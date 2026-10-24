"""Local Streamlit operations console. Run via scripts/start_app.sh."""

import json
from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

from fulfilliq.console.client import BackendClient, BackendError

st.set_page_config(page_title="FulfillIQ · Operations", page_icon="📦", layout="wide")
client = BackendClient()
NAVIGATION = ["Overview", "Orders & review queue", "Logistics", "Seller intelligence",
              "Data mining", "Review intelligence", "Model evaluation", "Reports & R"]
STATUSES = ["pending", "investigating", "reviewed", "escalated", "resolved"]


def table(rows, name="table", *, export=False):
    frame = pd.json_normalize(rows)
    if frame.empty:
        st.info("No records match this selection.")
        return frame
    st.dataframe(frame, hide_index=True, width="stretch")
    if export:
        st.download_button("Download CSV", frame.to_csv(index=False).encode(),
                           file_name=name + ".csv", mime="text/csv", key="download_" + name)
    return frame


def chart(rows, x, y, title, *, kind="bar", **kwargs):
    if not rows:
        st.info("No data available for " + title.lower() + ".")
        return
    function = {"bar": px.bar, "line": px.line, "scatter": px.scatter}[kind]
    figure = function(pd.json_normalize(rows), x=x, y=y, title=title,
                      template="plotly_white", **kwargs)
    st.plotly_chart(figure, width="stretch")


def performance(params, group="region", limit=100):
    return client.get("/analytics/delivery-performance", **params,
                      group_by=group, min_orders=1, limit=limit)


def show_overview(params):
    summary = client.get("/analytics/overview", **params)
    cols = st.columns(4)
    cols[0].metric("Historical orders", f"{summary['total_orders']:,}")
    rate = summary["late_rate"]
    cols[1].metric("On-time delivery", f"{1-rate:.1%}" if rate is not None else "Unavailable")
    cols[2].metric("Late delivery", f"{rate:.1%}" if rate is not None else "Unavailable")
    duration = summary["durations"]["fulfillment_days"]["mean"]
    cols[3].metric("Approval → carrier", f"{duration:.1f} days" if duration is not None else "Unavailable")
    st.caption(f"Rates use {summary['eligible_outcomes']:,} valid delivered outcomes; "
               f"{summary['excluded_outcomes']:,} missing, invalid or unresolved outcomes excluded. "
               "Late = actual timestamp > promised timestamp. Original mart calendar-day flags differ.")
    st.caption("Duration means omit missing/invalid milestones. Lateness includes zero for on-time orders.")
    stages = [{"stage": key.replace("_", " "), **value} for key, value in summary["durations"].items()]
    left, right = st.columns(2)
    with left:
        chart(summary["monthly_volume"], "month", "orders", "Order volume over time", kind="line")
        chart(stages, "stage", "mean", "Mean observed stage durations (days)")
    with right:
        regions = performance(params)["items"]
        chart(regions, "group", "late_rate", "Late rate by customer state")
        st.metric("Active sellers in cohort", summary["active_sellers"])
        chart(regions, "group", "total_orders", "Order volume by customer state")
    with st.expander("Definitions and denominators"):
        st.json(summary)


def order_details(identifier):
    detail = client.get("/orders/" + identifier)
    st.subheader("Order " + identifier)
    st.caption(detail["interpretation"])
    st.markdown("**Placement-time inputs**")
    st.json(detail["placement"], expanded=True)
    table(detail["products"], "products")
    with st.expander("Subsequent historical outcomes · excluded from replay inputs"):
        st.json(detail["observed_after_purchase"])
    if detail["replay_payload"]:
        if st.button("Score this historical order", key="score_detail_" + identifier):
            result = client.post("/orders/replay", {"order_ids": [identifier], "review_capacity": 1})
            st.json(result)
    else:
        st.warning(detail["replay_unavailable_reason"])
    state = detail["review"]
    st.markdown("**Human review decision**")
    with st.form("review_" + identifier):
        status = st.selectbox("Investigation status", STATUSES, index=STATUSES.index(state["status"]))
        notes = st.text_area("Investigation notes · avoid personal or sensitive information",
                             state["notes"], max_chars=5000)
        st.caption(f"Saved revision {state['revision']} · updated {state['updated_at_utc'] or 'never'}")
        if st.form_submit_button("Save review"):
            saved = client.put(f"/orders/{identifier}/review", {
                "status": status, "notes": notes, "expected_revision": state["revision"]})
            st.success(f"Review saved · revision {saved['revision']}. Reload to see refreshed queue filters.")


