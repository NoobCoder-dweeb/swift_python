from app.repositories.product_repository import PostgresProductLookupClient


def _arc_flash_row():
    return {
        "product_id": "SWP-ARC-40",
        "sku": "CATU-ARC-40",
        "name": "CATU 40 Cal Arc Flash Kit",
        "category": "Arc Flash Protection",
        "description": "Electrical safety kit for arc flash protection.",
        "currency": "RM",
        "unit_price": 2062.25,
        "stock_availability": 15,
        "unit_of_measure": "unit",
        "status": "active",
    }


def test_postgres_product_lookup_rejects_quantity_only_overlap(monkeypatch):
    """a quantity like 40 must not match an unrelated 40 Cal product."""
    client = PostgresProductLookupClient("postgresql://unused")
    monkeypatch.setattr(client, "_list_products", lambda: [_arc_flash_row()])

    result = client.get_product(
        "Product pricing request\nCan I get pricing for 40 units of strawberries?"
    )

    assert result["confidence"] == 0.0
    assert result["product"] == "Strawberries"
    assert "CATU 40 Cal Arc Flash Kit" not in str(result)
    assert "2062.25" not in str(result)


def test_postgres_product_lookup_accepts_real_product_terms(monkeypatch):
    """specific product tokens should still resolve to the catalog row."""
    client = PostgresProductLookupClient("postgresql://unused")
    monkeypatch.setattr(client, "_list_products", lambda: [_arc_flash_row()])

    result = client.get_product("Can I get pricing for a CATU 40 Cal Arc Flash Kit?")

    assert result["confidence"] == 0.96
    assert result["product"] == "CATU 40 Cal Arc Flash Kit"
    assert result["price"] == 2062.25
