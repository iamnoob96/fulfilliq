"""One checkout-safe replay path for quick API scoring and persistent workers."""

from fulfilliq.modeling.contracts import OrderRequest
from fulfilliq.modeling.inference import RiskService
from fulfilliq.operations.orders import OrderNotFound, OrderService


def score_orders(orders: OrderService, risk: RiskService, identifiers: list[str]):
    requests, unavailable = [], []
    for identifier in identifiers:
        try:
            order = orders.detail(identifier)
            if order["replay_payload"] is not None:
                requests.append(OrderRequest.model_validate(order["replay_payload"]))
            else:
                unavailable.append({"order_id": identifier, "reason": order["replay_unavailable_reason"]})
        except OrderNotFound:
            unavailable.append({"order_id": identifier, "reason": "Order not found"})
    return risk.predict(requests) if requests else [], unavailable
