"""Interpretable Portuguese review analysis without an external model/API."""

import re
import unicodedata
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, roc_auc_score
from sklearn.pipeline import Pipeline
from sqlalchemy import text
from threadpoolctl import threadpool_limits

from fulfilliq.db.connection import make_engine

# Curated function words. Deliberately retain nao/sem/nunca for Portuguese negation.
STOP_WORDS = list(
    dict.fromkeys(
        "a o as os um uma uns umas de da do das dos e em no na nos nas "
        "por para com ao aos que se eu ele ela eles elas meu minha meus minhas seu sua seus suas "
        "este esta estes estas esse essa esses essas isso isto aquele aquela aquilo foi foram "
        "ser estar ter tenho tinha havia ha sou estou era sao e ja ate entre pelo pela pelos pelas "
        "me te lhe lhes voce voces nos vos quando onde como qual quais quem porque pois ou mas "
        "ainda tambem entao mais menos mesmo mesma cada todo toda todos todas vez vezes".split()
    )
)

THEMES = {
    "late_delivery": r"\batras(?:o|ou|ad[oa]s?|ando|ar)?\b|\bdemor(?:a|ou|ad[oa]s?|ando)\b|fora do prazo|nunca cheg",
    "damaged_packaging": r"(?:embalag\w*|caixa|pacote).{0,35}(?:danific|rasgad|amass|abert)|(?:danific|rasgad|amass).{0,35}(?:embalag|caixa|pacote)",
    "missing_or_incorrect_items": r"nao (?:recebi|recebido|entreg\w*|veio)|falt(?:ou|ando)|pedido incompleto|produto errado|veio errado|item errado",
    "product_quality": r"defeito|quebrad|nao funciona|qualidade (?:ruim|pessima)|produto (?:ruim|danificad)",
    "positive_delivery": r"antes do prazo|entrega rapida|chegou (?:bem|rapido|no prazo)|(?:entregue|recebi|entrega) (?:no|dentro do) prazo|nao atrasou|sem atraso",
}
COMPLAINT_THEMES = ["late_delivery", "damaged_packaging", "missing_or_incorrect_items"]


def normalize_text(value) -> str:
    if value is None or pd.isna(value):
        return ""
    value = unicodedata.normalize("NFKD", str(value).lower())
    value = "".join(character for character in value if not unicodedata.combining(character))
    value = re.sub(r"https?://\S+|\b\S+@\S+\b", " ", value)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z\s]", " ", value)).strip()


def review_themes(value: str) -> dict[str, bool]:
    normalized = normalize_text(value)
    # Remove explicit non-delay phrases only from the late-delivery matching context.
    late_context = re.sub(r"\b(?:nao atrasou|sem atraso|nao houve atraso)\b", "", normalized)
    return {
        name: bool(re.search(pattern, late_context if name == "late_delivery" else normalized))
        for name, pattern in THEMES.items()
    }


def vectorizer(*, min_df: int = 2):
    return TfidfVectorizer(
        stop_words=STOP_WORDS,
        ngram_range=(1, 2),
        max_features=8000,
        min_df=min_df,
        sublinear_tf=True,
        token_pattern=r"(?u)\b[a-z]{2,}\b",
    )


def sentiment_baseline(reviews: pd.DataFrame, artifact_dir: Path) -> dict:
    labeled = reviews.loc[
        reviews.normalized_text.ne("")
        & reviews.review_score.isin([1, 2, 4, 5])
        & reviews.authored_at.notna()
    ].sort_values(["authored_at", "review_row_id"])
    # A repeated template must not appear on both sides of the sentiment evaluation.
    unique = labeled.drop_duplicates("normalized_text", keep="first").copy()
    if len(unique) < 30:
        return {
            "status": "insufficient_labeled_text",
            "unique_texts": len(unique),
            "label_source": "stars 1-2 negative, 4-5 positive; 3 excluded",
        }
    boundary = unique.authored_at.iloc[int(len(unique) * 0.8)]
    train = unique.loc[unique.authored_at.lt(boundary)]
    test = unique.loc[unique.authored_at.ge(boundary)]
    y_train = train.review_score.ge(4).astype(int)
    y_test = test.review_score.ge(4).astype(int)
    if y_train.nunique() < 2 or y_test.nunique() < 2:
        return {"status": "insufficient_label_classes", "unique_texts": len(unique)}
    pipeline = Pipeline(
        [
            ("tfidf", vectorizer()),
            ("classifier", LogisticRegression(C=1, max_iter=500, random_state=42)),
        ]
    )
    with threadpool_limits(limits=2):
        pipeline.fit(train.normalized_text, y_train)
        predicted = pipeline.predict(test.normalized_text)
        probability = pipeline.predict_proba(test.normalized_text)[:, 1]
    words = pipeline.named_steps["tfidf"].get_feature_names_out()
    weights = pipeline.named_steps["classifier"].coef_[0]
    folder = artifact_dir / "reviews"
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / ".sentiment.joblib.tmp"
    joblib.dump(pipeline, temporary, compress=3)
    temporary.replace(folder / "sentiment.joblib")
    return {
        "status": "trained",
        "model": "Portuguese TF-IDF + Logistic Regression",
        "label_source": "review stars: 1-2 negative, 4-5 positive; 3 excluded; noisy general sentiment",
        "unique_texts": len(unique),
        "duplicate_texts_excluded": len(labeled) - len(unique),
        "train_count": len(train),
        "test_count": len(test),
        "split_at": boundary.isoformat(),
        "last_training_review": train.authored_at.max().isoformat(),
        "accuracy": float(accuracy_score(y_test, predicted)),
        "majority_baseline_accuracy": float(max(y_test.mean(), 1 - y_test.mean())),
        "roc_auc": float(roc_auc_score(y_test, probability)),
        "classification_report": classification_report(
            y_test, predicted, output_dict=True, zero_division=0
        ),
        "confusion_matrix_negative_positive": confusion_matrix(
            y_test, predicted, labels=[0, 1]
        ).tolist(),
        "positive_terms": words[np.argsort(-weights)[:15]].tolist(),
        "negative_terms": words[np.argsort(weights)[:15]].tolist(),
        "limitations": "Star labels measure noisy general satisfaction, not verified logistical "
        "sentiment or complaint truth. This is a separate post-order NLP model.",
    }


