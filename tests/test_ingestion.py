import csv
import json

import pytest
from sqlalchemy import text

from fulfilliq.analytics.service import logistics_summary
from fulfilliq.db.connection import make_engine
from fulfilliq.db.integrity import verify_database
from fulfilliq.db.schema import SOURCES
from fulfilliq.ingestion.pipeline import ingest
from fulfilliq.ingestion.validation import DataValidationError, load_source, sha256_file


def test_nine_sources_order_grain_totals_and_quality(raw_dir, tmp_path):
    db = tmp_path / "processed" / "fulfilliq.sqlite3"
    report = ingest(raw_dir, db, db.parent)
    assert report["status"] == "success"
    counts = report["verification"]["row_counts"]
    assert counts["orders"] == counts["fact_orders"] == 6
    assert counts["order_items"] == 4
    assert counts["order_payments"] == 4
    assert counts["order_reviews"] == 3
    assert counts["geolocation"] == 4
    assert set(spec.table.name for spec in SOURCES) <= set(counts)
    assert report["tables"]["orders"]["invalid_to_null"]["order_approved_at"] == 1
    assert report["tables"]["order_items"]["exact_duplicates_removed"] == 1
    assert report["tables"]["geolocation"]["invalid_to_null"]["geolocation_lat"] == 1
    assert report["relationship_checks"]["delivery_before_purchase"] == 1
    assert report["relationship_checks"]["products_without_category_translation"] == 1
    assert report["relationship_checks"]["delivered_missing_outcome_timestamps"] == 1
    engine = make_engine(db, readonly=True)
    try:
        with engine.connect() as conn:
            assert verify_database(conn)["integrity_check"] == "ok"
            row = (
                conn.execute(text("SELECT * FROM fact_orders WHERE order_id='o1'")).mappings().one()
            )
            assert (
                row["item_count"],
                row["seller_count"],
                row["payment_count"],
                row["review_count"],
            ) == (2, 2, 2, 2)
            assert row["items_value"] == 150
            assert row["freight_value"] == 15
            assert row["total_order_value"] == row["payment_total"] == 165
            assert row["total_product_weight_g"] == 300
            assert (row["is_late"], row["delay_days"]) == (1, 1)
            assert (
                conn.exec_driver_sql(
                    "SELECT is_late FROM fact_orders WHERE order_id='o2'"
                ).scalar_one()
                == 0
            )  # Delivered later on the promised day is still on time.
            missing = conn.exec_driver_sql(
                "SELECT total_order_value, payment_total, total_product_weight_g "
                "FROM fact_orders WHERE order_id='o4'"
            ).one()
            assert tuple(missing) == (None, None, None)
            assert conn.exec_driver_sql(
                "SELECT latitude, longitude FROM zip_centroids WHERE zip_code_prefix='00001'"
            ).one() == (-24, -46)
            assert (
                conn.exec_driver_sql(
                    "SELECT customer_zip_code_prefix FROM customers LIMIT 1"
                ).scalar_one()
                == "00001"
            )
            messages = conn.exec_driver_sql(
                "SELECT review_comment_message FROM order_reviews"
            ).scalars()
            assert set(messages) == {"Entrega atrasada, não chegou no prazo!", "NA", "Ótimo!"}
            summary = logistics_summary(conn)
            assert summary["overview"]["eligible_outcomes"] == 2
            assert summary["overview"]["late_orders"] == 1
            assert summary["overview"]["late_rate"] == 0.5
            assert summary["overview"]["excluded_outcomes"] == 4
            assert summary["overview"]["multi_seller_orders"] == 1
            assert summary["overview"]["delivery_duration_count"] == 2
            stored = json.loads(
                conn.exec_driver_sql("SELECT quality_json FROM etl_runs").scalar_one()
            )
            assert stored == report
    finally:
        engine.dispose()
    assert json.loads((db.parent / "data_quality.json").read_text()) == report


def test_repeat_ingestion_has_same_counts_and_statistics(raw_dir, tmp_path):
    db = tmp_path / "data.sqlite3"
    first = ingest(raw_dir, db, tmp_path)
    first_summary = json.loads((tmp_path / "logistics_summary.json").read_text())
    second = ingest(raw_dir, db, tmp_path)
    second_summary = json.loads((tmp_path / "logistics_summary.json").read_text())
    assert first["run_id"] != second["run_id"]
    assert first["verification"] == second["verification"]
    assert first["tables"] == second["tables"]
    first_summary.pop("run_id")
    second_summary.pop("run_id")
    assert first_summary == second_summary


