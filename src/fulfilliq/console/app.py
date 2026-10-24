"""Local Streamlit operations console. Run via scripts/start_app.sh."""

import json
from datetime import date

import pandas as pd
import streamlit as st

from fulfilliq.console.client import BackendClient, BackendError, csv_export
from fulfilliq.console.cohorts import cohort_panel
from fulfilliq.console.theme import (
    PAGES,
    apply_theme,
    editorial_figure,
    facts,
    figure_title,
    finding,
    folio,
    masthead,
    page_header,
    review_quote,
    section,
)

st.set_page_config(
    page_title="FulfillIQ · The Logistics Intelligence Edition",
    page_icon="◒",
    layout="wide",
    initial_sidebar_state="expanded",
)
client = BackendClient()
NAVIGATION = [
    "Overview",
    "Orders & review queue",
    "Logistics",
    "Seller intelligence",
    "Data mining",
    "Review intelligence",
    "Model evaluation",
    "Reports & R",
]
STATUSES = ["pending", "investigating", "reviewed", "escalated", "resolved"]


def table(rows, name="table", *, export=False):
    frame = pd.json_normalize(rows)
    if frame.empty:
        st.info("No records match this selection.")
        return frame
    columns = {
        column: st.column_config.NumberColumn(
            column.replace("_", " ").capitalize(), format="percent"
        )
        for column in frame.columns
        if pd.api.types.is_numeric_dtype(frame[column])
        and (
            column.endswith("late_rate") or column in ("support", "confidence", "delay_probability")
        )
    }
    st.dataframe(frame, hide_index=True, width="stretch", column_config=columns)
    if export:
        st.caption(
            f"Export scope · these {len(frame):,} displayed rows, with their current filters and ordering."
        )
        st.download_button(
            "Download CSV",
            csv_export(frame),
            file_name=name + ".csv",
            mime="text/csv",
            key="download_" + name,
        )
    return frame


def chart(rows, x, y, title, *, kind="bar", **kwargs):
    if not rows:
        st.info("No data available for " + title.lower() + ".")
        return
    figure = editorial_figure(pd.json_normalize(rows), x, y, title, kind=kind, **kwargs)
    figure_title(title)
    figure.update_layout(title_text=None, margin={"t": 15})
    st.plotly_chart(figure, width="stretch", theme=None)


def itemset_label(token):
    names = {
        "customer_state": "Customer state",
        "seller_state": "Seller state",
        "category": "Product category",
        "distance_km": "Shipping distance",
        "items_value": "Order value",
        "freight_value": "Freight cost",
        "total_weight_g": "Product weight",
        "seller_history_late_rate": "Seller history",
        "outcome": "Delivery outcome",
    }
    field, _, value = token.partition("=")
    return f"{names.get(field, field.replace('_', ' ').title())}: {value}"


def performance(params, group="region", limit=100):
    return client.get(
        "/analytics/delivery-performance", **params, group_by=group, min_orders=1, limit=limit
    )


def show_overview(params):
    summary = client.get("/analytics/overview", **params)
    rate = summary["late_rate"]
    duration = summary["durations"]["fulfillment_days"]["mean"]
    with st.container(key="overview_spread"):
        lead, rates, operations = st.columns([1.45, 1, 1], gap="large")
        with lead, st.container(key="overview_spotlight"):
            st.metric("Historical orders", f"{summary['total_orders']:,}")
            st.caption(
                "The selected purchase cohort. A historical record of fulfillment, from checkout to the last mile."
            )
        with rates:
            st.metric("On-time delivery", f"{1 - rate:.1%}" if rate is not None else "Unavailable")
            st.metric("Late delivery", f"{rate:.1%}" if rate is not None else "Unavailable")
        with operations:
            st.metric(
                "Approval → carrier",
                f"{duration:.1f} days" if duration is not None else "Unavailable",
            )
            st.metric("Active sellers in cohort", f"{summary['active_sellers']:,}")
    st.caption(
        f"Rates use {summary['eligible_outcomes']:,} valid delivered outcomes; "
        f"{summary['excluded_outcomes']:,} missing, invalid or unresolved outcomes excluded. "
        "Late = actual timestamp > promised timestamp. Original mart calendar-day flags differ."
    )
    st.caption(
        "Duration means omit missing/invalid milestones. Lateness includes zero for on-time orders."
    )
    section(
        "A",
        "The shape of fulfillment",
        "Demand over time and the durations observed at each stage of the journey.",
    )
    stages = [
        {"stage": key.replace("_", " "), **value} for key, value in summary["durations"].items()
    ]
    left, right = st.columns([1.3, 1], gap="large")
    with left:
        chart(
            summary["monthly_volume"], "month", "orders", "01 / The rhythm of demand", kind="line"
        )
        st.caption(
            "Source: Olist purchase timestamps. Monthly counts respond to the historical cohort filters."
        )
    with right:
        chart(stages, "mean", "stage", "02 / Time along the journey", orientation="h")
        st.caption(
            "Mean duration in days. Stages have different valid-observation counts; some stages overlap."
        )
    section(
        "B",
        "Across the map",
        "Regional rates are descriptive comparisons, not evidence that location causes delays.",
    )
    regions = performance(params)["items"]
    left, right = st.columns(2, gap="large")
    with left:
        chart(
            regions,
            "group",
            "late_rate",
            "03 / Delivery pressure by state",
            labels={"group": "Customer state"},
        )
        st.caption("Late deliveries divided by eligible delivered orders in each customer state.")
    with right:
        chart(
            regions,
            "group",
            "total_orders",
            "04 / Where the orders go",
            labels={"group": "Customer state"},
        )
        st.caption(
            "Order volume shares the same cohort filters. Rate differences also reflect case mix and sample size."
        )
    workload = client.get("/orders", **params, limit=1)
    section("C", "The investigation desk", "Human workflow decisions for the selected cohort.")
    for col, (state, count) in zip(st.columns(5), workload["review_counts"].items(), strict=True):
        col.metric(state.capitalize(), f"{count:,}")
    st.caption("Workflow decisions are separate from observed delivery outcomes and model risk.")
    states = [row["group"] for row in regions]
    if states:
        region = st.selectbox("Investigate customer state", states)
        st.button(
            "Find orders in this region", on_click=navigate_orders, kwargs={"filter_region": region}
        )
    with st.expander("Definitions and denominators"):
        st.json(summary)