def aggregate_groups(reviews: pd.DataFrame, memberships: pd.DataFrame, key: str) -> list[dict]:
    attached = reviews.merge(memberships[["order_id", key]].drop_duplicates(), on="order_id")
    result = []
    for identifier, group in attached.groupby(key, dropna=False):
        with_text = group.normalized_text.ne("")
        text_count = int(with_text.sum())
        complaint = int(group[COMPLAINT_THEMES].any(axis=1).sum())
        result.append(
            {
                "group": str(identifier) if pd.notna(identifier) else "unknown",
                "review_count": len(group),
                "text_review_count": text_count,
                "complaint_reviews": complaint,
                "complaint_fraction_of_text": complaint / text_count if text_count else None,
                "themes": {name: int(group[name].sum()) for name in THEMES},
            }
        )
    return sorted(
        result, key=lambda row: (-row["complaint_reviews"], -row["text_review_count"], row["group"])
    )


def analyze_reviews(database_path: Path, artifact_dir: Path) -> dict:
    engine = make_engine(database_path, readonly=True)
    try:
        with engine.connect() as conn:
            reviews = pd.read_sql_query(text("SELECT * FROM order_reviews"), conn)
            regions = pd.read_sql_query(
                text("""
                SELECT o.order_id, c.customer_state AS region FROM orders o
                JOIN customers c ON c.customer_id=o.customer_id
            """),
                conn,
            )
            members = pd.read_sql_query(
                text("""
                SELECT DISTINCT i.order_id, i.seller_id,
                  COALESCE(p.product_category_name_english,p.product_category_name,'unknown') AS category
                FROM order_items i JOIN dim_product p ON p.product_id=i.product_id
            """),
                conn,
            )
    finally:
        engine.dispose()
    reviews["authored_at"] = pd.to_datetime(reviews.review_answer_timestamp, errors="coerce")
    reviews["normalized_text"] = (
        reviews.review_comment_title.fillna("") + " " + reviews.review_comment_message.fillna("")
    ).map(normalize_text)
    themes = pd.DataFrame(reviews.normalized_text.map(review_themes).tolist(), index=reviews.index)
    reviews = pd.concat([reviews, themes], axis=1)
    with_text = reviews.loc[reviews.normalized_text.ne("")]
    keywords = {name: [] for name in THEMES}
    if len(with_text):
        tfidf = vectorizer(min_df=1)
        try:
            matrix = tfidf.fit_transform(with_text.normalized_text)
            words = tfidf.get_feature_names_out()
            for name in THEMES:
                mask = with_text[name].to_numpy(dtype=bool)
                if mask.any():
                    mean = np.asarray(matrix[mask].mean(axis=0)).ravel()
                    keywords[name] = words[np.argsort(-mean)[:10]].tolist()
        except ValueError as exc:
            if "empty vocabulary" not in str(exc):
                raise
    sentiment = sentiment_baseline(reviews, artifact_dir)
    counts = {name: int(reviews[name].sum()) for name in THEMES}
    return {
        "language": "Portuguese",
        "total_review_records": len(reviews),
        "reviews_with_text": len(with_text),
        "reviews_without_text": len(reviews) - len(with_text),
        "theme_counts": counts,
        "theme_keywords": keywords,
        "complaint_reviews": int(reviews[COMPLAINT_THEMES].any(axis=1).sum()),
        "sentiment": sentiment,
        "by_seller": aggregate_groups(reviews, members, "seller_id"),
        "by_category": aggregate_groups(reviews, members, "category"),
        "by_region": aggregate_groups(reviews, regions, "region"),
        "theme_patterns": THEMES,
        "interpretation": "Themes are overlapping lexical evidence, not verified labels or "
        "validated complaint classifiers. No recall/precision is claimed for "
        "theme rules. Multi-seller/category review associations are non-additive. "
        "Reviews are post-order evidence and never purchase-time risk features.",
    }
