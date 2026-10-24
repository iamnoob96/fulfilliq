import numpy as np
import pandas as pd

from fulfilliq.ingestion.pipeline import ingest
from fulfilliq.nlp.reviews import (
    STOP_WORDS,
    analyze_reviews,
    normalize_text,
    review_themes,
    sentiment_baseline,
)


def test_portuguese_normalization_negation_and_themes():
    assert normalize_text(None) == ""
    assert normalize_text(np.nan) == ""
    assert normalize_text("NÃO recebi! Ótimo.") == "nao recebi otimo"
    assert "nao" not in STOP_WORDS and "sem" not in STOP_WORDS
    assert review_themes("Entrega atrasada, demorou muito.")["late_delivery"]
    assert review_themes("A caixa chegou amassada")["damaged_packaging"]
    assert review_themes("Produto errado e faltando uma peça")["missing_or_incorrect_items"]
    assert review_themes("Produto com defeito, não funciona")["product_quality"]
    positive = review_themes("Chegou antes do prazo, sem atraso")
    assert positive["positive_delivery"] and not positive["late_delivery"]


def test_real_schema_review_aggregation_preserves_multiple_reviews(raw_dir, tmp_path):
    db = tmp_path / "db.sqlite3"
    ingest(raw_dir, db, tmp_path)
    report = analyze_reviews(db, tmp_path / "artifacts")
    assert report["total_review_records"] == 3
    assert report["reviews_with_text"] == 3
    assert report["theme_counts"]["late_delivery"] == 1
    assert report["sentiment"]["status"] == "insufficient_labeled_text"
    assert {row["group"]: row["review_count"] for row in report["by_seller"]} == {"s1": 3, "s2": 2}


def test_sentiment_chronological_split_and_unique_texts(tmp_path):
    # Distinct alphabetic suffixes prevent template dedup from collapsing this controlled fixture.
    n = 100
    texts = [
        ("otimo entrega rapida " if i % 2 else "pessimo produto ruim ")
        + chr(97 + i // 26)
        + chr(97 + i % 26)
        for i in range(n)
    ]
    frame = pd.DataFrame(
        {
            "normalized_text": texts,
            "review_score": [5 if i % 2 else 1 for i in range(n)],
            "authored_at": pd.date_range("2018-01-01", periods=n),
            "review_row_id": range(n),
        }
    )
    report = sentiment_baseline(frame, tmp_path)
    assert report["status"] == "trained"
    assert report["train_count"] == 80 and report["test_count"] == 20
    assert report["last_training_review"] < report["split_at"]
    assert report["accuracy"] == 1
    assert (tmp_path / "reviews" / "sentiment.joblib").is_file()
