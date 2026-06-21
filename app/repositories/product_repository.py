from __future__ import annotations

from importlib import import_module
import re
from decimal import Decimal
from typing import Any

from app.core.config import get_app_settings


_PRODUCT_STOP_WORDS = {
    "about",
    "and",
    "any",
    "availability",
    "available",
    "browse",
    "can",
    "catalog",
    "category",
    "confirm",
    "cost",
    "current",
    "database",
    "description",
    "fit",
    "fits",
    "for",
    "get",
    "have",
    "how",
    "in",
    "inventory",
    "is",
    "list",
    "listed",
    "matching",
    "need",
    "of",
    "on",
    "please",
    "price",
    "pricing",
    "quote",
    "rate",
    "request",
    "show",
    "stock",
    "the",
    "unit",
    "units",
    "what",
    "with",
    "you",
}

_LOW_SIGNAL_SINGLE_TOKEN_MATCHES = {
    "product",
    "safety",
    "safetyware",
}

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
            return _missing_product_context(
                _extract_requested_product(query),
                suggestions=self.suggest_products(query, limit=3, rows=rows),
            )

        return _row_to_context(best)

    def search_products(
        self,
        query: str,
        *,
        limit: int = 5,
        rows: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """returns persisted active products matching customer criteria."""
        query = (query or "").strip()
        rows = rows if rows is not None else self._list_products()
        matches = _ranked_matches(
            query,
            rows,
            for_suggestions=True,
            relaxed_min_overlap=2,
        )
        if not matches and _is_catalog_listing_request(query):
            matches = rows
        return [_row_to_option(row, confidence=0.86) for row in matches[:limit]]

    def suggest_products(
        self,
        query: str,
        *,
        limit: int = 3,
        rows: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """returns nearest persisted alternatives without treating them as exact."""
        rows = rows if rows is not None else self._list_products()
        return [
            _row_to_option(row, confidence=0.62)
            for row in _ranked_matches(
                query,
                rows,
                for_suggestions=True,
                relaxed_min_overlap=1,
            )[:limit]
        ]

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


def _decimal_to_float(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def _row_to_context(row: dict[str, Any]) -> dict[str, Any]:
    price = row.get("unit_price")
    price = _decimal_to_float(price)

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

def _row_to_option(row: dict[str, Any], *, confidence: float) -> dict[str, Any]:
    return {
        "product": row.get("name"),
        "sku": row.get("sku"),
        "category": row.get("category"),
        "description": row.get("description"),
        "stock_availability": int(row.get("stock_availability") or 0),
        "price": _decimal_to_float(row.get("unit_price")),
        "currency": row.get("currency") or "RM",
        "unit_of_measure": row.get("unit_of_measure") or "unit",
        "source": "postgres",
        "confidence": confidence,
    }


def _missing_product_context(
    product: str | None,
    *,
    suggestions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "product": product,
        "source": "postgres",
        "confidence": 0.0,
        "notes": ["No approved product record matched the inquiry."],
        "suggested_products": suggestions or [],
    }


def _best_match(query: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    ranked = _ranked_matches(query, rows, for_suggestions=False)
    return ranked[0] if ranked else None


def _ranked_matches(
    query: str,
    rows: list[dict[str, Any]],
    *,
    for_suggestions: bool,
    relaxed_min_overlap: int = 1,
) -> list[dict[str, Any]]:
    query_lower = query.lower()
    query_tokens = _meaningful_product_tokens(query)
    scored: list[tuple[int, str, dict[str, Any]]] = []

    for row in rows:
        sku = str(row.get("sku") or "").lower()
        name = str(row.get("name") or "")
        name_lower = name.lower()
        searchable = " ".join(
            str(row.get(field) or "")
            for field in ("sku", "name", "category", "description")
        )
        row_tokens = _meaningful_product_tokens(searchable)
        name_tokens = _meaningful_product_tokens(name)
        token_overlap = query_tokens & row_tokens
        name_overlap = token_overlap & name_tokens
        direct_sku_match = bool(sku and sku in query_lower)
        direct_name_match = bool(name_lower and name_lower in query_lower)
        score = len(token_overlap)

        if direct_sku_match:
            score += 6
        if direct_name_match:
            score += 5

        sufficient = _has_sufficient_match_signal(
            direct_sku_match=direct_sku_match,
            direct_name_match=direct_name_match,
            query_tokens=query_tokens,
            token_overlap=token_overlap,
            name_overlap=name_overlap,
        )
        if for_suggestions and not sufficient:
            signal_overlap = token_overlap - _LOW_SIGNAL_SINGLE_TOKEN_MATCHES
            sufficient = len(signal_overlap) >= relaxed_min_overlap or bool(name_overlap)
        if not sufficient:
            continue

        if score > 0:
            scored.append((score, name, row))

    if not scored:
        return []

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored]


def _tokens(value: str) -> set[str]:
    tokens = set()
    for token in re.findall(r"[a-z0-9]+", value.lower()):
        if len(token) < 2:
            continue
        tokens.add(token)
        if token.endswith("s") and len(token) > 3:
            tokens.add(token[:-1])
    return tokens


def _meaningful_product_tokens(value: str) -> set[str]:
    """removes inquiry wording so catalog matching depends on product terms."""
    return {
        token
        for token in _tokens(value)
        if token not in _PRODUCT_STOP_WORDS and not token.isdigit()
    }


def _has_sufficient_match_signal(
    *,
    direct_sku_match: bool,
    direct_name_match: bool,
    query_tokens: set[str],
    token_overlap: set[str],
    name_overlap: set[str],
) -> bool:
    """rejects weak matches caused by quantities, stop words, or descriptions."""
    if direct_sku_match or direct_name_match:
        return True
    if len(token_overlap) >= 2 and name_overlap:
        return True
    if len(query_tokens) == 1 and name_overlap:
        return next(iter(name_overlap)) not in _LOW_SIGNAL_SINGLE_TOKEN_MATCHES
    return False


def _extract_requested_product(query: str) -> str | None:
    lowered = query.lower()
    patterns = (
        r"\b\d{1,6}(?:\.\d+)?\s*(?:units?|pcs?|pieces?|boxes?|cartons?|pairs?|sets?)\s+of\s+(?P<product>[a-z0-9][a-z0-9\s-]{2,80}?)(?:\?|\.|,| and | with | available| stock| price| pricing| quote| cost|$)",
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
    product = re.sub(r"^(?:the|a|an)\s+", "", product, flags=re.IGNORECASE)
    product = re.sub(
        r"^\d{1,6}(?:\.\d+)?\s*(?:units?|pcs?|pieces?|boxes?|cartons?|pairs?|sets?)?\s*(?:of\s+)?",
        "",
        product,
        flags=re.IGNORECASE,
    )
    product = re.sub(r"^(?:the|a|an)\s+", "", product, flags=re.IGNORECASE)
    product = re.sub(
        r"\b(?:in stock|stock|available|availability|price|pricing|quote|cost)\b.*$",
        "",
        product,
        flags=re.IGNORECASE,
    )
    return product.strip(" -")


def _is_catalog_listing_request(query: str) -> bool:
    lower = query.lower()
    return any(
        phrase in lower
        for phrase in (
            "list products",
            "list available products",
            "show products",
            "show available products",
            "what products",
            "which products",
            "browse products",
            "available products",
            "products in",
        )
    )
