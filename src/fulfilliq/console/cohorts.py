"""HTTP-only durable cohort workflow; the worker owns scoring and the API owns ranking."""

import math
from urllib.parse import urlencode

import pandas as pd
import streamlit as st


def cohort_panel(client, filters: dict, candidate_count: int, statuses: list[str]):
    jobs = client.get("/scoring-jobs", limit=50)
    maximum = jobs["max_cohort_size"]
    st.caption(f"Active discovery cohort: {candidate_count:,} candidates · maximum {maximum:,}. "
               "Creation freezes all matching IDs, independently of candidate-page pagination.")
    with st.expander("Filters to freeze"):
        st.json(filters)
    if filters.get("delivery_outcome") or filters.get("order_status"):
        st.warning("This selection uses retrospective outcomes/status. It is not a pre-delivery prioritization benchmark.")
    if st.button("Create persistent cohort job", disabled=not 0 < candidate_count <= maximum):
        created = client.post("/scoring-jobs", {"filters": filters, "review_capacity": min(20, candidate_count)})
        st.session_state["cohort_job"] = created["job_id"]
        st.rerun()
    if candidate_count > maximum:
        st.info("Narrow date, region, seller or category filters before creating a job.")
    job_pages = max(1, math.ceil(jobs["total"] / 50))
    job_page = int(st.number_input("Saved job page", min_value=1, max_value=job_pages, value=1))
    if job_page > 1:
        jobs = client.get("/scoring-jobs", limit=50, offset=(job_page - 1)*50)
    if not jobs["items"]:
        st.info("No saved jobs yet. The local worker starts with scripts/start_app.sh.")
        return None
    by_id = {row["job_id"]: row for row in jobs["items"]}
    identifiers = list(by_id)
    previous = st.session_state.get("cohort_job")
    identifier = st.selectbox("Saved cohort job", identifiers,
                             index=identifiers.index(previous) if previous in identifiers else 0,
                             format_func=lambda value: f"{value[:8]} · {by_id[value]['status']} · {by_id[value]['candidate_count']} candidates")
    st.session_state["cohort_job"] = identifier
    job = client.get("/scoring-jobs/" + identifier)
    st.progress(job["processed_count"] / job["candidate_count"], text=f"{job['status']} · {job['processed_count']}/{job['candidate_count']} processed")
    st.caption(f"Scored {job['scored_count']} · unavailable {job['unavailable_count']} · updated {job['updated_at_utc']}")
    st.caption(f"Model {job['model_version']} · warehouse snapshot {job['warehouse_snapshot']}")
    with st.expander("Frozen job cohort and provenance"):
        st.json(job)
    if job["retrospective_selection"]:
        st.caption("Frozen selection uses retrospective status/outcome filters; this is a historical replay.")
    context = st.session_state.get("model_context")
    if context != [job["warehouse_snapshot"], job["model_version"]]:
        st.warning("The recorded snapshot differs from the active one. Scores are historical; order details use the current warehouse.")
    cols = st.columns(3)
    if cols[0].button("Refresh cohort progress"):
        st.rerun()
    if job["status"] in ("pending", "running") and cols[1].button("Cancel cohort job"):
        client.post(f"/scoring-jobs/{identifier}/cancel", {})
        st.rerun()
    if job["status"] in ("failed", "canceled", "stale") and cols[2].button("Resume cohort job"):
        client.post(f"/scoring-jobs/{identifier}/resume", {})
        st.rerun()
    if job["error_summary"]:
        st.error(job["error_summary"])
    st.caption("Pending work needs the local worker. After an unexpected stop, an active lease can take up to 180 seconds to expire.")
    mode = st.selectbox("Cohort review capacity", ["Top N", "Percent of scored orders"])
    if mode == "Top N":
        capacity = int(st.number_input("Orders to review", min_value=0, max_value=job["candidate_count"],
                                        value=min(job["review_capacity"], job["candidate_count"])))
    else:
        percentage = st.number_input("Percent to review", min_value=0, max_value=100, value=10)
        capacity = math.ceil(job["scored_count"] * percentage / 100)
    state = st.selectbox("Cohort investigation status", ["all"] + statuses)
    unavailable = st.checkbox("Include unavailable cohort orders")
    result_page = int(st.number_input("Cohort result page", min_value=1, value=1))
    params = {"capacity": capacity, "review_status": None if state == "all" else state,
              "include_unavailable": unavailable}
    result = client.get(f"/scoring-jobs/{identifier}/results", **params, limit=50, offset=(result_page - 1)*50)
    if job["ranking_complete"]:
        st.success("Complete cohort-wide ranking · every frozen candidate has a recorded scoring outcome.")
    else:
        st.info("Preliminary partial results — not a complete cohort-wide ranking.")
    st.caption(result["interpretation"])
    st.caption(f"{result['total']} matching recorded results · page {result_page} (50 rows maximum)")
    rows = result["items"]
    if rows:
        st.dataframe(pd.json_normalize([{key: value for key, value in row.items() if key != "prediction"} for row in rows]),
                     hide_index=True, width="stretch")
        selected = st.selectbox("Inspect cohort order", [row["order_id"] for row in rows])
        if st.button("Investigate cohort order"):
            row = next(row for row in rows if row["order_id"] == selected)
            st.session_state["cohort_open"] = (identifier, selected, row["prediction"])
            st.rerun()
    else:
        st.info("No recorded results match this result page/filter. Refresh progress or select another page.")
    query = urlencode({key: str(value).lower() if isinstance(value, bool) else value
                       for key, value in params.items() if value is not None})
    st.link_button("Export full filtered cohort CSV", client.url + f"/api/v1/scoring-jobs/{identifier}/export.csv?" + query)
    opened = st.session_state.get("cohort_open")
    if opened and opened[0] == identifier:
        if st.button("Return to quick page analysis"):
            st.session_state.pop("cohort_open", None)
            st.rerun()
        return opened[1], opened[2]
    return None