def show_orders(params):
    st.info("Historical replay uses the existing saved model. Candidate selection is chronological; "
            "ranking covers only the submitted page of at most 100 orders. Scores are uncertain, "
            "and this replay is not independent model validation.")
    cols = st.columns(3)
    status = cols[0].selectbox("Workflow filter", ["all"] + STATUSES)
    size = cols[1].selectbox("Candidates per page", [25, 50, 100], index=1)
    page = int(cols[2].number_input("Page", min_value=1, value=1))
    cohort = {**params, "review_status": None if status == "all" else status,
              "limit": size, "offset": (page-1)*size}
    listing = client.get("/orders", **cohort)
    st.caption(f"{listing['total']:,} matching orders · page {page}")
    table(listing["items"], "candidate_orders", export=True)
    identifiers = [row["order_id"] for row in listing["items"]]
    if identifiers:
        capacity = st.slider("Review capacity within this page", 0, len(identifiers), min(10, len(identifiers)))
        if st.button("Score candidate page", type="primary"):
            with st.spinner("Scoring saved model through FastAPI…"):
                st.session_state["queue"] = client.post("/orders/replay", {
                    "order_ids": identifiers, "review_capacity": capacity})
                st.session_state["queue_cohort"] = json.dumps(cohort, sort_keys=True)
        queue = st.session_state.get("queue")
        if queue and st.session_state.get("queue_cohort") == json.dumps(cohort, sort_keys=True):
            st.subheader("Risk-ranked review queue")
            st.caption(queue["interpretation"])
            priorities = queue["review_order_ids"]
            states = {row["order_id"]: row["review_status"] for row in listing["items"]}
            ranked = sorted(queue["predictions"], key=lambda row: -row["delay_probability"])
            table([{**row, "within_review_capacity": row["order_id"] in priorities,
                    "review_status": states[row["order_id"]]} for row in ranked], "review_queue", export=True)
            if queue["unavailable"]:
                st.warning("Some orders cannot be reconstructed honestly.")
                table(queue["unavailable"], "unavailable")
        inspection_ids = identifiers
        if queue and st.session_state.get("queue_cohort") == json.dumps(cohort, sort_keys=True):
            ordered_ids = [row["order_id"] for row in sorted(
                queue["predictions"], key=lambda row: -row["delay_probability"])]
            inspection_ids = ordered_ids + [value for value in identifiers if value not in ordered_ids]
        selected = st.selectbox("Inspect candidate order", inspection_ids)
        order_details(selected)
    with st.expander("Find a historical order by identifier"):
        identifier = st.text_input("Order identifier")
        if identifier and identifier.strip() not in ([selected] if identifiers else []):
            order_details(identifier.strip())
    with st.expander("Score a checkout payload through the existing prediction API"):
        st.caption("Use the checkout schema from Swagger. Outcomes/reviews are rejected by the backend.")
        payload = st.text_area("Checkout JSON", height=180)
        if st.button("Score checkout payload"):
            try:
                st.json(client.post("/orders/predict-delay", json.loads(payload)))
            except json.JSONDecodeError:
                st.error("Enter valid JSON using the documented checkout schema.")


def show_logistics(params):
    group = st.selectbox("Compare by", ["region", "seller", "category", "month"])
    rows = performance(params, group, 100)["items"]
    chart(rows, "group", "late_rate", "Historical late delivery rate", kind="line" if group == "month" else "bar")
    chart(rows, "group", "durations.delivery_days.mean", "Mean purchase-to-delivery duration (days)")
    result = client.get("/analytics/bottlenecks", **params, group_by=group, min_orders=5)
    st.caption(result["interpretation"])
    table(result["items"], "bottlenecks", export=True)
    st.caption("Tables show the first 100 groups sorted by late rate. Report exports include regional totals.")
    st.subheader("Unusual logistics observations · full-history snapshot")
    table(client.get("/mining/anomalies", kind="region")["items"], "regional_anomalies")


def show_seller(options):
    st.caption("Seller intelligence and peer segments summarize full history; overview date filters do not apply.")
    identifier = st.selectbox("Seller", options["seller_ids"])
    result = client.get(f"/sellers/{identifier}/insights")
    if result["performance"]:
        table([result["performance"]], "seller_performance")
    for warning in result["warnings"]:
        st.warning(warning)
    if result["segment"]:
        segment = result["segment"]
        st.subheader(segment["segment_name"])
        table([segment["features"]], "seller_features")
        peers = client.get("/sellers/segments", segment_id=segment["segment_id"], limit=100)
        st.caption(f"Peers in the same measured segment · first {len(peers['items'])} of {peers['total']}")
        chart(peers["items"], "features.order_volume", "features.late_rate",
              "Similar sellers · volume versus historical late rate", kind="scatter",
              hover_name="seller_id")
    table(result["anomalies"], "seller_anomalies")
    if result["reviews"]:
        table([result["reviews"]], "seller_complaints")


