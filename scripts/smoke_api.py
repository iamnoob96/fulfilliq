"""Read-only live API verification with an explicitly synthetic checkout payload."""

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def smoke(base_url: str) -> dict:
    def request(path, payload=None, *, expected=200):
        body = json.dumps(payload).encode() if payload is not None else None
        req = Request(
            base_url.rstrip("/") + path,
            data=body,
            headers={"Content-Type": "application/json"} if body else {},
        )
        try:
            response = urlopen(req, timeout=30)
        except HTTPError as exc:
            response = exc
        with response:
            data = response.read()
            assert response.status == expected, (path, response.status, data[:300])
        return json.loads(data) if data.startswith(b"{") else data.decode()

    paths = [
        "/health",
        "/docs",
        "/openapi.json",
        "/api/v1/analytics/overview",
        "/api/v1/analytics/bottlenecks",
        "/api/v1/analytics/delivery-performance",
        "/api/v1/mining/association-rules",
        "/api/v1/mining/anomalies",
        "/api/v1/sellers/segments",
        "/api/v1/reviews/insights",
        "/api/v1/models/metrics",
        "/api/v1/models/info",
    ]
    results = {path: request(path) for path in paths}
    seller = results["/api/v1/sellers/segments"]["items"][0]["seller_id"]
    request(f"/api/v1/sellers/{seller}/insights")
    payload = json.loads((Path(__file__).resolve().parents[1] / "examples/order.json").read_text())
    first = request("/api/v1/orders/predict-delay", payload)
    assert 0 <= first["delay_probability"] <= 1
    assert request("/api/v1/orders/predict-delay", payload) == first
    batch = request("/api/v1/orders/predict-batch", {"orders": [payload]})
    assert batch["predictions"][0] == first
    second = {**payload, "order_id": payload["order_id"] + "-tie"}
    capacity = request(
        "/api/v1/orders/predict-batch",
        {
            "orders": [payload, second],
            "review_capacity": 1,
        },
    )
    assert capacity["review_order_ids"] == [payload["order_id"]]
    assert capacity["predictions"][0] == first
    request(
        "/api/v1/orders/predict-batch", {"orders": [payload], "review_capacity": 2}, expected=422
    )
    request("/api/v1/orders/predict-delay", {**payload, "delivered_at": "2018-07-10"}, expected=422)
    request("/api/v1/analytics/overview?start_date=2018-07-10&end_date=2018-07-01", expected=422)
    request("/api/v1/sellers/unknown-seller/insights", expected=404)
    return {
        "get_endpoints_passed": len(paths) + 1,
        "prediction_repeatability": "passed",
        "single_batch_parity": "passed",
        "capacity_review_queue": "passed",
        "invalid_input_422": "passed",
        "unknown_seller_404": "passed",
        "model_version": first["model_version"],
        "example_is_synthetic": True,
        "example_probability": first["delay_probability"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = smoke(args.base_url)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
