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
    "catalogue",
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
    "inquire",
    "inquiry",
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
    "product",
    "products",
    "quote",
    "quotation",
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
    "your",
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
    """looks up approved product facts from the PostgreSQL product catalogue."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or get_app_settings().database_url

    def get_product(self, query: str) -> dict[str, Any]:
        """returns the best active product match or a low-confidence miss."""
        query = (query or "").strip()
        if not query:
            return _missing_product_context(None)

        rows = self._list_products()
        best = _best_catalog_match(query, rows)
        if not best:
            return _missing_product_context(
                _extract_requested_product_name(query),
                suggestions=self.suggest_products(query, limit=3, rows=rows),
            )

        return _catalog_row_to_product_context(best)

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
        matches = _rank_catalog_matches_by_relevance(
            query,
            rows,
            for_suggestions=True,
            relaxed_min_overlap=2,
        )
        if not matches and _asks_for_catalog_listing(query):
            matches = rows
        return [
            _catalog_row_to_product_option(row, confidence=0.86)
            for row in matches[:limit]
        ]

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
            _catalog_row_to_product_option(row, confidence=0.62)
            for row in _rank_catalog_matches_by_relevance(
                query,
                rows,
                for_suggestions=True,
                relaxed_min_overlap=1,
            )[:limit]
        ]

    def _list_products(self) -> list[dict[str, Any]]:
        """loads active catalogue rows that are approved for customer-facing drafts."""
        psycopg_module, row_factory = _postgres_connection_parts()

        with psycopg_module.connect(
            self.database_url,
            autocommit=True,
            row_factory=row_factory,
        ) as conn:
            rows = conn.execute(
                """
                SELECT product_id, sku, name, source_url, category, description, currency,
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
    """converts PostgreSQL Decimal prices into JSON-safe numeric values."""
    if isinstance(value, Decimal):
        return float(value)
    return value


def _catalog_row_to_product_context(row: dict[str, Any]) -> dict[str, Any]:
    """maps one persisted catalogue row into the drafting product context shape."""
    price = row.get("unit_price")
    price = _decimal_to_float(price)
    source_url = _effective_source_url(row)

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
        "source_url": source_url,
        "stock_availability": int(row.get("stock_availability") or 0),
        "price": price,
        "currency": row.get("currency") or "RM",
        "source": "postgres",
        "confidence": 0.96,
        "notes": notes,
    }


def _catalog_row_to_product_option(
    row: dict[str, Any], *, confidence: float
) -> dict[str, Any]:
    """maps a catalogue row into a suggested/listed product option."""
    return {
        "product": row.get("name"),
        "sku": row.get("sku"),
        "source_url": _effective_source_url(row),
        "category": row.get("category"),
        "description": row.get("description"),
        "stock_availability": int(row.get("stock_availability") or 0),
        "price": _decimal_to_float(row.get("unit_price")),
        "currency": row.get("currency") or "RM",
        "unit_of_measure": row.get("unit_of_measure") or "unit",
        "source": "postgres",
        "confidence": confidence,
    }


def _effective_source_url(row: dict[str, Any]) -> str | None:
    """recovers product URLs from current rows and older description-only imports."""
    source_url = str(row.get("source_url") or "").strip()
    if source_url and source_url != "https://safetyware.com/products/":
        return source_url

    description = str(row.get("description") or "")
    match = re.search(
        r"Source:\s*(https://safetyware\.com/product/[^.\s]+/)",
        description,
    )
    if match:
        return match.group(1)
    return source_url or None


