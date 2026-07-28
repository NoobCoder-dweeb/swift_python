from app.repositories.product_repository import PostgresProductLookupClient


def _arc_flash_row():
    return {
        "product_id": "SWP-ARC-40",
        "sku": "CATU-ARC-40",
        "name": "CATU 40 Cal Arc Flash Kit",
        "source_url": "https://safetyware.com/product/catu-40-cal-arc-flash-kit/",
        "category": "Arc Flash Protection",
        "description": "Electrical safety kit for arc flash protection.",
        "currency": "RM",
        "unit_price": 2062.25,
        "stock_availability": 15,
        "unit_of_measure": "unit",
        "status": "active",
    }


def _face_shield_row():
    return {
        "product_id": "SWP-FACE-01",
        "sku": "SAFE-FACE-SHIELD",
        "name": "Face Shield",
        "source_url": "https://safetyware.com/product/face-shield/",
        "category": "Eye And Face Protection",
        "description": "Clear safety shield for face protection.",
        "currency": "RM",
        "unit_price": 12.5,
        "stock_availability": 30,
        "unit_of_measure": "unit",
        "status": "active",
    }


def _safety_glasses_row():
    return {
        "product_id": "SWP-GLASSES-01",
        "sku": "SAFE-GLASSES",
        "name": "Safety Glasses",
        "source_url": "https://safetyware.com/product/safety-glasses/",
        "category": "Eye And Face Protection",
        "description": "Protective shield eyewear for industrial work.",
        "currency": "RM",
        "unit_price": 9.0,
        "stock_availability": 70,
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
    """specific product tokens should still resolve to the catalogue row."""
    client = PostgresProductLookupClient("postgresql://unused")
    monkeypatch.setattr(client, "_list_products", lambda: [_arc_flash_row()])

    result = client.get_product("Can I get pricing for a CATU 40 Cal Arc Flash Kit?")

    assert result["confidence"] == 0.96
    assert result["product"] == "CATU 40 Cal Arc Flash Kit"
    assert result["price"] == 2062.25
    assert result["source_url"] == "https://safetyware.com/product/catu-40-cal-arc-flash-kit/"


def test_postgres_product_lookup_recovers_source_url_from_legacy_description(monkeypatch):
    """old imports stored exact product URLs in descriptions before source_url existed."""
    row = {
        **_arc_flash_row(),
        "source_url": "https://safetyware.com/products/",
        "description": (
            "Safetyware catalogue item from category 'Arc Flash Protection'. "
            "Source: https://safetyware.com/product/catu-40-cal-arc-flash-kit/. "
            "Public catalogue price was unavailable."
        ),
    }
    client = PostgresProductLookupClient("postgresql://unused")
    monkeypatch.setattr(client, "_list_products", lambda: [row])

    result = client.get_product("Can I get pricing for a CATU 40 Cal Arc Flash Kit?")

    assert result["source_url"] == "https://safetyware.com/product/catu-40-cal-arc-flash-kit/"


def test_postgres_product_lookup_returns_suggestions_for_missing_product(monkeypatch):
    """nearby catalogue rows should be suggested without becoming quoted facts."""
    client = PostgresProductLookupClient("postgresql://unused")
    monkeypatch.setattr(
        client,
        "_list_products",
        lambda: [_face_shield_row(), _safety_glasses_row(), _arc_flash_row()],
    )

    result = client.get_product("Can you quote 10 units of carbon fiber shield?")

    assert result["confidence"] == 0.0
    assert result["product"] == "Carbon Fiber Shield"
    assert [item["product"] for item in result["suggested_products"]][:2] == [
        "Face Shield",
        "Safety Glasses",
    ]
    assert result["suggested_products"][0]["source_url"] == "https://safetyware.com/product/face-shield/"


def test_postgres_product_lookup_omits_suggestions_without_signal(monkeypatch):
    """totally unrelated products should ask for clearer database fields."""
    client = PostgresProductLookupClient("postgresql://unused")
    monkeypatch.setattr(client, "_list_products", lambda: [_arc_flash_row()])

    result = client.get_product("Can I get pricing for 40 units of strawberries?")

    assert result["confidence"] == 0.0
    assert result["suggested_products"] == []


def test_postgres_product_search_lists_matching_catalog_rows(monkeypatch):
    """list-style queries should return persisted product rows."""
    client = PostgresProductLookupClient("postgresql://unused")
    monkeypatch.setattr(
        client,
        "_list_products",
        lambda: [_arc_flash_row(), _face_shield_row(), _safety_glasses_row()],
    )

    result = client.search_products("List products in eye face protection", limit=5)

    assert [item["product"] for item in result] == [
        "Face Shield",
        "Safety Glasses",
    ]
    assert result[0]["price"] == 12.5
    assert result[0]["stock_availability"] == 30
    assert result[0]["source_url"] == "https://safetyware.com/product/face-shield/"


def test_postgres_product_search_lists_broad_available_products(monkeypatch):
    """generic list requests should fall back to active persisted products."""
    client = PostgresProductLookupClient("postgresql://unused")
    monkeypatch.setattr(
        client,
        "_list_products",
        lambda: [_arc_flash_row(), _face_shield_row(), _safety_glasses_row()],
    )

    result = client.search_products("Please list available products.", limit=2)

    assert [item["product"] for item in result] == [
        "CATU 40 Cal Arc Flash Kit",
        "Face Shield",
    ]


def test_postgres_product_search_accepts_catalog_listing_spelling(monkeypatch):
    """catalog and catalogue should both trigger broad listing fallback."""
    client = PostgresProductLookupClient("postgresql://unused")
    monkeypatch.setattr(
        client,
        "_list_products",
        lambda: [_arc_flash_row(), _face_shield_row(), _safety_glasses_row()],
    )

    result = client.search_products("Can I browse catalog?", limit=2)

    assert [item["product"] for item in result] == [
        "CATU 40 Cal Arc Flash Kit",
        "Face Shield",
    ]
