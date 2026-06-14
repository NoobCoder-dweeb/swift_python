from __future__ import annotations

import argparse
import csv
import html
import os
import random
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from sqlalchemy import MetaData, Table, create_engine, inspect, insert, select, text


BASE_URL = "https://safetyware.com"
PRODUCT_CATEGORY_SITEMAP = f"{BASE_URL}/product_cat-sitemap.xml"
DEFAULT_DATABASE_URL = "postgresql+pg8000://swift:swift@127.0.0.1:5432/swift"
PRODUCT_COLUMNS = [
    "product_id",
    "sku",
    "name",
    "category",
    "description",
    "currency",
    "unit_price",
    "stock_availability",
    "unit_of_measure",
    "status",
    "created_at",
    "updated_at",
]


@dataclass(frozen=True)
class CategoryUrl:
    url: str
    slug: str


@dataclass(frozen=True)
class ProductCard:
    source_product_id: str
    source_url: str
    name: str
    category: str
    category_url: str
    category_slug: str


@dataclass(frozen=True)
class ProductRow:
    product_id: str
    sku: str
    name: str
    category: str
    description: str
    currency: str
    unit_price: Decimal
    stock_availability: int
    unit_of_measure: str
    status: str
    created_at: datetime
    updated_at: datetime


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 Chrome/125 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )

    category_urls = load_category_urls(session, out_dir / "safetyware_product_cat_sitemap.xml")
    print(f"Found {len(category_urls)} English Safetyware category URLs")

    cards = scrape_category_cards(
        session=session,
        category_urls=category_urls,
        limit_per_category=args.category_limit,
        request_delay=args.request_delay,
    )
    rows = build_product_rows(cards)
    print(f"Prepared {len(rows)} product rows from {len({c.category for c in cards})} categories")

    write_product_files(rows, out_dir)
    if not args.skip_db:
        load_products(args, out_dir / "swift_products_load.csv", len(rows))
        export_all_tables(args, out_dir / "tables")
    write_import_sql(rows, out_dir / "swift_products_import.sql")

    print(f"Wrote import/export files under {out_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scrape up to N Safetyware products per English product category, "
            "load swift_products, and export public Postgres tables."
        )
    )
    parser.add_argument("--category-limit", type=int, default=10)
    parser.add_argument("--request-delay", type=float, default=0.15)
    parser.add_argument("--output-dir", default="exports/safetyware_products")
    parser.add_argument(
        "--database-url",
        default=normalize_database_url(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)),
    )
    parser.add_argument("--skip-db", action="store_true")
    return parser.parse_args()