def _missing_product_context(
    product: str | None,
    *,
    suggestions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """returns a safe low-confidence context when no approved catalogue match exists."""
    return {
        "product": product,
        "source": "postgres",
        "confidence": 0.0,
        "notes": ["No approved product record matched the inquiry."],
        "suggested_products": suggestions or [],
    }


def _best_catalog_match(query: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """selects the strongest approved catalogue row for exact product lookup."""
    ranked = _rank_catalog_matches_by_relevance(query, rows, for_suggestions=False)
    return ranked[0] if ranked else None


def _rank_catalog_matches_by_relevance(
    query: str,
    rows: list[dict[str, Any]],
    *,
    for_suggestions: bool,
    relaxed_min_overlap: int = 1,
) -> list[dict[str, Any]]:
    """scores catalogue rows by SKU/name hits and meaningful product-token overlap."""
    query_lower = query.lower()
    query_tokens = _meaningful_product_tokens(query)
    requested_product = _extract_requested_product_name(query)
    requested_tokens = _meaningful_product_tokens(requested_product or "")
    scored: list[tuple[int, int, int, str, dict[str, Any]]] = []

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
        # Product-name agreement is more trustworthy than words found only in
        # a category or description. Without this distinction, a competing
        # row whose prose happens to mention every query term can tie the
        # requested product and win alphabetically (for example, "Mobile
        # Garbage Bin ..." over "Round Pedal Bin 18L").
        name_score = len(name_overlap)
        supporting_score = len(token_overlap - name_overlap)
        direct_score = 0

        if direct_sku_match:
            direct_score += 6
        if direct_name_match:
            direct_score += 5

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
        if (
            not for_suggestions
            and len(requested_tokens) >= 2
            and not (direct_sku_match or direct_name_match)
            and not _tokens_are_covered(requested_tokens, name_tokens)
        ):
            # A partial family-name hit is useful as a suggestion, but it is
            # not safe enough to supply price or stock as an exact match.
            continue

        if direct_score or name_score or supporting_score:
            scored.append(
                (direct_score, name_score, supporting_score, name, row)
            )

    if not scored:
        return []

    scored.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
    return [item[4] for item in scored]


def _search_tokens(value: str) -> set[str]:
    """tokenizes customer/catalogue text and includes simple singular variants."""
    tokens = set()
    for token in re.findall(r"[a-z0-9]+", value.lower()):
        if len(token) < 2:
            continue
        tokens.add(token)
        if token.endswith("s") and len(token) > 3:
            tokens.add(token[:-1])
    return tokens


def _meaningful_product_tokens(value: str) -> set[str]:
    """removes inquiry wording so catalogue matching depends on product terms."""
    return {
        token
        for token in _search_tokens(value)
        if token not in _PRODUCT_STOP_WORDS and not token.isdigit()
    }


def _tokens_are_covered(requested: set[str], candidate: set[str]) -> bool:
    """allows simple plurals while requiring every requested product term."""
    return all(
        token in candidate
        or (token.endswith("s") and token[:-1] in candidate)
        for token in requested
    )


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


def _extract_requested_product_name(query: str) -> str | None:
    """best-effort extraction for explaining which product could not be matched."""
    lowered = query.lower()
    patterns = (
        r"(?:stock\s+availability|availability|stock)\s+(?:of|for)\s+(?:your|the|a|an)?\s*(?P<product>[a-z0-9][a-z0-9\s-]{2,80}?)(?:\?|\.|,|$)",
        r"\b\d{1,6}(?:\.\d+)?\s*(?:units?|pcs?|pieces?|boxes?|cartons?|pairs?|sets?)\s+of\s+(?P<product>[a-z0-9][a-z0-9\s-]{2,80}?)(?:\?|\.|,| and | with | available| stock| price| pricing| quote| cost|$)",
        r"(?:for|about|of)\s+(?P<product>[a-z0-9][a-z0-9\s-]{2,80}?)(?:\?|\.|,| and | with | available| stock| price| pricing| quote| cost|$)",
        r"(?:do you (?:sell|have|carry)|is)\s+(?P<product>[a-z0-9][a-z0-9\s-]{2,80}?)(?:\?|\.|,| available| in stock|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, lowered, re.IGNORECASE)
        if match:
            product = _clean_requested_product_name(match.group("product"))
            return product.title() if product else None
    return None


def _clean_requested_product_name(value: str) -> str:
    """removes quantity/request wording around an unmatched product phrase."""
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


def _asks_for_catalog_listing(query: str) -> bool:
    """detects broad browse/list intents where returning active products is useful."""
    lower = query.lower()
    return any(
        phrase in lower
        for phrase in (
            "list products",
            "list some products",
            "list available products",
            "show products",
            "show available products",
            "what products",
            "which products",
            "browse products",
            "browse catalog",
            "browse catalogue",
            "available products",
            "products in",
        )
    )