def remembered_select(label, options, key, *, index=0):
    """Keep logical choices when Streamlit removes widgets on another page."""
    value = st.session_state.get(key, options[index])
    st.session_state["widget_" + key] = value if value in options else options[index]

    def remember():
        st.session_state[key] = st.session_state["widget_" + key]

    selected = st.selectbox(label, options, key="widget_" + key, on_change=remember)
    st.session_state[key] = selected
    return selected


def navigate_orders(**filters):
    st.session_state.update(filters)
    st.session_state["navigation"] = "Orders & review queue"
    st.session_state["browse_page"] = 1


def order_details(identifier, prediction=None):
    detail = client.get("/orders/" + identifier)
    section(
        "C",
        "The order case file",
        "Purchase-time information and later historical evidence are kept distinct.",
    )
    st.subheader("Order " + identifier)
    st.caption(detail["interpretation"])
    facts(
        {
            key: value
            for key, value in detail["placement"].items()
            if key in ("purchased_at", "estimated_delivery_at", "customer_state")
        }
    )
    st.markdown("**Products & sellers · purchase-time attributes**")
    table(detail["products"], "products")
    with st.expander("Complete placement-time attributes"):
        st.json(detail["placement"])
    with st.expander("Subsequent historical outcomes · excluded from replay inputs"):
        st.json(detail["observed_after_purchase"])
    context = st.session_state.get("model_context")
    score_key = json.dumps([identifier, context])
    individual = st.session_state.setdefault("individual_scores", {})
    prediction = prediction or individual.get(score_key)
    if detail["replay_payload"]:
        if st.button("Score this historical order", key="score_detail_" + identifier):
            result = client.post(
                "/orders/replay", {"order_ids": [identifier], "review_capacity": 1}
            )
            prediction = result["predictions"][0]
            individual[score_key] = prediction
    else:
        st.warning(detail["replay_unavailable_reason"])
    if prediction:
        st.metric("Model-estimated delay probability", f"{prediction['delay_probability']:.1%}")
        st.caption(
            f"Model {prediction['model_version']} · threshold {prediction['threshold']:.3f} · "
            f"category {prediction['risk_category']}. A risk estimate is not a confirmed outcome."
        )
        st.write(prediction["rationale"])
        for warning in prediction["warnings"]:
            st.warning(warning)
    with st.expander("Related seller and logistics evidence"):
        seller_ids = sorted({row["seller_id"] for row in detail["products"]})
        seller = (
            st.selectbox("Related seller", seller_ids, key="related_" + identifier)
            if seller_ids
            else None
        )
        if seller and st.button("Open seller evidence", key="seller_evidence_" + identifier):
            st.session_state["seller_focus"] = seller
            st.session_state["next_navigation"] = "Seller intelligence"
            st.rerun()
        st.caption(
            "Seller insights and anomaly screens summarize historical associations; they are not "
            "prediction-time inputs or proof of a delivery incident."
        )
    state = detail["review"]
    drafts = st.session_state.setdefault("review_drafts", {})
    if st.button("Reload saved review (discard draft)", key="reload_" + identifier):
        drafts[identifier] = dict(state)
        for key in ("notes_" + identifier, "status_" + identifier):
            st.session_state.pop(key, None)
    draft = drafts.setdefault(identifier, dict(state))
    section(
        "D",
        "Record the next step",
        "Save a human review decision with the evidence that supports it.",
    )
    with st.form("review_" + identifier):
        status = st.selectbox(
            "Investigation status",
            STATUSES,
            index=STATUSES.index(draft["status"]),
            key="status_" + identifier,
        )
        notes = st.text_area(
            "Investigation notes · avoid personal or sensitive information",
            draft["notes"],
            max_chars=5000,
            key="notes_" + identifier,
        )
        st.caption(
            f"Editing revision {draft['revision']} · latest saved revision {state['revision']}"
        )
        if st.form_submit_button("Save review"):
            draft.update(status=status, notes=notes)
            try:
                saved = client.put(
                    f"/orders/{identifier}/review",
                    {"status": status, "notes": notes, "expected_revision": draft["revision"]},
                )
            except BackendError as exc:
                if exc.status_code != 409:
                    raise
                st.error(
                    "Another session changed this review. Your draft is retained. "
                    "Copy it if needed, then reload the saved review before editing again."
                )
            else:
                drafts.pop(identifier, None)
                st.session_state["review_flash"] = f"Review saved · revision {saved['revision']}."
                st.rerun()