def load_category_urls(session: requests.Session, cache_path: Path) -> list[CategoryUrl]:
    if cache_path.exists():
        xml_text = cache_path.read_text(encoding="utf-8")
    else:
        response = session.get(PRODUCT_CATEGORY_SITEMAP, timeout=30)
        response.raise_for_status()
        xml_text = response.text
        cache_path.write_text(xml_text, encoding="utf-8")

    root = ET.fromstring(xml_text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls: list[CategoryUrl] = []
    seen: set[str] = set()

    for loc in root.findall(".//sm:loc", ns):
        url = (loc.text or "").strip()
        if not url or "/th/" in url or "/product-category/" not in url:
            continue
        slug = category_slug_from_url(url)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        urls.append(CategoryUrl(url=url, slug=slug))

    return urls


def scrape_category_cards(
    *,
    session: requests.Session,
    category_urls: list[CategoryUrl],
    limit_per_category: int,
    request_delay: float,
) -> list[ProductCard]:
    cards: list[ProductCard] = []
    categories_with_products = 0

    for index, category in enumerate(category_urls, start=1):
        page_cards = scrape_one_category(
            session=session,
            category=category,
            limit=limit_per_category,
            request_delay=request_delay,
        )
        if page_cards:
            categories_with_products += 1
            cards.extend(page_cards[:limit_per_category])

        if index % 10 == 0:
            print(
                f"Scanned {index}/{len(category_urls)} categories; "
                f"{categories_with_products} yielded products; {len(cards)} rows so far"
            )

    return cards


def scrape_one_category(
    *,
    session: requests.Session,
    category: CategoryUrl,
    limit: int,
    request_delay: float,
) -> list[ProductCard]:
    collected: list[ProductCard] = []
    next_url = category.url
    seen_product_urls: set[str] = set()

    for _ in range(5):
        response = session.get(next_url, timeout=30)
        if response.status_code == 404:
            break
        response.raise_for_status()

        html_text = response.text
        for card in parse_product_cards(html_text, category):
            if card.source_url in seen_product_urls:
                continue
            seen_product_urls.add(card.source_url)
            collected.append(card)
            if len(collected) >= limit:
                return collected

        next_url = find_next_page(html_text)
        if not next_url or next_url == category.url:
            break
        time.sleep(request_delay)

    if request_delay:
        time.sleep(request_delay)
    return collected


def parse_product_cards(html_text: str, category: CategoryUrl) -> list[ProductCard]:
    pattern = re.compile(
        r'<div class="product-small col[^"]* product type-product post-(?P<id>\d+)[\s\S]*?'
        r'<p class="category[^>]*>\s*(?P<category>[\s\S]*?)\s*</p>\s*'
        r'<p class="name product-title[^>]*><a href="(?P<url>[^"]+)"[^>]*>'
        r"(?P<name>[\s\S]*?)</a>",
        re.IGNORECASE,
    )
    cards: list[ProductCard] = []

    for match in pattern.finditer(html_text):
        source_url = normalize_whitespace(html.unescape(match.group("url")))
        name = clean_text(match.group("name"))
        display_category = title_from_slug(category.slug)
        if not source_url.startswith(f"{BASE_URL}/product/") or not name:
            continue
        cards.append(
            ProductCard(
                source_product_id=match.group("id"),
                source_url=source_url,
                name=name,
                category=display_category or title_from_slug(category.slug),
                category_url=category.url,
                category_slug=category.slug,
            )
        )

    return cards


def find_next_page(html_text: str) -> str | None:
    match = re.search(
        r'<a[^>]+class="next page-number"[^>]+href="([^"]+)"',
        html_text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return html.unescape(match.group(1))


def build_product_rows(cards: list[ProductCard]) -> list[ProductRow]:
    rng = random.Random()
    now = datetime.now(timezone.utc)
    used_ids: set[str] = set()
    used_skus: set[str] = set()
    rows: list[ProductRow] = []

    for index, card in enumerate(cards, start=1):
        product_id = unique_random_id(rng, used_ids)
        sku = unique_sku(card, index, rng, used_skus)
        price = estimated_price(card.category, rng)
        description = (
            f"Safetyware catalog item from category '{card.category}'. "
            f"Source: {card.source_url}. "
            "Public catalog price was unavailable; unit_price is an estimated "
            "average for similar products in this category."
        )
        rows.append(
            ProductRow(
                product_id=product_id,
                sku=sku,
                name=card.name,
                category=card.category,
                description=description,
                currency="RM",
                unit_price=price,
                stock_availability=rng.randint(5, 500),
                unit_of_measure=unit_of_measure(card.category, card.name),
                status="active",
                created_at=now,
                updated_at=now,
            )
        )

    return rows


def unique_random_id(rng: random.Random, used: set[str]) -> str:
    while True:
        product_id = f"SWP-{rng.randint(10_000_000, 99_999_999)}"
        if product_id not in used:
            used.add(product_id)
            return product_id


def unique_sku(card: ProductCard, index: int, rng: random.Random, used: set[str]) -> str:
    base = re.sub(r"[^A-Z0-9]+", "-", card.category_slug.upper()).strip("-")[:24]
    while True:
        sku = f"SW-{base}-{card.source_product_id}-{rng.randint(100, 999)}"
        if len(sku) > 64:
            sku = f"SW-{card.source_product_id}-{index}-{rng.randint(100, 999)}"
        if sku not in used:
            used.add(sku)
            return sku


def estimated_price(category: str, rng: random.Random) -> Decimal:
    text = category.lower()
    ranges = [
        (("sign", "label", "poster", "print"), (12, 55)),
        (("glove", "hand", "sleeve"), (6, 45)),
        (("shoe", "boot", "foot"), (75, 280)),
        (("helmet", "head", "cap"), (25, 120)),
        (("respirator", "mask", "respiratory", "filter"), (10, 220)),
        (("fall", "harness", "lanyard", "anchorage"), (80, 520)),
        (("fire", "extinguisher", "hose"), (45, 380)),
        (("training", "assessment", "consultation", "rental"), (250, 2500)),
        (("instrument", "detector", "monitor", "tester", "electrical"), (150, 3600)),
        (("aed", "defibrillator"), (700, 6500)),
        (("first aid", "rescue", "medical"), (20, 700)),
        (("traffic", "barricade", "cone", "bollard"), (35, 650)),
        (("apron", "apparel", "workwear", "rainwear", "body"), (25, 240)),
        (("wipe", "cleanser", "sanitiser", "disinfectant"), (8, 140)),
    ]
    low, high = 50, 500
    for keywords, candidate in ranges:
        if any(keyword in text for keyword in keywords):
            low, high = candidate
            break
    value = rng.uniform(low, high)
    return Decimal(str(round(value, 2))).quantize(Decimal("0.01"))


def unit_of_measure(category: str, name: str) -> str:
    text = f"{category} {name}".lower()
    if any(word in text for word in ("glove", "shoe", "boot", "sock", "pad")):
        return "pair"
    if any(word in text for word in ("wipe", "battery", "filter", "label", "sign")):
        return "pack"
    if any(word in text for word in ("training", "assessment", "consultation", "rental")):
        return "service"
    return "unit"


def write_product_files(rows: list[ProductRow], out_dir: Path) -> None:
    write_rows_csv(out_dir / "swift_products_load.csv", PRODUCT_COLUMNS, rows)
    write_rows_csv(out_dir / "swift_products_load.tbl", PRODUCT_COLUMNS, rows, delimiter="\t")


def write_rows_csv(
    path: Path,
    columns: list[str],
    rows: list[Any],
    *,
    delimiter: str = ",",
) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file, delimiter=delimiter)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([format_value(getattr(row, column)) for column in columns])


def load_products(args: argparse.Namespace, csv_path: Path, row_count: int) -> None:
    engine = create_engine(args.database_url)
    rows = [row_to_mapping(row) for row in read_product_csv(csv_path)]
    metadata = MetaData()
    products = Table("swift_products", metadata, autoload_with=engine)

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE swift_products"))
        if rows:
            conn.execute(insert(products), rows)

    print(f"Truncated and inserted {row_count} rows into swift_products")


def export_all_tables(args: argparse.Namespace, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(args.database_url)
    inspector = inspect(engine)
    table_names = sorted(inspector.get_table_names(schema="public"))
    metadata = MetaData()

    with engine.connect() as conn:
        for table_name in table_names:
            table = Table(table_name, metadata, schema="public", autoload_with=engine)
            columns = [column.name for column in table.columns]
            order_column = next(iter(table.columns))
            records = conn.execute(select(table).order_by(order_column)).fetchall()
            csv_text = table_records_to_csv(columns, records)
            csv_path = out_dir / f"{table_name}.csv"
            tbl_path = out_dir / f"{table_name}.tbl"
            csv_path.write_text(csv_text, encoding="utf-8")
            convert_csv_to_tbl(csv_text, tbl_path)
            print(f"Exported {table_name}: {len(records)} rows")


def read_product_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def row_to_mapping(row: dict[str, Any]) -> dict[str, Any]:
    converted = dict(row)
    converted["unit_price"] = Decimal(converted["unit_price"])
    converted["stock_availability"] = int(converted["stock_availability"])
    converted["created_at"] = datetime.fromisoformat(converted["created_at"])
    converted["updated_at"] = datetime.fromisoformat(converted["updated_at"])
    return converted


def table_records_to_csv(columns: list[str], records: list[Any]) -> str:
    from io import StringIO

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for record in records:
        writer.writerow([format_value(value) for value in record])
    return buffer.getvalue()


def normalize_database_url(database_url: str) -> str:
    database_url = database_url.replace("@postgres:", "@127.0.0.1:")
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+pg8000://", 1)
    return database_url


def convert_csv_to_tbl(csv_text: str, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        reader = csv.reader(csv_text.splitlines())
        writer = csv.writer(file, delimiter="\t")
        writer.writerows(reader)


def write_import_sql(rows: list[ProductRow], path: Path) -> None:
    lines = [
        "TRUNCATE TABLE swift_products;",
        "INSERT INTO swift_products ("
        + ", ".join(PRODUCT_COLUMNS)
        + ") VALUES",
    ]
    values = []
    for row in rows:
        literals = [sql_literal(getattr(row, column)) for column in PRODUCT_COLUMNS]
        values.append("(" + ", ".join(literals) + ")")
    lines.append(",\n".join(values) + ";")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (int, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        return "'" + value.isoformat().replace("'", "''") + "'"
    return "'" + str(value).replace("'", "''") + "'"


def format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def category_slug_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    parts = [part for part in path.split("/") if part]
    return parts[-1] if parts else ""


def title_from_slug(slug: str) -> str:
    return slug.replace("-", " ").title()


def clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    return normalize_whitespace(html.unescape(value))


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


if __name__ == "__main__":
    main()