def show_mining():
    st.caption("Full-history exploratory snapshots. Shared orders and lexical evidence do not prove causes.")
    tab_rules, tab_segments, tab_anomalies = st.tabs(["Apriori & FP-Growth", "Seller clustering", "Anomalies"])
    with tab_rules:
        st.write("Apriori enumerates frequent candidates; FP-Growth compresses transactions into a prefix tree. "
                 "Both mine identical discretized baskets and verify matching supports offline.")
        algorithm = st.selectbox("Mining algorithm", ["apriori", "fp_growth"])
        support = st.number_input("Minimum displayed support", min_value=0.0, max_value=1.0, value=0.01, step=0.01)
        rules = client.get("/mining/association-rules", min_support=support)
        st.caption(rules["interpretation"])
        table([{"algorithm": name, **value} for name, value in rules["algorithms"].items()], "algorithm_comparison")
        st.markdown("**Rules with late-delivery consequent**")
        table(rules["items"], "association_rules", export=True)
        st.caption("Confidence = subgroup late rate; lift compares it to overall late prevalence.")
        st.markdown("**Frequent itemsets**")
        itemsets = client.get("/mining/itemsets", algorithm=algorithm, min_support=support, limit=500)
        st.caption(f"Showing {len(itemsets['items'])} of {itemsets['total']} itemsets.")
        table(itemsets["items"], "frequent_itemsets", export=True)
    with tab_segments:
        segments = client.get("/sellers/segments", limit=100)
        st.write(segments["method"])
        st.caption(segments["interpretation"])
        chart(segments["segments"], "name", "sellers", "Seller segment sizes")
        table(segments["segments"], "segments", export=True)
        st.caption(f"Silhouette {segments['silhouette']:.3f}; stability ARI {segments['mean_stability_ari']:.3f}; "
                   f"{segments['excluded_low_volume_sellers']} low-volume sellers excluded.")
    with tab_anomalies:
        st.write("Isolation Forest screens unusual shipping features; robust statistical thresholds screen "
                 "historical seller/region rates and durations. These are investigation signals.")
        kind = st.selectbox("Anomaly entity", ["order", "seller", "region", "seller_fulfillment"])
        result = client.get("/mining/anomalies", kind=kind, limit=100)
        st.caption(result["interpretation"])
        table(result["items"], "anomalies", export=True)
        st.caption(f"Showing first {len(result['items'])} of {result['total']} observations.")


def show_reviews(params):
    st.caption("Saved theme and sentiment summaries cover full history. Excerpt/score filters use seller, "
               "region and category below; date filters do not apply. Reviews never enter replay risk inputs.")
    group = st.selectbox("Complaint groups", ["category", "seller", "region"])
    result = client.get("/reviews/insights", group_by=group, min_text_reviews=5)
    summary = result["global_summary"]
    st.caption(result["interpretation"])
    chart([{"theme": key, "reviews": value} for key, value in summary["theme_counts"].items()],
          "theme", "reviews", "Overlapping logistics and product themes")
    table(result["items"], "complaint_groups", export=True)
    st.markdown("**Theme keywords**")
    st.json(summary["theme_keywords"])
    st.markdown("**Saved Portuguese TF-IDF sentiment baseline**")
    st.json(summary["sentiment"])
    st.warning("Star-derived sentiment measures noisy general satisfaction. Its accuracy does not validate "
               "logistics complaint detection; theme rules have no measured recall/precision.")
    evidence = client.get("/reviews/evidence", **{k: v for k, v in params.items()
                          if k in ("seller_id", "region", "product_category")})
    chart([{"score": key, "records": value} for key, value in evidence["score_counts"].items()],
          "score", "records", "Review score distribution · selected evidence cohort")
    st.caption(evidence["redaction"])
    table(evidence["examples"], "review_excerpts")


