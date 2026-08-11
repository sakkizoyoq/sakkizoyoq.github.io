"""Сборщик цен Makro (makromarket.uz), Ташкент.

У Makro есть открытый JSON-API без авторизации:

    GET https://api.makromarket.uz/api/v2/product-list/?limit=100&offset=0

Отдаёт акции недели (~305 товаров): название, старая и новая цена, процент
скидки, картинка, категория и — что приятно — даты начала и конца акции.
Заголовок Accept-Language управляет языком названий (ru / uz).

Запуск:  python3 -m scrapers.makro
"""
from __future__ import annotations

import gzip
import json
import urllib.request

from scrapers.common import now_iso, parse_price, polite_sleep, save_json

SOURCE = "makro"
API_URL = "https://api.makromarket.uz/api/v2/product-list/"


def _get(url: str, lang: str = "ru") -> dict:
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Accept-Language": lang,
        "Accept-Encoding": "gzip",
        "Referer": "https://makromarket.uz/",
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def normalize(raw: dict, titles_uz: dict[int, str] | None = None) -> dict:
    price = parse_price(raw.get("newPrice"))
    old = parse_price(raw.get("oldPrice"))
    return {
        "source": SOURCE,
        "source_product_id": raw.get("id"),
        "title_ru": raw.get("title"),
        "title_uz": (titles_uz or {}).get(raw.get("id")),
        "title_en": None,
        "vendor_code": raw.get("code"),
        "category": raw.get("category_title"),
        "price": price,
        "old_price": old if (old and old != price) else None,
        "discount_percent": raw.get("percent") or None,
        "is_discount": bool(raw.get("percent")),
        "unit": raw.get("weight"),
        "product_type": raw.get("promo_type"),
        "cashback": None,
        "image_url": raw.get("photo_medium"),
        # У Makro на сайте тоже нет страницы отдельного товара — весь акционный
        # каталог лежит одной страницей с фильтрами (проверено 11.08.2026).
        "product_url": "https://makromarket.uz/catalog",
        "currency": "UZS",
        "city": "Tashkent",
        "in_stock": raw.get("status") == 1,
        "promo_start": raw.get("startDate"),
        "promo_end": raw.get("endDate"),
        "scraped_at": now_iso(),
    }


def _fetch_all(lang: str = "ru") -> list[dict]:
    """Без параметра `p` API отдаёт весь список одним ответом (~305 товаров)."""
    data = _get(API_URL, lang=lang)
    return data if isinstance(data, list) else (data.get("results") or [])


def fetch_products() -> list[dict]:
    rows = _fetch_all("ru")

    # Второй проход на узбекском — те же товары, другие названия
    titles_uz: dict[int, str] = {}
    try:
        polite_sleep(0.4)
        for r in _fetch_all("uz"):
            titles_uz[r.get("id")] = r.get("title")
    except Exception:
        pass  # узбекские названия — приятный бонус, без них тоже работаем

    return [normalize(r, titles_uz) for r in rows if r.get("newPrice")]


def main() -> None:
    print(f"[{SOURCE}] загружаю {API_URL} ...")
    products = fetch_products()
    path = save_json(f"{SOURCE}_sample.json", products)
    discounted = sum(1 for p in products if p["is_discount"])
    with_uz = sum(1 for p in products if p["title_uz"])
    print(f"[{SOURCE}] готово — {len(products)} товаров → {path}")
    print(f"[{SOURCE}]   со скидкой: {discounted}, с узбекским названием: {with_uz}")
    for p in products[:3]:
        old = f" (было {p['old_price']})" if p["old_price"] else ""
        print(f"   • {p['title_ru'][:56]} — {p['price']} сум{old}")


if __name__ == "__main__":
    main()
