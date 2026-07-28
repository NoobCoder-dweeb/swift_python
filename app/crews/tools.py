from __future__ import annotations

import json
from importlib import import_module
from typing import Any

from app.repositories.product_repository import build_product_lookup_client

try:
    _base_tool_module = import_module("crewai.tools.base_tool")
except Exception as exc:  # pragma: no cover - depends on optional runtime install
    BaseTool = object
    _CREWAI_TOOL_IMPORT_ERROR = exc
else:
    BaseTool = _base_tool_module.BaseTool
    _CREWAI_TOOL_IMPORT_ERROR = None


class ProductLookupGetProductTool(BaseTool):
    """CrewAI tool for fetching the best approved product match."""

    name: str = "postgres_product_lookup.get_product"
    description: str = (
        "Use this tool to retrieve the best approved product catalogue match for a "
        "customer product, pricing, stock, SKU, or delivery query. Input should "
        "be the full customer product query."
    )

    def _run(self, query: str) -> str:
        client = build_product_lookup_client()
        if client:
            return _json_result(client.get_product(query))
        return _json_result(_local_product_context(query))


class ProductLookupSearchProductsTool(BaseTool):
    """CrewAI tool for listing approved products matching a request."""

    name: str = "postgres_product_lookup.search_products"
    description: str = (
        "Use this tool for catalogue listing requests such as 'show products' or "
        "'which products do you carry'. Returns only persisted or approved "
        "catalogue rows that may be mentioned to the customer."
    )

    def _run(self, query: str, limit: int = 5) -> str:
        client = build_product_lookup_client()
        if client and hasattr(client, "search_products"):
            search_products = getattr(client, "search_products")
            return _json_result(search_products(query, limit=limit))
        return _json_result(_local_product_options(query, limit=limit))


class ProductLookupSuggestProductsTool(BaseTool):
    """CrewAI tool for approved alternatives when an exact match is missing."""

    name: str = "postgres_product_lookup.suggest_products"
    description: str = (
        "Use this tool when the exact requested product is ambiguous or missing. "
        "It returns nearby approved catalogue alternatives without treating them "
        "as exact product matches."
    )

    def _run(self, query: str, limit: int = 3) -> str:
        client = build_product_lookup_client()
        if client and hasattr(client, "suggest_products"):
            suggest_products = getattr(client, "suggest_products")
            return _json_result(suggest_products(query, limit=limit))
        return _json_result(_local_product_options(query, limit=limit))


_TOOL_FACTORIES = {
    "postgres_product_lookup.get_product": ProductLookupGetProductTool,
    "postgres_product_lookup.search_products": ProductLookupSearchProductsTool,
    "postgres_product_lookup.suggest_products": ProductLookupSuggestProductsTool,
}


def build_crewai_tools(tool_names: list[str]) -> list[Any]:
    """Instantiate CrewAI BaseTool objects declared in YAML agent config."""
    _ensure_crewai_tools_available()
    return [_tool_for_name(name) for name in tool_names]


def _tool_for_name(name: str) -> Any:
    try:
        return _TOOL_FACTORIES[name]()
    except KeyError as exc:
        known = ", ".join(sorted(_TOOL_FACTORIES))
        raise ValueError(f"Unknown CrewAI tool '{name}'. Known tools: {known}") from exc


def _ensure_crewai_tools_available() -> None:
    if _CREWAI_TOOL_IMPORT_ERROR is not None:
        raise RuntimeError("CrewAI BaseTool import failed.") from _CREWAI_TOOL_IMPORT_ERROR


def _json_result(value: Any) -> str:
    return json.dumps(_jsonable(value), indent=2, sort_keys=True)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _local_product_context(query: str) -> dict[str, Any]:
    from app.crews.agents import SalesProcessingAgent

    processor = SalesProcessingAgent()
    return processor.get_product_context(query)


def _local_product_options(query: str, *, limit: int) -> list[dict[str, Any]]:
    from app.crews.agents import SalesProcessingAgent

    processor = SalesProcessingAgent()
    return [
        item.model_dump()
        for item in processor.lookup_product_list_context(query).listed_products[:limit]
    ]
