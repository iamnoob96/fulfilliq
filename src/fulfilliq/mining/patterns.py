"""Both algorithms mine exactly the same discretized, eligible order transactions."""

from time import perf_counter

import pandas as pd
from mlxtend.frequent_patterns import apriori, association_rules, fpgrowth
from mlxtend.preprocessing import TransactionEncoder

from fulfilliq.features.orders import TARGET_DEFINITION

BINNING = {
    "distance_km": ([0, 250, 750, 1500, float("inf")], ["local", "near", "far", "very_far"]),
    "items_value": (
        [0, 50, 150, 500, float("inf")],
        ["under_50", "50_to_150", "150_to_500", "over_500"],
    ),
    "freight_value": (
        [0, 10, 30, 60, float("inf")],
        ["under_10", "10_to_30", "30_to_60", "over_60"],
    ),
    "total_weight_g": (
        [0, 500, 2000, 10000, float("inf")],
        ["light", "medium", "heavy", "very_heavy"],
    ),
    "seller_history_late_rate": (
        [0, 0.05, 0.15, 1.00001],
        ["under_5_percent", "5_to_15_percent", "over_15_percent"],
    ),
}


def transactions(frame: pd.DataFrame) -> list[list[str]]:
    eligible = frame.loc[frame.target_is_late.notna()].copy()
    fields = {
        "customer_state": eligible.customer_state.fillna("unknown"),
        "seller_state": eligible.primary_seller_state.fillna("unknown"),
        "category": eligible.primary_category.fillna("unknown"),
    }
    for column, (edges, labels) in BINNING.items():
        # Fixed domain bins: no fitted quantiles or duplicated continuous/exact-value tokens.
        fields[column] = (
            pd.cut(eligible[column], bins=edges, labels=labels, right=False, include_lowest=True)
            .astype(object)
            .fillna("unknown")
        )
    fields["outcome"] = eligible.target_is_late.map({True: "late", False: "on_time"})
    tokens = pd.DataFrame(fields, index=eligible.index)
    return [[f"{column}={value}" for column, value in row.items()] for _, row in tokens.iterrows()]


def mine_patterns(
    frame: pd.DataFrame,
    *,
    min_support: float = 0.01,
    min_confidence: float = 0.15,
    min_lift: float = 1.1,
    max_length: int = 3,
) -> dict:
    if not 0 < min_support <= 1 or not 0 <= min_confidence <= 1 or min_lift <= 0:
        raise ValueError("Support/confidence must be probabilities and lift must be positive")
    if not 2 <= max_length <= 4:
        raise ValueError("max_length must be between 2 and 4 to bound candidate growth")
    baskets = transactions(frame)
    if not baskets:
        raise ValueError("Association mining requires eligible outcome transactions")
    encoder = TransactionEncoder()
    encoded = pd.DataFrame(
        encoder.fit(baskets).transform(baskets), columns=encoder.columns_, dtype=bool
    )
    results, itemsets = {}, {}
    for name, algorithm in (("apriori", apriori), ("fp_growth", fpgrowth)):
        started = perf_counter()
        options = {"low_memory": True} if name == "apriori" else {}
        frequent = algorithm(
            encoded, min_support=min_support, use_colnames=True, max_len=max_length, **options
        )
        results[name] = {"seconds": perf_counter() - started, "frequent_itemsets": len(frequent)}
        itemsets[name] = frequent
    comparison = {
        name: {tuple(sorted(row.itemsets)): float(row.support) for row in value.itertuples()}
        for name, value in itemsets.items()
    }
    same = comparison["apriori"].keys() == comparison["fp_growth"].keys() and all(
        abs(value - comparison["fp_growth"][key]) < 1e-10
        for key, value in comparison["apriori"].items()
    )
    if not same:
        raise ValueError("Apriori and FP-Growth disagree on frequent itemsets")
    rules = []
    if not itemsets["fp_growth"].empty:
        candidates = association_rules(
            itemsets["fp_growth"],
            metric="confidence",
            min_threshold=min_confidence,
            num_itemsets=len(baskets),
            return_metrics=["support", "confidence", "lift", "leverage"],
        )
        for row in candidates.itertuples():
            if row.consequents != frozenset({"outcome=late"}):
                continue
            if (
                any(token.startswith("outcome=") for token in row.antecedents)
                or row.lift < min_lift
            ):
                continue
            rules.append(
                {
                    "antecedents": sorted(row.antecedents),
                    "consequents": ["outcome=late"],
                    "support": float(row.support),
                    "confidence": float(row.confidence),
                    "lift": float(row.lift),
                    "leverage": float(row.leverage),
                    "support_count": round(row.support * len(baskets)),
                }
            )
    rules.sort(key=lambda row: (-row["lift"], -row["support"], row["antecedents"]))
    return {
        "target_definition": TARGET_DEFINITION,
        "transaction_count": len(baskets),
        "parameters": {
            "min_support": min_support,
            "min_confidence": min_confidence,
            "min_lift": min_lift,
            "max_length": max_length,
        },
        "binning": {
            name: {
                "edges": [str(v) for v in edges],
                "labels": labels,
                "interval": "left closed, right open; missing is unknown",
            }
            for name, (edges, labels) in BINNING.items()
        },
        "algorithms": results,
        "algorithms_agree": same,
        "itemsets": sorted(
            [{"items": sorted(row.itemsets), "support": float(row.support),
              "support_count": round(row.support * len(baskets))}
             for row in itemsets["apriori"].itertuples()],
            key=lambda row: (-row["support"], row["items"]),
        ),
        "rules": rules,
        "interpretation": "Exploratory full-history associations, not causal findings or "
        "independent held-out confirmation. One category/state summary per "
        "order avoids redundant tokens; confidence is the subgroup late rate.",
    }
