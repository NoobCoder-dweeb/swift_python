from scripts.import_safetyware_products import (
    PRODUCT_SOURCE_URL,
    build_product_rows,
    scrape_products,
    write_init_db,
)


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages

    def get(self, url: str, timeout: int) -> FakeResponse:
        return FakeResponse(self.pages[url])


def test_safetyware_importer_caps_products_and_writes_only_init_db(tmp_path):
    """the Safetyware generator should emit one init file and cap product rows."""
    session = FakeSession(
        {
            PRODUCT_SOURCE_URL: """
                <a href="https://safetyware.com/product-category/ppe/">PPE</a>
            """,
            "https://safetyware.com/product-category/ppe/": """
                <a href="https://safetyware.com/product/helmet/">Helmet</a>
                <a href="https://safetyware.com/product/gloves/">Gloves</a>
                <a href="https://safetyware.com/product/goggles/">Goggles</a>
            """,
        }
    )

    cards = scrape_products(
        session=session,
        limit=2,
        request_delay=0,
        max_pages=5,
    )
    rows = build_product_rows(cards)
    output_path = tmp_path / "init.db"

    write_init_db(rows, output_path)

    assert [row.name for row in rows] == ["Helmet", "Gloves"]
    assert output_path.exists()
    assert not list(tmp_path.glob("*.csv"))
    assert not list(tmp_path.glob("*.tbl"))
    init_sql = output_path.read_text(encoding="utf-8")
    assert "source_url" in init_sql
    assert "https://safetyware.com/product/helmet/" in init_sql
    assert "https://safetyware.com/product/goggles/" not in init_sql