@pytest.mark.parametrize("problem", ["missing_file", "missing_column", "conflicting_key", "orphan"])
def test_failure_preserves_previous_database(raw_dir, tmp_path, problem):
    db = tmp_path / "data.sqlite3"
    ingest(raw_dir, db, tmp_path)
    previous = sha256_file(db)
    orders = raw_dir / "olist_orders_dataset.csv"
    if problem == "missing_file":
        orders.unlink()
    elif problem == "missing_column":
        orders.write_text(orders.read_text().replace("customer_id,", "wrong_column,", 1))
    elif problem == "conflicting_key":
        lines = orders.read_text().splitlines()
        orders.write_text("\n".join(lines + [lines[1].replace("delivered", "shipped")]) + "\n")
    else:
        orders.write_text(orders.read_text().replace("o1,c1,", "o1,missing-customer,"))
    with pytest.raises(DataValidationError):
        ingest(raw_dir, db, tmp_path)
    assert sha256_file(db) == previous
    assert json.loads((tmp_path / "ingestion_failure.json").read_text())["status"] == "failed"
    assert not list(tmp_path.glob("*.staging"))
    assert not list(tmp_path.glob(".*.ingest.lock"))


def test_missing_files_are_reported_together(tmp_path):
    with pytest.raises(DataValidationError) as failure:
        ingest(tmp_path / "absent", tmp_path / "db.sqlite3", tmp_path / "reports")
    for spec in SOURCES:
        assert spec.filename in str(failure.value)
    assert not (tmp_path / "db.sqlite3").exists()


def test_invalid_keys_rejected_but_optional_numbers_are_null(raw_dir):
    spec = next(s for s in SOURCES if s.table.name == "order_items")
    path = raw_dir / spec.filename
    path.write_text(path.read_text().replace("o1,1,", "o1,1.5,"))
    with pytest.raises(DataValidationError, match="order_item_id"):
        load_source(path, spec)


def test_empty_source_rejected(raw_dir):
    spec = SOURCES[0]
    path = raw_dir / spec.filename
    path.write_text(",".join(spec.columns) + "\n")
    with pytest.raises(DataValidationError, match="empty"):
        load_source(path, spec)


def test_ingestion_lock_and_path_collision_protect_inputs(raw_dir, tmp_path):
    source = raw_dir / SOURCES[0].filename
    original = sha256_file(source)
    with pytest.raises(DataValidationError, match="overwrite"):
        ingest(raw_dir, source, tmp_path)
    assert sha256_file(source) == original
    db = tmp_path / "db.sqlite3"
    lock = tmp_path / ".db.sqlite3.ingest.lock"
    lock.touch()
    with pytest.raises(DataValidationError, match="already running"):
        ingest(raw_dir, db, tmp_path)
    assert lock.exists()


def test_no_eligible_outcomes_is_null_rate(raw_dir, tmp_path):
    path = raw_dir / "olist_orders_dataset.csv"
    path.write_text(path.read_text().replace(",delivered,", ",canceled,"))
    ingest(raw_dir, tmp_path / "db.sqlite3", tmp_path)
    overview = json.loads((tmp_path / "logistics_summary.json").read_text())["overview"]
    assert overview["eligible_outcomes"] == 0
    assert overview["late_rate"] is None


def test_extra_columns_reported_and_duplicate_headers_rejected(raw_dir):
    spec = SOURCES[0]
    path = raw_dir / spec.filename
    with path.open(newline="") as stream:
        rows = list(csv.reader(stream))
    with path.open("w", newline="") as stream:
        csv.writer(stream).writerows(
            [row + ["extra" if i == 0 else "x"] for i, row in enumerate(rows)]
        )
    _, report = load_source(path, spec)
    assert report["ignored_extra_columns"] == ["extra"]
    path.write_text(path.read_text().replace(",extra", ",product_category_name", 1))
    with pytest.raises(DataValidationError, match="unique"):
        load_source(path, spec)


def test_verify_detects_damaged_aggregate(raw_dir, tmp_path):
    db = tmp_path / "db.sqlite3"
    ingest(raw_dir, db, tmp_path)
    engine = make_engine(db)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("UPDATE fact_orders SET payment_total=999 WHERE order_id='o1'")
        with engine.connect() as conn, pytest.raises(ValueError, match="totals differ"):
            verify_database(conn)
    finally:
        engine.dispose()


def test_excess_csv_fields_are_not_silently_shifted_or_discarded(raw_dir):
    spec = SOURCES[0]
    path = raw_dir / spec.filename
    path.write_text(path.read_text().replace("livros,books", "livros,books,unexpected"))
    with pytest.raises(DataValidationError, match="cannot parse CSV"):
        load_source(path, spec)


def test_out_of_range_integer_becomes_null(raw_dir):
    spec = next(s for s in SOURCES if s.table.name == "products")
    path = raw_dir / spec.filename
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    rows[0]["product_photos_qty"] = "9223372036854775808.5"
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=spec.columns)
        writer.writeheader()
        writer.writerows(rows)
    frame, report = load_source(path, spec)
    assert report["invalid_to_null"]["product_photos_qty"] == 1
    assert frame["product_photos_qty"].isna().all()
