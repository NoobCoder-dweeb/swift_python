from __future__ import annotations

from importlib import import_module
import re
from decimal import Decimal
from typing import Any

from app.core.config import get_app_settings

try:
    psycopg = import_module("psycopg")
    dict_row = import_module("psycopg.rows").dict_row
except ImportError as exc:  # pragma: no cover - depends on optional runtime install
    psycopg = None
    dict_row = None
    _PSYCOPG_IMPORT_ERROR = exc
else:
    _PSYCOPG_IMPORT_ERROR = None


class PostgresProductLookupClient:
    """looks up approved product facts from the PostgreSQL product catalog."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or get_app_settings().database_url

    def get_product(self, query: str) -> dict[str, Any]:
        """returns the best active product match or a low-confidence miss."""
        query = (query or "").strip()
        if not query:
            return _missing_product_context(None)

        rows = self._list_products()
        best = _best_match(query, rows)
        if not best:
            return _missing_product_context(_extract_requested_product(query))

        return _row_to_context(best)

    def _list_products(self) -> list[dict[str, Any]]:
        psycopg_module, row_factory = _postgres_connection_parts()

        with psycopg_module.connect(
            self.database_url,
            autocommit=True,
            row_factory=row_factory,
        ) as conn:
            rows = conn.execute(
                """
                SELECT product_id, sku, name, category, description, currency,
                       unit_price, stock_availability, unit_of_measure, status
                FROM swift_products
                WHERE status = 'active'
                ORDER BY name
                """
            ).fetchall()
        return [dict(row) for row in rows]


def _postgres_connection_parts() -> tuple[Any, Any]:
    """returns concrete psycopg connection helpers before database use."""
    if psycopg is not None and dict_row is not None:
        return psycopg, dict_row
    raise RuntimeError(
        "PostgreSQL product lookup requires psycopg. Install dependencies "
        "from requirements.txt or use memory storage for local tests."
    ) from _psycopg_import_error()


def _psycopg_import_error() -> Exception:
    """returns the captured psycopg import failure as a concrete exception."""
    if _PSYCOPG_IMPORT_ERROR is not None:
        return _PSYCOPG_IMPORT_ERROR
    return RuntimeError("psycopg module is unavailable.")


def build_product_lookup_client() -> PostgresProductLookupClient | None:
    """uses PostgreSQL product facts when the configured app storage is PostgreSQL."""
    settings = get_app_settings()
    if settings.storage_mode != "postgres" or not settings.database_url:
        return None
    return PostgresProductLookupClient(settings.database_url)


def _row_to_context(row: dict[str, Any]) -> dict[str, Any]:
    price = row.get("unit_price")
    if isinstance(price, Decimal):
        price = float(price)

    notes = [
        f"Category: {row.get('category')}",
        f"Unit of measure: {row.get('unit_of_measure')}",
    ]
    description = (row.get("description") or "").strip()
    if description:
        notes.append(f"Description: {description}")

    return {
        "product": row.get("name"),
        "sku": row.get("sku"),
        "stock_availability": int(row.get("stock_availability") or 0),
        "price": price,
        "currency": row.get("currency") or "RM",
        "source": "postgres",
        "confidence": 0.96,
        "notes": notes,
    }


def _missing_product_context(product: str | None) -> dict[str, Any]:
    return {
        "product": product,
        "source": "postgres",
        "confidence": 0.0,
        "notes": ["No approved product record matched the inquiry."],
    }


def _best_match(query: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    query_lower = query.lower()
    query_tokens = _tokens(query)
    scored: list[tuple[int, str, dict[str, Any]]] = []

    for row in rows:
        sku = str(row.get("sku") or "").lower()
        name = str(row.get("name") or "")
        searchable = " ".join(
            str(row.get(field) or "")
            for field in ("sku", "name", "category", "description")
        )
        row_tokens = _tokens(searchable)
        score = len(query_tokens & row_tokens)

        if sku and sku in query_lower:
            score += 6
        if name and name.lower() in query_lower:
            score += 5

        if score >= 2:
            scored.append((score, name, row))

    if not scored:
        return None

    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[0][2]


def _tokens(value: str) -> set[str]:
    tokens = set()
    for token in re.findall(r"[a-z0-9]+", value.lower()):
        if len(token) < 2:
            continue
        tokens.add(token)
        if token.endswith("s") and len(token) > 3:
            tokens.add(token[:-1])
    return tokens


def _extract_requested_product(query: str) -> str | None:
    lowered = query.lower()
    patterns = (
        r"(?:for|about|of)\s+(?P<product>[a-z0-9][a-z0-9\s-]{2,80}?)(?:\?|\.|,| and | with | available| stock| price| pricing| quote| cost|$)",
        r"(?:do you (?:sell|have|carry)|is)\s+(?P<product>[a-z0-9][a-z0-9\s-]{2,80}?)(?:\?|\.|,| available| in stock|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, lowered, re.IGNORECASE)
        if match:
            product = _clean_requested_product(match.group("product"))
            return product.title() if product else None
    return None


def _clean_requested_product(value: str) -> str:
    product = " ".join(value.split()).strip(" -")
    product = re.sub(
        r"\b(?:in stock|stock|available|availability|price|pricing|quote|cost)\b.*$",
        "",
        product,
        flags=re.IGNORECASE,
    )
    return product.strip(" -")