def show_model():
    info = client.get("/models/info")
    metrics = client.get("/models/metrics")
    st.write(f"Active saved model: **{info['selected_model']}** · `{info['model_version']}`")
    st.warning("Read-only evaluation. Historical test cohorts have already been inspected; they are not "
               "new independent evidence. No training, calibration or promotion controls are provided.")
    rows = []
    for name, candidate in metrics["comparison"].items():
        for split in ("validation", "test"):
            value = candidate[split]
            rows.append({"model": name, "cohort": split, **{key: value[key] for key in (
                "roc_auc", "pr_auc_average_precision", "precision", "recall", "f1",
                "brier_score", "precision_at_top_10_percent")}})
    table(rows, "saved_model_metrics", export=True)
    selected = metrics["comparison"][info["selected_model"]]["test"]
    chart(selected["calibration"], "predicted", "observed", "Saved test reliability summary", kind="scatter")
    st.json({"threshold": info["threshold"], "baselines": metrics["baselines"],
             "limitations": info["limitations"], "review_budgets": selected.get("review_budgets", {})})
    research = client.get("/models/research")
    st.caption(research["interpretation"])
    for report in research["reports"]:
        with st.expander(report["name"]):
            if report["available"]:
                st.json(report["summary"])
            else:
                st.info("Saved research report is not installed with this checkout.")


def show_reports(params):
    with st.expander("Backend dependencies and artifact readiness"):
        readiness = client.get("/console/dependencies")
        table(readiness["dependencies"], "dependency_readiness")
        st.caption(readiness["interpretation"])
    st.caption("Operational tables use the selected cohort. Mining findings retain their saved full-history scope.")
    report = client.get("/reports/operations", **params)
    st.download_button("Download consolidated Markdown report", report["markdown"],
                       file_name="fulfilliq-operations.md", mime="text/markdown")
    with st.expander("Preview consolidated report"):
        st.markdown(report["markdown"])
    for name in ("regions", "sellers", "bottlenecks", "rules"):
        with st.expander("Export " + name):
            table(report[name], "report_" + name, export=True)
    st.subheader("Optional R analysis")
    result = client.get("/reports/r")
    if not result["available"]:
        st.info(result["message"])
    else:
        summary = result["summary"]
        cols = st.columns(2)
        cols[0].metric("Shared Python/R transactions", f"{summary['transaction_count']:,}")
        cols[1].metric("Matching late-delivery rules", summary["comparison"]["rules_compared"])
        st.caption("Support, confidence and lift agree within 1e-8. Plots describe all valid "
                   "historical deliveries; associations do not demonstrate causes.")
        with st.expander("R execution and reproducibility details"):
            st.json(summary)
        for filename in result["files"]:
            url = client.url + "/api/v1/reports/r/files/" + filename
            if filename.endswith(".png"):
                st.image(url, caption=filename)
            else:
                st.link_button("Open " + filename, url)


def main():
    st.title("FulfillIQ")
    st.caption("Historical logistics intelligence · internal operations console")
    try:
        options = client.get("/console/options")
        st.sidebar.title("Operations")
        page = st.sidebar.radio("Navigate", NAVIGATION)
        st.sidebar.caption(f"Olist history: {options['first_purchase']} → {options['last_purchase']}")
        st.sidebar.markdown("**Historical cohort filters**")
        start = st.sidebar.date_input("Purchase from", date.fromisoformat(options["first_purchase"]))
        end = st.sidebar.date_input("Purchase through", date.fromisoformat(options["last_purchase"]))
        region = st.sidebar.selectbox("Customer state", ["All"] + options["regions"])
        seller = st.sidebar.selectbox("Seller filter", ["All"] + options["seller_ids"])
        category = st.sidebar.selectbox("Product category", ["All"] + options["categories"])
        params = {"start_date": start.isoformat(), "end_date": end.isoformat(),
                  "region": None if region == "All" else region,
                  "seller_id": None if seller == "All" else seller,
                  "product_category": None if category == "All" else category}
        st.sidebar.caption("Local demonstration. Human decisions persist separately from historical orders.")
        st.header(page)
        with st.spinner("Loading historical evidence…"):
            if page == "Overview":
                show_overview(params)
            elif page == "Orders & review queue":
                show_orders(params)
            elif page == "Logistics":
                show_logistics(params)
            elif page == "Seller intelligence":
                show_seller(options)
            elif page == "Data mining":
                show_mining()
            elif page == "Review intelligence":
                show_reviews(params)
            elif page == "Model evaluation":
                show_model()
            elif page == "Reports & R":
                show_reports(params)
    except BackendError as exc:
        st.error(str(exc))
        st.info("Verify backend health and prepare missing artifacts explicitly. Startup never trains models.")


main()
