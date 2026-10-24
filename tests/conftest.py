"""Small, explicitly synthetic fixtures; never used for project performance claims."""

import csv
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fulfilliq.db.schema import SOURCES
from fulfilliq.features.orders import NUMERIC_FEATURES


def write_source(raw_dir: Path, table: str, rows: list[dict]) -> None:
    spec = next(spec for spec in SOURCES if spec.table.name == table)
    with (raw_dir / spec.filename).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=spec.columns)
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in spec.columns} for row in rows)


@pytest.fixture
def raw_dir(tmp_path: Path) -> Path:
    raw = tmp_path / "raw"
    raw.mkdir()
    customers = [
        dict(
            customer_id=f"c{i}",
            customer_unique_id="returning-customer",
            customer_zip_code_prefix="00001",
            customer_city="São Paulo",
            customer_state="SP",
        )
        for i in range(1, 7)
    ]
    write_source(raw, "customers", customers)
    write_source(
        raw,
        "sellers",
        [
            dict(
                seller_id="s1",
                seller_zip_code_prefix="00001",
                seller_city="São Paulo",
                seller_state="SP",
            ),
            dict(
                seller_id="s2",
                seller_zip_code_prefix="99999",
                seller_city="Manaus",
                seller_state="AM",
            ),
        ],
    )
    write_source(
        raw,
        "products",
        [
            dict(
                product_id="p1",
                product_category_name="livros",
                product_weight_g="100",
                product_length_cm="10",
                product_height_cm="2",
                product_width_cm="10",
            ),
            dict(product_id="p2", product_category_name="sem_traducao", product_weight_g="200"),
            dict(product_id="p3"),
        ],
    )
    write_source(
        raw,
        "category_translation",
        [
            dict(product_category_name="livros", product_category_name_english="books"),
        ],
    )
    orders = [
        dict(
            order_id="o1",
            customer_id="c1",
            order_status="delivered",
            order_purchase_timestamp="2018-01-01 12:00:00",
            order_approved_at="2018-01-01 13:00:00",
            order_delivered_carrier_date="2018-01-02 12:00:00",
            order_delivered_customer_date="2018-01-06 14:00:00",
            order_estimated_delivery_date="2018-01-05 00:00:00",
        ),
        dict(
            order_id="o2",
            customer_id="c2",
            order_status="delivered",
            order_purchase_timestamp="2018-01-02 12:00:00",
            order_approved_at="not-a-date",
            order_delivered_customer_date="2018-01-05 23:59:59",
            order_estimated_delivery_date="2018-01-05 00:00:00",
        ),
        dict(
            order_id="o3",
            customer_id="c3",
            order_status="canceled",
            order_purchase_timestamp="2018-01-03 12:00:00",
            order_estimated_delivery_date="2018-01-08 00:00:00",
        ),
        dict(
            order_id="o4",
            customer_id="c4",
            order_status="delivered",
            order_purchase_timestamp="2018-01-03 12:00:00",
            order_estimated_delivery_date="2018-01-08 00:00:00",
        ),
        dict(
            order_id="o5",
            customer_id="c5",
            order_status="shipped",
            order_purchase_timestamp="2018-01-04 12:00:00",
            order_delivered_customer_date="2018-01-05 12:00:00",
            order_estimated_delivery_date="2018-01-04 00:00:00",
        ),
        dict(
            order_id="o6",
            customer_id="c6",
            order_status="delivered",
            order_purchase_timestamp="2018-01-05 12:00:00",
            order_delivered_customer_date="2018-01-04 12:00:00",
            order_estimated_delivery_date="2018-01-08 00:00:00",
        ),
    ]
    write_source(raw, "orders", orders)
    items = [
        dict(
            order_id="o1",
            order_item_id="1",
            product_id="p1",
            seller_id="s1",
            price="100",
            freight_value="10",
        ),
        dict(
            order_id="o1",
            order_item_id="2",
            product_id="p2",
            seller_id="s2",
            price="50",
            freight_value="5",
        ),
        dict(
            order_id="o2",
            order_item_id="1",
            product_id="p1",
            seller_id="s1",
            price="20",
            freight_value="10",
        ),
        dict(
            order_id="o4",
            order_item_id="1",
            product_id="p3",
            seller_id="s1",
            price="-1",
            freight_value="10",
        ),
    ]
    write_source(raw, "order_items", items + [items[0]])
    write_source(
        raw,
        "order_payments",
        [
            dict(
                order_id="o1",
                payment_sequential="1",
                payment_type="credit_card",
                payment_installments="2",
                payment_value="100",
            ),
            dict(
                order_id="o1",
                payment_sequential="2",
                payment_type="voucher",
                payment_installments="0",
                payment_value="65",
            ),
            dict(
                order_id="o2",
                payment_sequential="1",
                payment_type="credit_card",
                payment_installments="1",
                payment_value="30",
            ),
            dict(
                order_id="o4",
                payment_sequential="1",
                payment_type="credit_card",
                payment_installments="1",
                payment_value="not-a-number",
            ),
        ],
    )
    reviews = [
        dict(
            review_id="r1",
            order_id="o1",
            review_score="1",
            review_comment_message="Entrega atrasada, não chegou no prazo!",
        ),
        dict(review_id="r2", order_id="o1", review_score="2", review_comment_message="NA"),
        dict(review_id="r1", order_id="o2", review_score="5", review_comment_message="Ótimo!"),
    ]
    write_source(raw, "order_reviews", reviews + [reviews[0]])
    geo = [
        dict(
            geolocation_zip_code_prefix="00001",
            geolocation_lat="-23",
            geolocation_lng="-45",
            geolocation_city="São Paulo",
            geolocation_state="SP",
        ),
        dict(
            geolocation_zip_code_prefix="00001",
            geolocation_lat="-25",
            geolocation_lng="-47",
            geolocation_city="sao paulo",
            geolocation_state="SP",
        ),
        dict(geolocation_zip_code_prefix="00002", geolocation_lat="-22", geolocation_lng="-44"),
        dict(geolocation_zip_code_prefix="00003", geolocation_lat="999", geolocation_lng="-44"),
    ]
    write_source(raw, "geolocation", geo + [geo[0]])
    return raw


@pytest.fixture
def training_frame():
    rng = np.random.default_rng(42)
    n = 400
    frame = pd.DataFrame({name: rng.uniform(1, 10, n) for name in NUMERIC_FEATURES})
    frame["customer_state"] = np.where(np.arange(n) % 2, "SP", "RJ")
    frame["primary_seller_state"] = "SP"
    frame["primary_category"] = "books"
    frame["seller_history_late_rate"] = rng.uniform(0, 1, n)
    frame["region_history_late_rate"] = rng.uniform(0, 1, n)
    frame.index = pd.Index([f"t{i}" for i in range(n)], name="order_id")
    frame["purchased_at"] = pd.date_range("2017-01-01", periods=n, freq="D")
    frame["estimated_at"] = frame.purchased_at + pd.Timedelta(days=4)
    labels = (rng.random(n) < np.where(frame.customer_state.eq("RJ"), 0.6, 0.15)).astype(int)
    frame["delivered_at"] = frame.purchased_at + pd.to_timedelta(2 + labels * 4, unit="D")
    frame["label_available_at"] = frame.delivered_at + pd.Timedelta(days=1)
    frame["approved_at"] = frame.purchased_at + pd.Timedelta(hours=2)
    frame["carrier_at"] = frame.purchased_at + pd.Timedelta(days=1)
    frame["order_status"] = "delivered"
    frame["target_is_late"] = labels
    return frame
