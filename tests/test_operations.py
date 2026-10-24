from datetime import date

import pytest

from fulfilliq.analytics.operations import CohortFilter, OperationsService
from fulfilliq.analytics.store import InsightUnavailable, load_insight, save_insight
from fulfilliq.ingestion.pipeline import ingest


def test_cohort_filters_and_shared_order_grain(raw_dir, tmp_path):
    db = tmp_path / "db.sqlite3"
    ingest(raw_dir, db, tmp_path)
    service = OperationsService(db)
    overview = service.overview()
    assert overview["total_orders"] == 6
    assert overview["eligible_outcomes"] == overview["late_orders"] == 2
    assert service.overview(CohortFilter(seller_id="s2"))["total_orders"] == 1
    assert service.overview(CohortFilter(region="AM"))["total_orders"] == 0
    assert service.overview(CohortFilter(start_date=date(2018, 1, 5)))["total_orders"] == 1
    groups = service.performance("seller")
    assert {row["group"]: row["total_orders"] for row in groups} == {"s1": 3, "s2": 1}
    assert (
        service.performance("category", CohortFilter(seller_id="s2"))[0]["group"] == "sem_traducao"
    )
    bottlenecks = service.bottlenecks("region", min_orders=1)
    assert bottlenecks["items"][0]["longest_median_stage"] == "transit_days"
    assert overview["durations"]["purchase_to_carrier_days"]["count"] == 1
    with pytest.raises(ValueError):
        CohortFilter(start_date=date(2019, 1, 1), end_date=date(2018, 1, 1))
    with pytest.raises(ValueError):
        service.performance("unsupported")


def test_analytical_snapshot_provenance(raw_dir, tmp_path):
    db, artifacts = tmp_path / "db.sqlite3", tmp_path / "artifacts"
    ingest(raw_dir, db, tmp_path)
    with pytest.raises(InsightUnavailable):
        load_insight(artifacts, "operations", db)
    save_insight(artifacts, "operations", {"overview": {"total_orders": 6}}, db)
    assert load_insight(artifacts, "operations", db)["overview"]["total_orders"] == 6
