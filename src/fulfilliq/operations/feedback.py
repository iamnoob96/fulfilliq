"""Read-only review distributions and conservatively redacted keyword excerpts."""

import re

from fulfilliq.nlp.reviews import STOP_WORDS, normalize_text, review_themes
from fulfilliq.operations.orders import OrderService

# Only a logistics/function-word vocabulary survives; names, addresses and arbitrary content do not.
SAFE_WORDS = set(STOP_WORDS) | set((
    "nao sem nunca entrega entregue entregou entregaram recebi recebido chegou chegaram "
    "antes depois dentro fora prazo rapido rapida atrasada atrasado atraso atrasou demorou "
    "demora demorado produto produtos pedido pedidos item itens errado errada faltou faltando "
    "incompleto completa qualidade ruim pessima pessimo bom boa otimo otima excelente bem "
    "embalagem caixa pacote amassada amassado danificada danificado rasgada aberto aberta "
    "quebrado quebrada defeito funciona recomendo satisfeito satisfeita super muito tudo certo"
).split())


def redacted_excerpt(value: str) -> str:
    tokens = normalize_text(value).split()
    text = " ".join(token if token in SAFE_WORDS else "[redigido]" for token in tokens)
    return re.sub(r"(?:\[redigido\] ){2,}", "[redigido] ", text)[:240]


def review_samples(orders: OrderService, *, seller_id=None, region=None, category=None,
                   limit: int = 12) -> dict:
    rows = orders.query("""SELECT r.review_score, r.review_comment_title, r.review_comment_message
        FROM order_reviews r JOIN orders o ON o.order_id=r.order_id
        JOIN customers c ON c.customer_id=o.customer_id
        WHERE (:region IS NULL OR c.customer_state=:region)
        AND EXISTS (SELECT 1 FROM order_items i JOIN dim_product p ON p.product_id=i.product_id
            WHERE i.order_id=o.order_id AND (:seller_id IS NULL OR i.seller_id=:seller_id)
            AND (:category IS NULL OR
                COALESCE(p.product_category_name_english,p.product_category_name,'unknown')=:category))
        ORDER BY r.review_row_id""", seller_id=seller_id, region=region, category=category)
    scores, examples, seen = {}, [], set()
    for row in rows:
        key = str(row["review_score"]) if row["review_score"] is not None else "missing"
        scores[key] = scores.get(key, 0) + 1
        text = (row["review_comment_title"] or "") + " " + (row["review_comment_message"] or "")
        themes = [key for key, matched in review_themes(text).items() if matched]
        excerpt = redacted_excerpt(text)
        if themes and excerpt not in seen and len(examples) < limit:
            examples.append({"excerpt": excerpt, "themes": themes, "review_score": row["review_score"]})
            seen.add(excerpt)
    return {"review_records": len(rows), "score_counts": scores, "examples": examples,
            "redaction": "Normalized excerpts retain only a conservative logistics/function-word "
            "allowlist; all other tokens are redacted. Identifiers, original text and names are omitted. "
            "Examples are deterministic lexical matches, not a random sample or verified complaints."}
