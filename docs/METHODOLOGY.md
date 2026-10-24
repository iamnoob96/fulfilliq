# Experimental methodology

## Outcome definitions and missing data

The completed prediction engine follows the requested exact target:
`actual_delivery_timestamp > estimated_delivery_timestamp`. Olist promises are usually
recorded at midnight; a delivery later on that calendar day is positive under this
definition. The legacy mart and `stats` retain their calendar-day target, so their late
counts intentionally differ. Neither label is silently substituted for the other.
Canceled, undelivered, missing-time and temporally incoherent orders are retained for
reporting but do not receive a supervised delay label.

## Purchase-time feature contract

Only explicit fields in `features/orders.py:FEATURES` enter the estimator. Inputs cover
purchase calendar/time, promise lead time, customer/seller states, primary product category,
distinct category/state/seller counts, per-item price/freight, product weight/volume,
item-weighted geographic distance and backward-looking historical performance.
The primary category/state is the lexicographically first known value; it is a deterministic
summary, not an inferred dominant seller/category. Each quantity is one item in the request.
Unknown prices/weights propagate through complete sums. Unknown coordinates are excluded
from mean distances; all-missing distances remain unknown. Identifiers are lookup keys,
not memorization features. Review text/scores, current status, actual milestones and outcomes
are excluded from the feature allowlist.

Each seller history contains one contribution per distinct order/seller pair. Multiple
sellers' counts are pooled, so a shared historic order can contribute once to each seller;
this represents seller/order observations, not unique historical orders. Regional history
uses one observation per order. No review or future delivery is consulted by these features.

Olist lacks an event audit log. A delivered outcome becomes observable at its recorded
delivery time plus a configurable reporting lag (default one day). Every history query uses
`available_at < purchase_timestamp` and a trailing 180-day window. Simultaneous outcomes
are excluded. Cold-start counts are zero and rates/durations are missing. No global
future-informed prior is substituted. The API uses the same indexed prefix-sum histories
and exactly the same numeric/categorical transformations as offline training.

The original database contains a static snapshot of seller/product attributes and promised
dates; it cannot prove those attributes never changed after checkout. The offline simulation
assumes their recorded values were available when the order was placed. Coordinates are
approximate ZIP centroids, not routes, customer addresses or measured shipping distances.
