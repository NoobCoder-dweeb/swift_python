from __future__ import annotations

import argparse
import hashlib
import html
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests


BASE_URL = "https://safetyware.com"
PRODUCT_SOURCE_URL = f"{BASE_URL}/products/"
DEFAULT_PRODUCT_LIMIT = 50
DEFAULT_OUTPUT_PATH = "init.db"
PRODUCT_COLUMNS = [
    "product_id",
    "sku",
    "name",
    "source_url",
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
class CategoryPage:
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
    source_url: str
    category: str
    description: str
    currency: str
    unit_price: Decimal
    stock_availability: int
    unit_of_measure: str
    status: str
    created_at: datetime
    updated_at: datetime


class LinkCollector(HTMLParser):
    """extracts href/text pairs without adding a heavy parser dependency."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href_stack: list[str | None] = []
        self._text_stack: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = next((value for name, value in attrs if name.lower() == "href"), None)
        self._href_stack.append(href)
        self._text_stack.append([])

    def handle_data(self, data: str) -> None:
        if self._text_stack:
            self._text_stack[-1].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href_stack:
            return
        href = self._href_stack.pop()
        text = normalize_whitespace(" ".join(self._text_stack.pop()))
        if href:
            self.links.append((href, text))


def main() -> None:
    args = parse_args()
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

    cards = scrape_products(
        session=session,
        limit=args.limit,
        request_delay=args.request_delay,
        max_pages=args.max_pages,
    )
    rows = build_product_rows(cards)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_init_db(rows, output_path)
    print(f"Wrote {len(rows)} Safetyware products to {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate one Postgres init.db file with Safetyware product rows."
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_PRODUCT_LIMIT)
    parser.add_argument("--request-delay", type=float, default=0.15)
    parser.add_argument("--max-pages", type=int, default=250)
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def scrape_products(
    *,
    session: requests.Session,
    limit: int,
    request_delay: float,
    max_pages: int,
) -> list[ProductCard]:
    queue = load_initial_category_pages(session)
    seen_categories: set[str] = set()
    seen_products: set[str] = set()
    cards: list[ProductCard] = []

    while queue and len(cards) < limit and len(seen_categories) < max_pages:
        category = queue.pop(0)
        if category.url in seen_categories:
            continue
        seen_categories.add(category.url)

        response = session.get(category.url, timeout=30)
        if response.status_code == 404:
            continue
        response.raise_for_status()
        html_text = response.text

        for child in parse_category_links(html_text):
            if child.url not in seen_categories and child not in queue:
                queue.append(child)

        for card in parse_product_links(html_text, category):
            if card.source_url in seen_products:
                continue
            seen_products.add(card.source_url)
            cards.append(card)
            if len(cards) >= limit:
                break

        next_page = find_next_page(html_text)
        if next_page and next_page not in seen_categories:
            queue.insert(0, CategoryPage(url=next_page, slug=category.slug))

        if request_delay:
            time.sleep(request_delay)

    if len(cards) < limit:
        raise RuntimeError(
            f"Expected {limit} product rows from {PRODUCT_SOURCE_URL}, found {len(cards)}."
        )
    return cards[:limit]


def load_initial_category_pages(session: requests.Session) -> list[CategoryPage]:
    response = session.get(PRODUCT_SOURCE_URL, timeout=30)
    response.raise_for_status()
    categories = parse_category_links(response.text)
    if not categories:
        raise RuntimeError(f"No Safetyware category links found at {PRODUCT_SOURCE_URL}")
    return categories


def parse_category_links(html_text: str) -> list[CategoryPage]:
    categories: list[CategoryPage] = []
    seen: set[str] = set()
    for href, _ in collect_links(html_text):
        url = normalize_url(href)
        if not url or "/th/" in url or "/product-category/" not in url:
            continue
        slug = category_slug_from_url(url)
        if not slug or url in seen:
            continue
        seen.add(url)
        categories.append(CategoryPage(url=url, slug=slug))
    return categories


def parse_product_links(html_text: str, category: CategoryPage) -> list[ProductCard]:
    cards: list[ProductCard] = []
    seen: set[str] = set()
    for href, text in collect_links(html_text):
        url = normalize_url(href)
        if not url or "/th/" in url or "/product/" not in url:
            continue
        if "/product-category/" in url or url in seen:
            continue
        seen.add(url)
        name = clean_text(text) or title_from_slug(product_slug_from_url(url))
        if not name:
            continue
        cards.append(
            ProductCard(
                source_product_id=source_id_from_url(url),
                source_url=url,
                name=name,
                category=title_from_slug(category.slug),
                category_url=category.url,
                category_slug=category.slug,
            )
        )
    return cards


def collect_links(html_text: str) -> list[tuple[str, str]]:
    parser = LinkCollector()
    parser.feed(html_text)
    return parser.links


def build_product_rows(cards: list[ProductCard]) -> list[ProductRow]:
    rng = random.Random(20260624)
    now = datetime.now(timezone.utc)
    used_ids: set[str] = set()
    used_skus: set[str] = set()
    rows: list[ProductRow] = []

    for index, card in enumerate(cards, start=1):
        product_id = unique_product_id(card, used_ids)
        sku = unique_sku(card, index, used_skus)
        price = estimated_price(card.category, rng)
        description = (
            f"Safetyware catalogue item from category '{card.category}'. "
            f"Source: {card.source_url}. "
            "Public catalogue price was unavailable; unit_price is an estimated "
            "average for similar products in this category."
        )
        rows.append(
            ProductRow(
                product_id=product_id,
                sku=sku,
                name=card.name,
                source_url=card.source_url,
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


def unique_product_id(card: ProductCard, used: set[str]) -> str:
    base = f"SWP-{card.source_product_id}"
    product_id = base
    suffix = 2
    while product_id in used:
        product_id = f"{base}-{suffix}"
        suffix += 1
    used.add(product_id)
    return product_id


def unique_sku(card: ProductCard, index: int, used: set[str]) -> str:
    base = re.sub(r"[^A-Z0-9]+", "-", card.category_slug.upper()).strip("-")[:24]
    source_id = re.sub(r"[^A-Z0-9]+", "-", card.source_product_id.upper()).strip("-")
    sku = f"SW-{base}-{source_id}"
    if len(sku) > 64:
        sku = f"SW-{source_id}-{index}"
    candidate = sku
    suffix = 2
    while candidate in used:
        candidate = f"{sku}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


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


def write_init_db(rows: list[ProductRow], path: Path) -> None:
    statements = [
        "-- Project Swift database initialiser generated from https://safetyware.com/products/",
        "BEGIN;",
        create_schema_sql(),
        "TRUNCATE TABLE swift_products;",
    ]
    if rows:
        values = []
        for row in rows:
            literals = [sql_literal(getattr(row, column)) for column in PRODUCT_COLUMNS]
            values.append("(" + ", ".join(literals) + ")")
        statements.append(
            "INSERT INTO swift_products ("
            + ", ".join(PRODUCT_COLUMNS)
            + ") VALUES\n"
            + ",\n".join(values)
            + ";"
        )
    statements.append("COMMIT;")
    path.write_text("\n\n".join(statements) + "\n", encoding="utf-8")


def create_schema_sql() -> str:
    return """
CREATE TABLE IF NOT EXISTS swift_drafts (
    draft_id TEXT PRIMARY KEY,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL,
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    revisions INTEGER NOT NULL DEFAULT 0,
    last_rejection_reason TEXT NOT NULL DEFAULT '',
    ai_draft_text TEXT NOT NULL DEFAULT '',
    workflow JSONB
);

CREATE INDEX IF NOT EXISTS swift_drafts_review_idx
    ON swift_drafts (status, created DESC);

CREATE TABLE IF NOT EXISTS swift_audits (
    audit_id TEXT PRIMARY KEY,
    draft_id TEXT,
    action TEXT,
    timestamp TEXT,
    payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS swift_audits_action_idx
    ON swift_audits (action, timestamp DESC);

CREATE TABLE IF NOT EXISTS swift_emails (
    email_id TEXT PRIMARY KEY,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    raw_body TEXT,
    preprocessed BOOLEAN NOT NULL DEFAULT FALSE,
    removed_line_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    draft_id TEXT,
    payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS swift_emails_created_idx
    ON swift_emails (created_at DESC);

CREATE TABLE IF NOT EXISTS swift_products (
    product_id TEXT PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    source_url TEXT NOT NULL DEFAULT 'https://safetyware.com/products/',
    category TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    currency TEXT NOT NULL DEFAULT 'RM',
    unit_price NUMERIC(10,2) NOT NULL,
    stock_availability INTEGER NOT NULL DEFAULT 0,
    unit_of_measure TEXT NOT NULL DEFAULT 'unit',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS swift_products_status_idx
    ON swift_products (status, name);
""".strip()


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (int, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        return "'" + value.isoformat().replace("'", "''") + "'"
    return "'" + str(value).replace("'", "''") + "'"


def find_next_page(html_text: str) -> str | None:
    match = re.search(
        r'<a[^>]+class="[^"]*\bnext\s+page-number\b[^"]*"[^>]+href="([^"]+)"',
        html_text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return normalize_url(html.unescape(match.group(1)))


def normalize_url(href: str) -> str | None:
    href = html.unescape(href).strip()
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
        return None
    url = urljoin(PRODUCT_SOURCE_URL, href)
    parsed = urlparse(url)
    if parsed.netloc and parsed.netloc != urlparse(BASE_URL).netloc:
        return None
    clean_path = parsed.path or "/"
    if not clean_path.endswith("/"):
        clean_path = f"{clean_path}/"
    return f"{BASE_URL}{clean_path}"


def source_id_from_url(url: str) -> str:
    slug = product_slug_from_url(url)
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8].upper()
    return re.sub(r"[^A-Z0-9]+", "-", slug.upper()).strip("-")[:36] or digest


def category_slug_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    parts = [part for part in path.split("/") if part]
    return parts[-1] if parts else ""


def product_slug_from_url(url: str) -> str:
    return category_slug_from_url(url)


def title_from_slug(slug: str) -> str:
    return slug.replace("-", " ").title()


def clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    return normalize_whitespace(html.unescape(value))


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


if __name__ == "__main__":
    main()
