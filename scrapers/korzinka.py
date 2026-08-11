"""Scraper for Korzinka (korzinka.uz), Tashkent.

Korzinka's website (Nuxt/Vue) is powered by a clean public JSON API on the
`catalog.korzinka.uz` subdomain. The promotions catalog — categories with all
their products and prices — is available with a single unauthenticated GET:

    GET https://catalog.korzinka.uz/api/catalogs/categories

No login, no Cloudflare challenge on this endpoint. This module fetches it and
normalises every product into our common schema (see `normalize_product`).

Run it directly:

    python3 scrapers/korzinka.py
"""
from __future__ import annotations

from scrapers.common import (
    http_get_json,
    now_iso,
    parse_percent,
    parse_price,
    save_json,
)

SOURCE = "korzinka"
CATEGORIES_URL = "https://catalog.korzinka.uz/api/catalogs/categories"


def normalize_product(raw: dict, category_title: str) -> dict:
    """Map one Korzinka product object into our common product schema."""
    prices = raw.get("prices") or {}
    return {
        "source": SOURCE,
        "source_product_id": raw.get("id"),
        "title_ru": raw.get("title_ru") or raw.get("title"),
        "title_uz": raw.get("title_uz"),
        "title_en": raw.get("title_en"),
        "vendor_code": raw.get("vendor_code"),  # barcode/SKU when present -> used for matching
        "category": category_title,
        "price": parse_price(prices.get("actual_price")),
        "old_price": parse_price(prices.get("old_price")),
        "discount_percent": parse_percent(prices.get("price_tag_name")),
        "is_discount": bool(prices.get("is_discount")),
        "unit": raw.get("weight_param"),
        "product_type": prices.get("product_type"),
        "cashback": prices.get("cashback_size"),
        "image_url": raw.get("small_image_url"),
        # У Korzinka нет отдельной страницы товара: их собственный product_url —
        # это ссылка на установку приложения, одинаковая для всех товаров.
        # Проверено 11.08.2026, поэтому ведём на страницу акционного каталога.
        "product_url": "https://korzinka.uz/ru/catalog",
        "currency": "UZS",
        "city": "Tashkent",
        "in_stock": True,
        "scraped_at": now_iso(),
    }


def fetch_products() -> list[dict]:
    """Fetch and normalise all products from the Korzinka promotions catalog."""
    payload = http_get_json(CATEGORIES_URL)
    categories = payload.get("data") or payload
    products: list[dict] = []
    for cat in categories:
        title = cat.get("title_ru") or cat.get("title") or cat.get("title_uz") or ""
        for raw in cat.get("products") or []:
            products.append(normalize_product(raw, title))
    return products


def main() -> None:
    print(f"[{SOURCE}] fetching {CATEGORIES_URL} ...")
    products = fetch_products()

    with_barcode = sum(1 for p in products if p["vendor_code"])
    discounted = sum(1 for p in products if p["is_discount"])

    path = save_json(f"{SOURCE}_sample.json", products)

    print(f"[{SOURCE}] OK — {len(products)} products saved to {path}")
    print(f"[{SOURCE}]   with barcode/SKU: {with_barcode}   on discount: {discounted}")
    print(f"[{SOURCE}] example rows:")
    for p in products[:3]:
        old = f" (was {p['old_price']})" if p["old_price"] else ""
        print(f"   • {p['title_ru']} — {p['price']} {p['currency']}{old}  [{p['category']}]")


if __name__ == "__main__":
    main()
