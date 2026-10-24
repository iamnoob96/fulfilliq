"""Fit on train, choose model/threshold on validation, evaluate once on held-out test."""

import importlib.metadata
import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import joblib
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sqlalchemy import text
from threadpoolctl import threadpool_limits

from fulfilliq.db.connection import make_engine
from fulfilliq.features.orders import (
    CATEGORICAL_FEATURES,
    FEATURE_VERSION,
    FEATURES,
    NUMERIC_FEATURES,
    TARGET_DEFINITION,
    build_dataset,
)
from fulfilliq.ingestion.download import write_json
from fulfilliq.ingestion.validation import sha256_file
from fulfilliq.modeling.evaluation import choose_threshold, evaluate
from fulfilliq.modeling.temporal import chronological_split

logger = logging.getLogger(__name__)
SEED = 42


def preprocessing() -> ColumnTransformer:
    return ColumnTransformer(
        [
            (
                "numeric",
                Pipeline(
                    [
                        (
                            "impute",
                            SimpleImputer(
                                strategy="median", add_indicator=True, keep_empty_features=True
                            ),
                        ),
                        ("scale", StandardScaler()),
                    ]
                ),
                NUMERIC_FEATURES,
            ),
            (
                "categorical",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="constant", fill_value="unknown")),
                        (
                            "onehot",
                            OneHotEncoder(
                                handle_unknown="ignore", min_frequency=20, sparse_output=False
                            ),
                        ),
                    ]
                ),
                CATEGORICAL_FEATURES,
            ),
        ],
        sparse_threshold=0,
    )


def model_candidates(*, quick: bool = False) -> dict:
    return {
        "logistic_regression": LogisticRegression(C=0.5, max_iter=1000, random_state=SEED),
        "random_forest": RandomForestClassifier(
            n_estimators=30 if quick else 160,
            max_depth=14,
            min_samples_leaf=10,
            max_features=0.7,
            n_jobs=2,
            random_state=SEED,
        ),
        "hist_gradient_boosting": HistGradientBoostingClassifier(
            max_iter=25 if quick else 160,
            learning_rate=0.06,
            max_leaf_nodes=15,
            min_samples_leaf=30,
            l2_regularization=1,
            early_stopping=False,
            random_state=SEED,
        ),
    }


def dataset_identity(database_path: Path) -> dict:
    engine = make_engine(database_path, readonly=True)
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT run_id, quality_json FROM etl_runs")).one()
    finally:
        engine.dispose()
    quality = json.loads(row.quality_json)
    return {
        "etl_run_id": row.run_id,
        "source_sha256": {name: value["sha256"] for name, value in quality["tables"].items()},
    }


def train_delivery_model(
    database_path: Path,
    artifact_dir: Path,
    *,
    maturity_days: int = 14,
    lag_days: int = 1,
    window_days: int = 180,
    quick: bool = False,
    frame=None,
    history=None,
    as_of=None,
) -> dict:
    os.environ.setdefault("LOKY_MAX_CPU_COUNT", "2")
    if frame is None:
        frame, history, _, _ = build_dataset(
            database_path, lag_days=lag_days, window_days=window_days
        )
    split = chronological_split(frame, maturity_days=maturity_days, as_of=as_of)
    for category in CATEGORICAL_FEATURES:
        frame[category] = frame[category].fillna("unknown")
        for subset in (split.train, split.validation, split.test):
            subset[category] = subset[category].fillna("unknown")
    x_train, y_train = split.train[FEATURES], split.train.target_is_late.astype(int)
    x_val, y_val = split.validation[FEATURES], split.validation.target_is_late.astype(int)
    x_test, y_test = split.test[FEATURES], split.test.target_is_late.astype(int)
    fitted, comparisons = {}, {}
    with threadpool_limits(limits=2):
        for name, estimator in model_candidates(quick=quick).items():
            start = perf_counter()
            pipeline = Pipeline([("preprocess", preprocessing()), ("classifier", estimator)])
            pipeline.fit(x_train, y_train)
            val_probabilities = pipeline.predict_proba(x_val)[:, 1]
            threshold = choose_threshold(y_val, val_probabilities)
            comparisons[name] = {
                "validation": evaluate(y_val, val_probabilities, threshold),
                "fit_seconds": perf_counter() - start,
            }
            fitted[name] = pipeline
            logger.info(
                "Fitted %s; validation average precision=%.4f",
                name,
                comparisons[name]["validation"]["pr_auc_average_precision"],
            )
        selected = max(
            comparisons,
            key=lambda name: comparisons[name]["validation"]["pr_auc_average_precision"],
        )
        pipeline = fitted[selected]
        threshold = comparisons[selected]["validation"]["threshold"]
        # Test metrics for all specified candidates are reported, but never consulted for selection.
        for name, candidate in fitted.items():
            comparisons[name]["test"] = evaluate(
                y_test,
                candidate.predict_proba(x_test)[:, 1],
                comparisons[name]["validation"]["threshold"],
            )
        importance_sample = split.validation.sample(
            min(2000, len(split.validation)), random_state=SEED
        )
        importance = permutation_importance(
            pipeline,
            importance_sample[FEATURES],
            importance_sample.target_is_late.astype(int),
            scoring="average_precision",
            n_repeats=3,
            random_state=SEED,
            n_jobs=1,
        )
    base_probability = float(y_train.mean())
    baselines = {}
    for name, values in (
        ("training_prevalence", np.full(len(y_test), base_probability)),
        ("seller_history", x_test.seller_history_late_rate.fillna(base_probability).to_numpy()),
    ):
        baselines[name] = evaluate(y_test, values, 0.5)
    version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    metadata = {
        "model_version": version,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "selected_model": selected,
        "selection_metric": "validation average precision",
        "threshold_selection": "maximum validation F1; higher threshold breaks ties",
        "threshold": threshold,
        "target_definition": TARGET_DEFINITION,
        "feature_version": FEATURE_VERSION,
        "features": FEATURES,
        "seed": SEED,
        "history_lag_days": lag_days,
        "history_window_days": window_days,
        "split": split.metadata,
        "comparison": comparisons,
        "baselines": baselines,
        "feature_importance": sorted(
            [
                {"feature": name, "average_precision_decrease": float(mean), "std": float(std)}
                for name, mean, std in zip(
                    FEATURES, importance.importances_mean, importance.importances_std, strict=True
                )
            ],
            key=lambda row: -row["average_precision_decrease"],
        ),
        "importance_method": "permutation average-precision decrease on validation sample",
        "dataset": dataset_identity(database_path),
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("scikit-learn", "pandas", "numpy", "joblib", "fulfilliq")
        },
        "limitations": [
            "Offline historical simulation, not validated for current commercial traffic",
            "Static product/seller/promise attributes assumed available at checkout",
            "Label observation time approximated by delivery plus reporting lag",
            "No observed outcomes for canceled/undelivered orders; selection bias remains",
            "Interventions and causes cannot be established from these predictions",
        ],
    }
    root = artifact_dir / "delivery"
    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".training-", dir=root))
    try:
        joblib.dump(
            {"pipeline": pipeline, "history": history}, staging / "model.joblib", compress=3
        )
        metadata["model_sha256"] = sha256_file(staging / "model.joblib")
        write_json(staging / "metadata.json", metadata)
        os.replace(staging, root / version)
        write_json(root / "current.json", {"version": version})
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return metadata