def show_orders(params, options):
    st.caption(
        "Historical replay ranks only this candidate page (at most 100 orders), not the complete "
        "filtered cohort. Observed status/outcome filters are retrospective browsing context; "
        "they never enter checkout features. This is not independent model validation."
    )
    if message := st.session_state.pop("review_flash", None):
        st.success(message)
    if identifier := st.session_state.get("open_order_details"):
        if st.button("Return to order queue", key="return_from_anomaly_order"):
            st.session_state.pop("open_order_details", None)
            st.rerun()
        order_details(identifier)
        return
    section(
        "A",
        "Discover the cohort",
        "Use the sidebar to define the purchase cohort, then refine its discovery and investigation state.",
    )
    cols = st.columns(3)
    with cols[0]:
        status = remembered_select("Workflow filter", ["all"] + STATUSES, "browse_status")
    with cols[1]:
        order_status = remembered_select(
            "Historical order status", ["all"] + options["order_statuses"], "browse_order_status"
        )
    with cols[2]:
        outcome = remembered_select(
            "Observed delivery outcome", ["all", "late", "on_time", "unavailable"], "browse_outcome"
        )
    size = remembered_select("Candidates per page", [25, 50, 100], "browse_size", index=1)
    filters = {
        **params,
        "review_status": None if status == "all" else status,
        "order_status": None if order_status == "all" else order_status,
        "delivery_outcome": None if outcome == "all" else outcome,
    }
    discovery_key = json.dumps([filters, size], sort_keys=True)
    if st.session_state.get("discovery_key") != discovery_key:
        st.session_state["browse_page"] = 1
        st.session_state["discovery_key"] = discovery_key
    page = st.session_state.get("browse_page", 1)
    listing = client.get("/orders", **filters, limit=size, offset=(page - 1) * size)
    pages = max(1, (listing["total"] + size - 1) // size)
    if page > pages:
        st.session_state["browse_page"] = pages
        st.rerun()
    cols = st.columns(3)
    if cols[0].button("Previous page", disabled=page <= 1):
        st.session_state["browse_page"] = page - 1
        st.rerun()
    cols[1].caption(f"Page {page} of {pages} · {listing['total']:,} matching orders")
    if cols[2].button("Next page", disabled=page >= pages):
        st.session_state["browse_page"] = page + 1
        st.rerun()

    def jump_page():
        st.session_state["browse_page"] = st.session_state["page_jump"]

    st.session_state["page_jump"] = page
    st.number_input(
        "Go to page", min_value=1, max_value=pages, step=1, key="page_jump", on_change=jump_page
    )
    st.caption("Investigation counts in the discovery cohort before the workflow-status filter:")
    st.write(listing["review_counts"])
    table(listing["items"], "candidate_orders", export=True)
    section(
        "B",
        "Prioritize with evidence",
        "Score a candidate page for a quick look, or freeze a bounded cohort as a persistent job.",
    )
    with st.expander("Cohort Scoring — persistent jobs", expanded=False):
        cohort_order = cohort_panel(client, filters, listing["total"], STATUSES)
    if cohort_order:
        order_details(*cohort_order)
        return
    identifiers = [row["order_id"] for row in listing["items"]]
    if not identifiers:
        st.info("No matching orders. Adjust discovery filters or return to a broader cohort.")
    else:

        def remember_capacity():
            st.session_state["review_capacity"] = st.session_state["capacity_widget"]

        capacity = st.slider(
            "Review capacity within this page",
            0,
            len(identifiers),
            min(st.session_state.get("review_capacity", 10), len(identifiers)),
            key="capacity_widget",
            on_change=remember_capacity,
        )
        context = st.session_state["model_context"]
        cache_key = json.dumps([identifiers, context])
        cache = st.session_state.setdefault("scored_pages", {})
        if st.button("Score candidate page", type="primary"):
            if cache_key not in cache:
                with st.spinner(f"Scoring {len(identifiers)} candidates with the saved model…"):
                    scored = client.post(
                        "/orders/replay", {"order_ids": identifiers, "review_capacity": capacity}
                    )
                    if scored["warehouse_snapshot"] != context[0] or (
                        scored["model_version"] and scored["model_version"] != context[1]
                    ):
                        st.warning(
                            "Data/model changed during this request. Refresh before scoring again."
                        )
                        return
                    cache[cache_key] = scored
                    if len(cache) > 4:
                        cache.pop(next(iter(cache)))
            else:
                st.success("Reused this page's saved scores; no repeat inference.")
        queue = cache.get(cache_key)
        ranked = []
        if queue:
            st.subheader("Risk-ranked review queue")
            st.caption(
                f"Scored {queue['scored_count']} of {queue['candidate_count']} candidates · "
                f"{queue['scored_at_utc']} · model {queue['model_version'] or 'unavailable'}. "
                "Scope: this candidate page only. Unreconstructible orders are excluded from ranking."
            )
            states = client.get("/orders", order_ids=identifiers, limit=100)["items"]
            state_by_id = {row["order_id"]: row["review_status"] for row in states}
            ranked = sorted(queue["predictions"], key=lambda row: -row["delay_probability"])
            review_ids = {row["order_id"] for row in ranked[:capacity]}
            queue_status = remembered_select(
                "Scored queue workflow filter", ["all"] + STATUSES, "queue_status"
            )
            rows = [
                {
                    **row,
                    "within_review_capacity": row["order_id"] in review_ids,
                    "review_status": state_by_id.get(row["order_id"], "pending"),
                }
                for row in ranked
            ]
            if queue_status != "all":
                rows = [row for row in rows if row["review_status"] == queue_status]
            table(rows, "review_queue", export=True)
            if rows and st.button("Inspect highest-risk match"):
                st.session_state["inspect_order"] = rows[0]["order_id"]
                st.rerun()
            if queue["unavailable"]:
                table(queue["unavailable"], "unavailable", export=True)
        inspection_ids = [row["order_id"] for row in ranked] + [
            value for value in identifiers if value not in {row["order_id"] for row in ranked}
        ]
        selected = remembered_select("Inspect candidate order", inspection_ids, "inspect_order")
        predictions = {row["order_id"]: row for row in ranked}
        order_details(selected, predictions.get(selected))
    with st.expander("Find a historical order by identifier"):
        identifier = st.text_input("Order identifier")
        if identifier and identifier.strip() not in ([selected] if identifiers else []):
            order_details(identifier.strip())
    with st.expander("Score a checkout payload through the existing prediction API"):
        st.caption(
            "Use the checkout schema from Swagger. Outcomes/reviews are rejected by the backend."
        )
        payload = st.text_area("Checkout JSON", height=180)
        if st.button("Score checkout payload"):
            try:
                st.json(client.post("/orders/predict-delay", json.loads(payload)))
            except json.JSONDecodeError:
                st.error("Enter valid JSON using the documented checkout schema.")


def show_logistics(params):
    section(
        "A",
        "Trace the journey",
        "Compare the same historical cohort across regions, sellers, categories, or purchase months.",
    )
    group = st.selectbox("Compare by", ["region", "seller", "category", "month"])
    rows = performance(params, group, 100)["items"]
    chart(
        rows,
        "group",
        "late_rate",
        "01 / Historical late-delivery rate",
        kind="line" if group == "month" else "bar",
        labels={"group": group.capitalize()},
    )
    st.caption(
        "Each rate uses valid delivered outcomes. Group size and case mix vary; these observations do not establish causes."
    )
    chart(
        rows,
        "group",
        "durations.delivery_days.mean",
        "02 / Mean purchase-to-delivery duration (days)",
        labels={"group": group.capitalize()},
    )
    section(
        "B",
        "The bottleneck ledger",
        "Milestone durations and the longest observed median stage, with explicit missing-data counts.",
    )
    result = client.get("/analytics/bottlenecks", **params, group_by=group, min_orders=5)
    st.caption(result["interpretation"])
    table(result["items"], "bottlenecks", export=True)
    st.caption(
        "Tables show the first 100 groups sorted by late rate. Report exports include regional totals."
    )
    section(
        "C",
        "Regional signals",
        "A separate full-history anomaly snapshot; the operational cohort filters do not regenerate it.",
    )
    table(client.get("/mining/anomalies", kind="region")["items"], "regional_anomalies")


def show_seller(options):
    st.caption(
        "Seller intelligence and peer segments summarize full history; overview date filters do not apply."
    )
    identifier = remembered_select("Seller", options["seller_ids"], "seller_focus")
    st.button(
        "Find this seller’s orders", on_click=navigate_orders, kwargs={"filter_seller": identifier}
    )
    result = client.get(f"/sellers/{identifier}/insights")
    facts({"seller identifier": identifier, "evidence scope": "Full historical record"})
    if result["performance"]:
        profile = result["performance"]
        cols = st.columns(3)
        cols[0].metric("Historical orders", f"{profile['total_orders']:,}")
        cols[1].metric(
            "Late delivery rate",
            f"{profile['late_rate']:.1%}" if profile["late_rate"] is not None else "Unavailable",
        )
        fulfillment = profile["durations"]["fulfillment_days"]["median"]
        cols[2].metric(
            "Median approval → carrier",
            f"{fulfillment:.1f} days" if fulfillment is not None else "Unavailable",
        )
        section("A", "The seller record")
        table([result["performance"]], "seller_performance")
    for warning in result["warnings"]:
        st.warning(warning)
    if result["segment"]:
        segment = result["segment"]
        section(
            "B",
            "A measured peer group",
            "Segment descriptions quote historical features rather than assigning a quality label.",
        )
        st.subheader(segment["segment_name"])
        table([segment["features"]], "seller_features")
        peers = client.get("/sellers/segments", segment_id=segment["segment_id"], limit=100)
        st.caption(
            f"Peers in the same measured segment · first {len(peers['items'])} of {peers['total']}"
        )
        chart(
            peers["items"],
            "features.order_volume",
            "features.late_rate",
            "Similar sellers · volume versus historical late rate",
            kind="scatter",
            hover_name="seller_id",
        )
    section(
        "C",
        "Signals worth reviewing",
        "Historical screens and customer-review associations; shared-order milestones can involve several sellers.",
    )
    table(result["anomalies"], "seller_anomalies")
    if result["reviews"]:
        table([result["reviews"]], "seller_complaints")


def show_mining():
    section("A", "The research notebook")
    st.caption(
        "Discover historical associations, seller groups, and unusual logistics patterns. "
        "Mining snapshots use the full eligible history; sidebar date, seller, region, and category filters "
        "do not rebuild or filter them. These associations are not causal findings."
    )
    tab_rules, tab_segments, tab_anomalies = st.tabs(
        ["Frequent Pattern Mining", "Seller Clustering", "Anomaly Detection"]
    )
    with tab_rules:
        rules = client.get("/mining/association-rules", limit=1)
        saved = rules.get("mining_parameters", {})
        choice = st.selectbox(
            "Mining algorithm view",
            ["Apriori", "FP-Growth", "Compare Both"],
            key="mining_algorithm_view",
        )
        algorithm = {"Apriori": "apriori", "FP-Growth": "fp_growth"}.get(choice, "apriori")
        stats = rules.get("algorithms", {})
        if choice == "Compare Both":
            left, right, match = st.columns(3)
            left.metric(
                "Apriori",
                f"{stats.get('apriori', {}).get('seconds', 0):.3f} s",
            )
            left.caption(
                f"{stats.get('apriori', {}).get('frequent_itemsets', 0):,} frequent itemsets"
            )
            right.metric(
                "FP-Growth",
                f"{stats.get('fp_growth', {}).get('seconds', 0):.3f} s",
            )
            right.caption(
                f"{stats.get('fp_growth', {}).get('frequent_itemsets', 0):,} frequent itemsets"
            )
            match.metric("Verified parity", "Yes" if rules["algorithms_agree"] else "No")
            chart(
                [
                    {"algorithm": name.replace("_", "-"), "seconds": value["seconds"]}
                    for name, value in stats.items()
                ],
                "algorithm",
                "seconds",
                "Saved mining runtime · one historical run",
            )
            st.caption(
                "Apriori generates and prunes candidate itemsets. FP-Growth compresses transactions "
                "into an FP-tree and mines patterns without candidate generation. On the same baskets "
                "and support threshold, their itemsets and supports should match; timings are one saved "
                "measurement, not a performance guarantee."
            )
        else:
            selected = stats.get(algorithm, {})
            cols = st.columns(3)
            cols[0].metric("Selected algorithm", choice)
            cols[1].metric("Saved execution time", f"{selected.get('seconds', 0):.3f} s")
            cols[2].metric("Frequent itemsets", f"{selected.get('frequent_itemsets', 0):,}")
            if algorithm == "apriori":
                st.caption(
                    "Apriori builds candidate itemsets level by level and prunes candidates whose "
                    "subsets are not frequent. The shared saved results were verified against FP-Growth."
                )
            else:
                st.caption(
                    "FP-Growth compresses transactions into an FP-tree and mines conditional patterns. "
                    "The shared saved results were verified against Apriori."
                )
        if rules["algorithms_agree"]:
            st.success(
                f"Apriori and FP-Growth agree on the saved itemsets and supports across "
                f"{rules['transaction_count']:,} eligible transactions."
            )
        else:
            st.error(
                "The saved report records disagreement between Apriori and FP-Growth. Treat the mined "
                "results as unverified until the offline report is rebuilt and checked."
            )
        st.caption(
            f"Snapshot {rules.get('created_at_utc') or 'timestamp unavailable'} · saved minimum support "
            f"{saved.get('min_support', 0):.3g}, confidence {saved.get('min_confidence', 0):.3g}, "
            f"lift {saved.get('min_lift', 0):.3g}. Changing display filters never reruns mining."
        )

        st.markdown("#### Frequent itemsets")
        item_support = st.number_input(
            "Minimum displayed support · itemsets",
            min_value=0.0,
            max_value=1.0,
            value=float(saved.get("min_support", 0.01)),
            step=0.005,
            format="%.3f",
            key="mining_itemset_support",
        )
        item_sort = st.selectbox(
            "Sort itemsets by",
            ["Support", "Support count", "Itemset size", "Items"],
            key="mining_itemset_sort",
        )
        item_order = st.selectbox(
            "Itemset sort order", ["Descending", "Ascending"], key="mining_itemset_order"
        )
        if item_support < float(saved.get("min_support", 0)):
            st.warning(
                "This is below the snapshot's original support threshold. Lower-support itemsets were "
                "never saved, so this view cannot recover them; run the offline mining command to do so."
            )
        item_limit = st.selectbox(
            "Itemsets per page", [25, 50, 100], index=1, key="mining_itemset_limit"
        )
        item_params = {
            "algorithm": algorithm,
            "min_support": item_support,
            "limit": item_limit,
            "sort_by": {
                "Support": "support",
                "Support count": "support_count",
                "Itemset size": "size",
                "Items": "items",
            }[item_sort],
            "sort_order": "desc" if item_order == "Descending" else "asc",
        }
        itemsets = client.get(
            "/mining/itemsets",
            **item_params,
            offset=(st.session_state.get("mining_itemset_page", 1) - 1) * item_limit,
        )
        st.caption(
            f"{choice} context · {itemsets['total']:,} saved matches · page shows "
            f"{len(itemsets['items'])} rows. The rows are shared and verified, not reminted per algorithm."
        )
        itemset_rows = [
            {
                **row,
                "items_display": " · ".join(itemset_label(token) for token in row["items"]),
                "itemset_size": len(row["items"]),
            }
            for row in itemsets["items"]
        ]
        chart(
            itemset_rows[:25],
            "support",
            "items_display",
            "Frequent itemset support · current page",
            orientation="h",
        )
        item_pages = max(1, (itemsets["total"] + item_limit - 1) // item_limit)
        if st.session_state.get("mining_itemset_page", 1) > item_pages:
            st.session_state["mining_itemset_page"] = item_pages
        st.number_input(
            "Itemset page", min_value=1, max_value=item_pages, step=1, key="mining_itemset_page"
        )
        table(itemset_rows, "frequent_itemsets", export=True)

        st.markdown("#### Association rules for late delivery")
        rule_cols = st.columns(4)
        rule_support = rule_cols[0].number_input(
            "Minimum support · rules",
            min_value=0.0,
            max_value=1.0,
            value=float(saved.get("min_support", 0.01)),
            step=0.005,
            format="%.3f",
            key="mining_rule_support",
        )
        rule_confidence = rule_cols[1].number_input(
            "Minimum confidence",
            min_value=0.0,
            max_value=1.0,
            value=float(saved.get("min_confidence", 0.15)),
            step=0.05,
            format="%.3f",
            key="mining_rule_confidence",
        )
        rule_lift = rule_cols[2].number_input(
            "Minimum lift",
            min_value=0.0,
            max_value=20.0,
            value=float(saved.get("min_lift", 1.1)),
            step=0.1,
            format="%.2f",
            key="mining_rule_lift",
        )
        antecedent = rule_cols[3].text_input(
            "Antecedent attribute or value", key="mining_rule_antecedent"
        )
        rule_sort = st.selectbox(
            "Sort rules by",
            ["Highest lift", "Highest confidence", "Highest support"],
            key="mining_rule_sort",
        )
        for field, value in (
            ("support", rule_support),
            ("confidence", rule_confidence),
            ("lift", rule_lift),
        ):
            if value < float(saved.get("min_" + field, 0)):
                st.warning(
                    f"The requested minimum {field} is below the saved mining threshold. "
                    "Patterns excluded from the snapshot cannot be recovered here."
                )
        rule_limit = st.selectbox("Rules per page", [25, 50, 100], index=1, key="mining_rule_limit")
        rule_params = {
            "min_support": rule_support,
            "min_confidence": rule_confidence,
            "min_lift": rule_lift,
            "antecedent_contains": antecedent or None,
            "sort_by": {
                "Highest lift": "lift",
                "Highest confidence": "confidence",
                "Highest support": "support",
            }[rule_sort],
            "limit": rule_limit,
        }
        rule_page = st.session_state.get("mining_rule_page", 1)
        rule_rows = client.get(
            "/mining/association-rules", **rule_params, offset=(rule_page - 1) * rule_limit
        )
        st.caption(
            "Support is the fraction of all eligible transactions containing the full rule. Confidence "
            "is the fraction matching the antecedent that also match the consequent; for outcome=late, "
            "it is the historical late rate in that subgroup. Lift compares this association with the "
            "overall late prevalence. These are associations, not causes."
        )
        st.caption(f"{rule_rows['total']:,} saved rules match these display filters.")
        chart(
            [
                {"rule": " AND ".join(itemset_label(value) for value in row["antecedents"]), **row}
                for row in rule_rows["items"][:15]
            ],
            "lift",
            "rule",
            "Highest-lift matching rules",
            orientation="h",
        )
        rule_pages = max(1, (rule_rows["total"] + rule_limit - 1) // rule_limit)
        if rule_page > rule_pages:
            st.session_state["mining_rule_page"] = rule_pages
            st.rerun()
        st.number_input(
            "Rule page", min_value=1, max_value=rule_pages, step=1, key="mining_rule_page"
        )
        table(rule_rows["items"], "association_rules", export=True)
    with tab_segments:
        segments = client.get("/sellers/segments", limit=1)
        cols = st.columns(4)
        cols[0].metric("Seller segments", segments["selected_k"])
        cols[1].metric("Sellers included", f"{segments['total']:,}")
        cols[2].metric(
            "Low-volume sellers excluded", f"{segments['excluded_low_volume_sellers']:,}"
        )
        cols[3].metric(
            "Silhouette",
            f"{segments['silhouette']:.3f}",
        )
        cols[3].caption(f"Stability ARI {segments['mean_stability_ari']:.3f}")
        st.write(segments["method"])
        st.caption(
            segments["interpretation"]
            + " K-Medoids assigns sellers to the nearest observed medoid; "
            "a medoid is an actual seller near the center of its group. Silhouette summarizes separation "
            "and cohesion, while resample ARI summarizes agreement of cluster assignments across samples."
        )
        chart(segments["segments"], "name", "sellers", "Historical seller segment sizes")
        profile_rows = [
            {"segment": row["name"], "sellers": row["sellers"], **row["medians"]}
            for row in segments["segments"]
        ]
        table(profile_rows, "seller_segment_profiles", export=True)
        numeric_features = [
            key
            for key in segments.get("feature_names", [])
            if key
            in {
                "order_volume",
                "late_rate",
                "median_fulfillment_days",
                "mean_freight",
                "mean_distance_km",
                "mean_order_value",
                "category_diversity",
            }
        ]
        if numeric_features and profile_rows:
            feature = st.selectbox(
                "Compare cluster medians", numeric_features, key="segment_profile_feature"
            )
            chart(
                [{"segment": row["segment"], feature: row.get(feature)} for row in profile_rows],
                "segment",
                feature,
                f"Seller segments · median {feature.replace('_', ' ')}",
            )
        if segments["segments"]:
            segment_names = {row["name"]: row["segment_id"] for row in segments["segments"]}
            chosen_segment = st.selectbox(
                "Explore sellers in segment", list(segment_names), key="seller_segment_choice"
            )
            seller_limit = st.selectbox(
                "Sellers per page", [25, 50, 100], key="segment_seller_limit"
            )
            selected_id = segment_names[chosen_segment]
            seller_page_num = st.session_state.get("segment_seller_page", 1)
            assignments = client.get(
                "/sellers/segments",
                segment_id=selected_id,
                limit=seller_limit,
                offset=(seller_page_num - 1) * seller_limit,
            )
            seller_pages = max(1, (assignments["total"] + seller_limit - 1) // seller_limit)
            if seller_page_num > seller_pages:
                st.session_state["segment_seller_page"] = seller_pages
                st.rerun()
            st.caption(
                f"Segment {selected_id} · showing {len(assignments['items'])} of "
                f"{assignments['total']:,} sellers. Compare these values with the segment medians above."
            )
            st.number_input(
                "Seller page",
                min_value=1,
                max_value=seller_pages,
                step=1,
                key="segment_seller_page",
            )
            table(assignments["items"], "segment_sellers", export=True)
            if assignments["items"]:
                seller_choices = {row["seller_id"]: row for row in assignments["items"]}
                seller_id = st.selectbox(
                    "Inspect seller on this page", list(seller_choices), key="segment_seller_choice"
                )
                seller_features = seller_choices[seller_id]["features"]
                profile = next(
                    row for row in segments["segments"] if row["segment_id"] == selected_id
                )
                comparison = [
                    {
                        "feature": feature.replace("_", " "),
                        "seller": seller_features.get(feature),
                        "segment median": profile["medians"].get(feature),
                    }
                    for feature in numeric_features
                    if feature in seller_features
                ]
                table(comparison, "seller_vs_segment_median")
                if st.button("Open in Seller Intelligence", key="open_segment_seller"):
                    st.session_state["seller_focus"] = seller_id
                    st.session_state["next_navigation"] = "Seller intelligence"
                    st.rerun()
    with tab_anomalies:
        labels = {
            "Unusual orders": "order",
            "Unusual sellers": "seller",
            "Unusual regions": "region",
            "Slow fulfillment sellers": "seller_fulfillment",
        }
        label = st.selectbox("Anomaly type", list(labels), key="mining_anomaly_type")
        kind = labels[label]
        result = client.get(
            "/mining/anomalies",
            kind=kind,
            limit=50,
            offset=(st.session_state.get("mining_anomaly_page", 1) - 1) * 50,
        )
        total = result["counts"].get(kind, 0)
        st.subheader(label)
        st.metric("Matching historical flags", f"{total:,}")
        if kind == "order":
            st.caption(
                f"Isolation Forest order-characteristic score; saved threshold {result['order_threshold']:.4f}. "
                "Higher scores are more unusual within this historical reference distribution."
            )
        elif kind in {"seller", "region"}:
            st.caption(
                "Wilson interval screen: the group's 95% lower bound exceeds the global 95% late-rate "
                "upper bound. The score is a lower bound, not a shared anomaly scale."
            )
        else:
            st.caption(
                "Robust duration screen: median approval-to-carrier time exceeds the historical median "
                "by three scaled median absolute deviations."
            )
        st.caption(result["interpretation"])
        rows = result["items"]
        if kind == "order":
            rows = [
                {
                    "order_id": row["entity_id"],
                    "score": row["score"],
                    "threshold": row["threshold"],
                    "customer_region": row.get("region"),
                    "reasons": row["reasons"],
                    "observed_features": row.get("observed_features"),
                }
                for row in rows
            ]
        elif kind in {"seller", "region"}:
            rows = [
                {
                    "entity_id": row["entity_id"],
                    "late_rate": row.get("late_rate"),
                    "eligible_outcomes": row.get("eligible_outcomes"),
                    "late_orders": row.get("late_orders"),
                    "screen_score": row["score"],
                    "screen_threshold": row["threshold"],
                    "wilson_interval": row.get("wilson_interval"),
                    "reasons": row["reasons"],
                }
                for row in rows
            ]
        table(rows, "anomalies_" + kind, export=True)
        pages = max(1, (total + 49) // 50)
        if st.session_state.get("mining_anomaly_page", 1) > pages:
            st.session_state["mining_anomaly_page"] = pages
            st.rerun()
        st.number_input(
            "Anomaly page", min_value=1, max_value=pages, step=1, key="mining_anomaly_page"
        )
        if result["items"]:
            if kind == "order":
                identifiers = [row["entity_id"] for row in result["items"]]
                order_id = st.selectbox(
                    "Investigate unusual order", identifiers, key="anomaly_order_id"
                )
                if st.button("Open order investigation", key="open_anomaly_order"):
                    st.session_state["open_order_details"] = order_id
                    st.session_state["next_navigation"] = "Orders & review queue"
                    st.rerun()
            elif kind in {"seller", "seller_fulfillment"}:
                sellers = [row["entity_id"] for row in result["items"]]
                seller_id = st.selectbox("Inspect unusual seller", sellers, key="anomaly_seller_id")
                if st.button("Open seller intelligence", key="open_anomaly_seller"):
                    st.session_state["seller_focus"] = seller_id
                    st.session_state["next_navigation"] = "Seller intelligence"
                    st.rerun()
            elif kind == "region":
                regions = [row["entity_id"] for row in result["items"]]
                region = st.selectbox(
                    "Inspect unusual customer region", regions, key="anomaly_region_id"
                )
                if st.button("Open regional logistics", key="open_anomaly_region"):
                    st.session_state["filter_region"] = region
                    st.session_state["next_navigation"] = "Logistics"
                    st.rerun()


def show_reviews(params):
    st.caption(
        "Saved theme and sentiment summaries cover full history. Excerpt/score filters use seller, "
        "region and category below; date filters do not apply. Reviews never enter replay risk inputs."
    )
    group = st.selectbox("Complaint groups", ["category", "seller", "region"])
    result = client.get("/reviews/insights", group_by=group, min_text_reviews=5)
    summary = result["global_summary"]
    evidence = client.get(
        "/reviews/evidence",
        **{k: v for k, v in params.items() if k in ("seller_id", "region", "product_category")},
    )
    st.caption(result["interpretation"])
    cols = st.columns(3)
    cols[0].metric("Reviews with text", f"{summary['reviews_with_text']:,}")
    cols[1].metric("Lexical complaint matches", f"{summary['complaint_reviews']:,}")
    cols[2].metric("Selected evidence records", f"{evidence['review_records']:,}")
    section(
        "A",
        "Signals in the language",
        "Lexical themes overlap. A review may match more than one topic.",
    )
    left, right = st.columns([1.3, 1], gap="large")
    with left:
        chart(
            [
                {"theme": key.replace("_", " "), "reviews": value}
                for key, value in summary["theme_counts"].items()
            ],
            "reviews",
            "theme",
            "01 / What the text mentions",
            orientation="h",
        )
    with right:
        chart(
            [{"score": key, "records": value} for key, value in evidence["score_counts"].items()],
            "score",
            "records",
            "02 / The review-score distribution",
        )
    st.caption(
        "Theme totals describe the saved full-history corpus. The score distribution uses the selected evidence cohort."
    )
    section(
        "B",
        "The complaint ledger",
        "Grouped historical observations for seller, category, or region.",
    )
    table(result["items"], "complaint_groups", export=True)
    with st.expander("Portuguese theme vocabulary"):
        table(
            [
                {"theme": theme, "keywords": words}
                for theme, words in summary["theme_keywords"].items()
            ],
            "theme_keywords",
        )
    section(
        "C",
        "Satisfaction, with context",
        "The saved Portuguese TF-IDF baseline learns noisy review-star labels.",
    )
    sentiment = summary["sentiment"]
    facts(
        {
            "model": sentiment.get("model") or sentiment["status"],
            "label source": sentiment.get("label_source") or "Insufficient labeled text",
        }
    )
    if sentiment.get("accuracy") is not None:
        cols = st.columns(3)
        cols[0].metric("Later-period accuracy", f"{sentiment['accuracy']:.1%}")
        cols[1].metric("Majority baseline", f"{sentiment['majority_baseline_accuracy']:.1%}")
        cols[2].metric("Evaluation reviews", f"{sentiment['test_count']:,}")
    st.warning(
        "Star-derived sentiment measures noisy general satisfaction. Its accuracy does not validate "
        "logistics complaint detection; theme rules have no measured recall/precision."
    )
    with st.expander("Sentiment method and full evaluation"):
        st.json(sentiment)
    section(
        "D",
        "From the review archive",
        "Deterministic lexical examples, conservatively redacted; not a random customer sample.",
    )
    st.caption(evidence["redaction"])
    for example in evidence["examples"][:3]:
        review_quote(example["excerpt"], example["review_score"], example["themes"])
    with st.expander("All returned redacted examples"):
        table(evidence["examples"], "review_excerpts")


def show_model():
    info = client.get("/models/info")
    metrics = client.get("/models/metrics")
    facts(
        {
            "active saved model": info["selected_model"],
            "model version": info["model_version"],
            "decision threshold": f"{info['threshold']:.4f}",
        }
    )
    st.warning(
        "Read-only evaluation. Historical test cohorts have already been inspected; they are not "
        "new independent evidence. No training, calibration or promotion controls are provided."
    )
    selected = metrics["comparison"][info["selected_model"]]["test"]
    section(
        "A",
        "The historical scorecard",
        "Saved, previously inspected test evidence. These metrics are not an estimate of current production performance.",
    )
    for keys in (
        ("precision", "recall", "f1"),
        ("roc_auc", "pr_auc_average_precision", "brier_score"),
    ):
        for col, key in zip(st.columns(3), keys, strict=True):
            col.metric(
                key.replace("pr_auc_average_precision", "Average precision")
                .replace("_", " ")
                .capitalize(),
                f"{selected[key]:.3f}",
            )
    rows = []
    for name, candidate in metrics["comparison"].items():
        for split in ("validation", "test"):
            value = candidate[split]
            rows.append(
                {
                    "model": name,
                    "cohort": split,
                    **{
                        key: value[key]
                        for key in (
                            "roc_auc",
                            "pr_auc_average_precision",
                            "precision",
                            "recall",
                            "f1",
                            "brier_score",
                            "precision_at_top_10_percent",
                        )
                    },
                }
            )
    section(
        "B",
        "Models in comparison",
        "Candidate selection used validation data. Later test rankings do not override that selection rule.",
    )
    table(rows, "saved_model_metrics", export=True)
    section(
        "C",
        "The calibration question",
        "Probability error and ranking are different properties of a risk model.",
    )
    chart(
        selected["calibration"],
        "predicted",
        "observed",
        "01 / Saved test reliability",
        kind="scatter",
    )
    st.caption(
        "Each point compares a bin's mean prediction with its observed late rate. The diagonal is perfect calibration."
    )
    if selected.get("review_budgets"):
        table(
            [
                {"review_budget": name, **value}
                for name, value in selected["review_budgets"].items()
            ],
            "review_budget_evidence",
        )
    with st.expander("Threshold, probability baselines, and limitations"):
        st.json(
            {
                "threshold": info["threshold"],
                "baselines": metrics["baselines"],
                "limitations": info["limitations"],
                "review_budgets": selected.get("review_budgets", {}),
            }
        )
    section(
        "D",
        "Across time",
        "Preserved temporal validation and calibration research; all model controls remain offline.",
    )
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
    st.caption(
        "Operational tables use the selected cohort. Mining findings retain their saved full-history scope."
    )
    report = client.get("/reports/operations", **params)
    section(
        "A",
        "The operations issue",
        "A consolidated narrative and companion data tables for the selected operational cohort.",
    )
    finding(
        "Available in this edition",
        f"{report['overview']['total_orders']:,} historical orders, with regional, seller, bottleneck, and saved association evidence.",
    )
    st.download_button(
        "Download consolidated Markdown report",
        report["markdown"],
        file_name="fulfilliq-operations.md",
        mime="text/markdown",
    )
    with st.expander("Preview consolidated report"):
        st.markdown(report["markdown"])
    for name in ("regions", "sellers", "bottlenecks", "rules"):
        with st.expander("Export " + name):
            table(report[name], "report_" + name, export=True)
    section(
        "B",
        "The R research supplement",
        "An independent Apriori comparison on identical transactions, with four reproducible statistical figures.",
    )
    result = client.get("/reports/r")
    if not result["available"]:
        st.info(result["message"])
    else:
        summary = result["summary"]
        cols = st.columns(2)
        cols[0].metric("Shared Python/R transactions", f"{summary['transaction_count']:,}")
        cols[1].metric("Matching late-delivery rules", summary["comparison"]["rules_compared"])
        st.caption(
            "Support, confidence and lift agree within 1e-8. Plots describe all valid "
            "historical deliveries; associations do not demonstrate causes."
        )
        with st.expander("R execution and reproducibility details"):
            st.json(summary)
        plots = [filename for filename in result["files"] if filename.endswith(".png")]
        for position, filename in enumerate(plots):
            with st.expander(
                filename.replace(".png", "").replace("-", " ").title(), expanded=position == 0
            ):
                st.image(
                    client.url + "/api/v1/reports/r/files/" + filename,
                    caption=filename,
                    width="stretch",
                )
        section("C", "Source files & reproducibility")
        for filename in result["files"]:
            url = client.url + "/api/v1/reports/r/files/" + filename
            if not filename.endswith(".png"):
                st.link_button("Open " + filename, url)


def main():
    apply_theme()
    try:
        options = client.get("/console/options")
        with st.sidebar:
            st.html(
                '<div class="editorial-brand">FULFILL<span>/</span>IQ</div>'
                '<p class="editorial-tagline">An intelligent logistics publication &amp; operations platform.</p>'
            )
            st.caption("CONTENTS / EIGHT PERSPECTIVES")
        if next_page := st.session_state.pop("next_navigation", None):
            st.session_state["navigation"] = next_page
        page = st.sidebar.radio(
            "Navigate",
            NAVIGATION,
            key="navigation",
            label_visibility="collapsed",
            format_func=lambda value: f"{PAGES[value][0]}  {value}",
        )
        st.session_state["model_context"] = [
            options["warehouse_snapshot"],
            options["model_version"],
        ]
        st.sidebar.caption(
            f"Olist history: {options['first_purchase']} → {options['last_purchase']}"
        )
        st.sidebar.divider()
        st.sidebar.markdown("**THE HISTORICAL COHORT**")
        st.sidebar.caption(
            "These filters shape operational views. Research snapshots retain their own stated scope."
        )
        start = st.sidebar.date_input(
            "Purchase from", date.fromisoformat(options["first_purchase"]), key="filter_start"
        )
        end = st.sidebar.date_input(
            "Purchase through", date.fromisoformat(options["last_purchase"]), key="filter_end"
        )
        region = st.sidebar.selectbox(
            "Customer state", ["All"] + options["regions"], key="filter_region"
        )
        seller = st.sidebar.selectbox(
            "Seller filter", ["All"] + options["seller_ids"], key="filter_seller"
        )
        category = st.sidebar.selectbox(
            "Product category", ["All"] + options["categories"], key="filter_category"
        )
        params = {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "region": None if region == "All" else region,
            "seller_id": None if seller == "All" else seller,
            "product_category": None if category == "All" else category,
        }
        if end < start:
            st.error(
                "Purchase through must be on or after Purchase from. Your other filters are retained."
            )
            return
        st.sidebar.caption(
            "Local demonstration. Human decisions persist separately from historical orders."
        )
        masthead(options["first_purchase"], options["last_purchase"])
        page_header(page)
        with st.spinner("Loading historical evidence…"):
            if page == "Overview":
                show_overview(params)
            elif page == "Orders & review queue":
                show_orders(params, options)
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
        folio(page)
    except BackendError as exc:
        st.error(str(exc))
        st.info(
            "Verify backend health and prepare missing artifacts explicitly. Startup never trains models."
        )


main()
