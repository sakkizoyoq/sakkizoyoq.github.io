"""Сборщик полных каталогов магазинов из Яндекс Еды (Ташкент).

На сайте каталог магазина открывается только после ввода адреса доставки,
но данные отдаёт запрос, которому адрес не нужен вовсе:

    POST https://eats.yandex.com/api/v2/menu/goods
    {"slug": "makro_knsfg"}                    → дерево категорий
    {"slug": "makro_knsfg", "category": 1034}  → категория вместе с товарами

Без авторизации. Товары лежат внутри `payload.categories[].items[]`, поэтому
проходим по верхним категориям и собираем всё, убирая повторы по `uid`.

Здесь лежит ПОЛНЫЙ ассортимент доставки: у Makro ~3000 товаров против 305
акционных на их собственном сайте.

Важно: названия записаны латиницей, как в кассовой системе магазина
(«Pyure rastishka yabloko grusha 85gr»). Сопоставлением с русскими названиями
занимается matching.py — там есть перевод латиницы.

Запуск:  python3 -m scrapers.yandex_eats
"""
from __future__ import annotations

import gzip
import json
import urllib.request

from scrapers.common import now_iso, parse_price, polite_sleep, save_json

API_URL = "https://eats.yandex.com/api/v2/menu/goods"

# Магазины Ташкента: слаг в Яндекс Еде → как показываем пользователю.
#
# ВАЖНО: новые магазины сюда добавляет только Валерия. Не расширять список
# по своей инициативе — сначала спросить.
#
# Доступные, но пока не подключённые: safia_68j4q (пекарня Safia) — убрана
# по просьбе 10.08.2026.
STORES = {
    "makro_knsfg": "Makro (Яндекс)",
}

# Кусок адреса страницы магазина на сайте Яндекс Еды: slug магазина → бренд.
# Ссылка на товар выглядит так:
#   https://eats.yandex.com/uz/retail/<бренд>/product/<slug товара>?placeSlug=<slug магазина>
BRAND_SLUGS = {
    "makro_knsfg": "makro",
}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Accept-Encoding": "gzip",
    "Accept-Language": "ru",
    "Referer": "https://eats.yandex.com/uz/",
}


def _post(payload: dict) -> dict:
    req = urllib.request.Request(API_URL, data=json.dumps(payload).encode(),
                                 headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def _picture_url(item: dict) -> str | None:
    """Картинки отдаются шаблоном с {w}x{h} — подставляем нужный размер."""
    pic = item.get("picture") or {}
    url = pic.get("url") if isinstance(pic, dict) else pic
    if not url:
        return None
    return url.replace("{w}", "400").replace("{h}", "400")


def _product_url(item: dict, slug: str) -> str:
    """Ссылка на страницу товара в Яндекс Еде.

    Адрес страницы товара у них устроен так (взято из их же кода, из описания
    маршрутов сайта):

        /retail/<бренд>/product/<slug товара>/<код товара>?placeSlug=<магазин>

    Последняя часть — код товара (uid) — обязательна. Без неё Яндекс принимает
    slug за код, товара с таким кодом не находит и выкидывает на главную
    (в адресе видно redirectFrom=not_found_page).

    Первый заход Яндекс встречает просьбой указать адрес доставки — это его
    поведение, а не наша ошибка: без адреса он так же не открывает и свои
    собственные страницы магазинов.
    """
    brand = BRAND_SLUGS.get(slug, slug)
    uid = item.get("uid") or item.get("public_id")
    if not uid:
        return f"https://eats.yandex.com/uz/retail/{brand}?placeSlug={slug}"
    item_slug = item.get("slug")
    tail = f"{item_slug}/{uid}" if item_slug else uid
    return f"https://eats.yandex.com/uz/retail/{brand}/product/{tail}?placeSlug={slug}"


def normalize(item: dict, store: str, category: str, slug: str) -> dict:
    base = parse_price(item.get("price"))
    promo = parse_price(item.get("promoPrice"))
    price = promo or base
    old = base if (promo and base and base != promo) else None
    discount = round((old - price) * 100 / old) if (old and price) else None
    return {
        "source": "yandex_eats",
        "source_product_id": item.get("uid") or item.get("public_id"),
        "title_ru": item.get("name"),
        "title_uz": None,
        "title_en": None,
        "vendor_code": None,
        "category": category,
        "price": price,
        "old_price": old,
        "discount_percent": discount,
        "is_discount": bool(discount),
        "unit": item.get("weight"),
        "product_type": None,
        "cashback": None,
        "image_url": _picture_url(item),
        "product_url": _product_url(item, slug),
        "currency": "UZS",
        "city": "Tashkent",
        "in_stock": bool(item.get("available")) and (item.get("inStock") or 0) > 0,
        "store_label": store,
        "scraped_at": now_iso(),
    }


def fetch_store(slug: str, label: str, pause: float = 0.3) -> list[dict]:
    tree = _post({"slug": slug})
    categories = tree["payload"]["categories"]
    tops = [c for c in categories if c.get("parentId") is None]
    print(f"  [{slug}] категорий: {len(categories)} (верхних {len(tops)})")

    rows: list[dict] = []
    seen: set[str] = set()
    for top in tops:
        try:
            page = _post({"slug": slug, "category": top["id"]})
        except Exception as exc:
            print(f"    {top['name'][:30]}: ошибка {exc}")
            continue
        added = 0
        for sub in page["payload"].get("categories") or []:
            for item in sub.get("items") or []:
                uid = item.get("uid")
                if not uid or uid in seen or not item.get("price"):
                    continue
                seen.add(uid)
                rows.append(normalize(item, label, sub.get("name") or top["name"], slug))
                added += 1
        if added:
            print(f"    {top['name'][:34]:36} {added:>5}")
        polite_sleep(pause)
    return rows


def main() -> None:
    all_rows: list[dict] = []
    for slug, label in STORES.items():
        print(f"[yandex] {label} ...")
        rows = fetch_store(slug, label)
        print(f"  итого: {len(rows)} товаров")
        all_rows.extend(rows)

    path = save_json("yandex_sample.json", all_rows)
    discounted = sum(1 for r in all_rows if r["is_discount"])
    print(f"\n[yandex] готово — {len(all_rows)} товаров → {path}")
    print(f"[yandex]   со скидкой: {discounted}")
    for r in all_rows[:3]:
        old = f" (было {r['old_price']})" if r["old_price"] else ""
        print(f"   • {r['title_ru'][:52]} — {r['price']} сум{old}")


if __name__ == "__main__":
    main()
