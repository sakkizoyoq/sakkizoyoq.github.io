"""Scraper for Uzum Market (uzum.uz), Tashkent — full grocery assortment.

Uzum's website talks to a GraphQL API at https://graphql.uzum.uz/. The catalog
("makeSearch") is public but requires a *guest* bearer token that Uzum ID issues
to anonymous visitors, plus Apollo client headers and the city (Tashkent = 1).

    POST https://graphql.uzum.uz/   operationName MakeSearch_ItemsAndFilters
    variables.queryInput = { categoryId, pagination:{offset,limit}, ... }
    -> data.makeSearch.total
       data.makeSearch.items[].catalogCard.discovery {
           title, feedback{rating,quantity},
           priceBlock{ sellPrice{amount}, fullPrice{amount} },
           photos{ link(trans:SIZE_540){high} },
           ...on DiscoverySkuCard { id productId }
       }

TOKEN NOTE: the guest token expires in ~3 hours. It is now fetched automatically
by scrapers.uzum_auth (POST https://id.uzum.uz/api/auth/token) and cached until
it is about to expire. Setting UZUM_TOKEN in the environment still overrides it.

    python3 -m scrapers.uzum
"""
from __future__ import annotations

import gzip
import json
import urllib.request

from scrapers.common import now_iso, parse_price, save_json, polite_sleep
from scrapers.uzum_auth import get_guest_token

SOURCE = "uzum"
GRAPHQL_URL = "https://graphql.uzum.uz/"

# Tashkent
CITY_ID = "1"
CITY_LAT, CITY_LON = "41.311151", "69.279737"

QUERY = """
query Cat($queryInput: MakeSearchQueryInput!) {
  makeSearch(query: $queryInput) {
    total
    items {
      catalogCard {
        __typename
        discovery {
          title
          feedback { rating quantity }
          priceBlock { sellPrice { amount } fullPrice { amount } }
          photos { link(trans: SIZE_540) { high } }
          ... on DiscoverySkuCard { id productId }
          ... on DiscoverySkuGroupCard { id productId }
          ... on DiscoveryProductCard { id }
        }
      }
    }
  }
}
"""

# Категории Uzum, которые пересекаются с продуктовой корзиной. Дерево категорий
# лежит у них на сайте в localStorage («categories»), оттуда и взяты номера.
# Берём подкатегории, а не корни: у корня выдача обрывается на первых сотнях.
GROCERY_CATEGORIES = {
    # Продукты питания
    "2478": "Чай, кофе и какао",
    "2475": "Масла, соусы и приправы",
    "2483": "Выпечка и сладости",
    "14340": "Консервация",
    "15476": "Макароны, крупы и сухие завтраки",
    "2480": "Вода, соки, напитки",
    "15477": "Мука, сахар и соль",
    "2476": "Снеки, орехи и семечки",
    "1913": "Здоровое питание",
    "328": "Мед, варенье, сладкая консервация",
    "87": "Продукты для выпечки и десертов",
    "17846": "Мясо, птица и мясные продукты",
    "17280": "Яйца, молоко и молочные продукты",
    # Бытовая химия
    "11341": "Чистящие и моющие средства",
    "11011": "Освежители и нейтрализаторы",
    "10524": "Средства для стирки",
    "11083": "Средства для посудомоечных машин",
    "17845": "Бумажная продукция",
    # Гигиена и уход
    "66": "Личная гигиена",
    "10165": "Уход за волосами",
    "10070": "Уход за телом",
    "10137": "Уход за лицом",
    # Детское
    "14285": "Детское питание",
    "10064": "Гигиена и подгузники",
    # Дом и школа
    "10110": "Хозяйственные товары",
    "14369": "Товары для школы и обучения",
    "11477": "Письменные принадлежности",
}

# Сколько товаров тянуть из одной категории.
PER_CATEGORY = 500


def _headers() -> dict:
    token, iid = get_guest_token()
    return {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Accept-Encoding": "gzip",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        "Accept-Language": "ru-RU",
        "apollographql-client-name": "web-customers",
        "apollographql-client-version": "1.63.2",
        "x-iid": iid,
        "city-id": CITY_ID,
        "city-latitude": CITY_LAT,
        "city-longitude": CITY_LON,
        "Authorization": "Bearer " + token,
    }


def _post(category_id: str, offset: int, limit: int) -> dict:
    payload = {
        "operationName": "Cat",
        "query": QUERY,
        "variables": {"queryInput": {
            "categoryId": category_id,
            "showAdultContent": "NONE",
            "filters": [],
            "sort": "BY_RELEVANCE_DESC",
            "pagination": {"offset": offset, "limit": limit},
            "correctQuery": False,
        }},
    }
    req = urllib.request.Request(GRAPHQL_URL, data=json.dumps(payload).encode(), headers=_headers())
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    data = json.loads(raw.decode())
    if data.get("errors"):
        raise RuntimeError(json.dumps(data["errors"], ensure_ascii=False)[:300])
    return data["data"]["makeSearch"]


def normalize(card: dict, category_title: str) -> dict | None:
    d = (card or {}).get("discovery") or {}
    if not d.get("title"):
        return None
    pb = d.get("priceBlock") or {}
    sell = (pb.get("sellPrice") or {}).get("amount")
    full = (pb.get("fullPrice") or {}).get("amount")
    price = parse_price(sell)
    old = parse_price(full)
    discount = None
    if price and old and old > price:
        discount = round((old - price) * 100 / old)
    photos = d.get("photos") or []
    image = None
    if photos:
        image = ((photos[0].get("link") or {}).get("high"))
    fb = d.get("feedback") or {}
    pid = d.get("productId") or d.get("id")
    return {
        "source": SOURCE,
        "source_product_id": pid,
        "title_ru": d.get("title"),
        "title_uz": None,
        "title_en": None,
        "vendor_code": None,
        "category": category_title,
        "price": price,
        "old_price": old if (old and old != price) else None,
        "discount_percent": discount,
        "is_discount": bool(discount),
        "unit": None,
        "product_type": None,
        "cashback": None,
        "image_url": image,
        "product_url": f"https://uzum.uz/ru/product/{pid}" if pid else None,
        "currency": "UZS",
        "city": "Tashkent",
        "in_stock": True,
        "rating": fb.get("rating"),
        "reviews": fb.get("quantity"),
        "scraped_at": now_iso(),
    }


def fetch_category(category_id: str, title: str, max_products: int = PER_CATEGORY) -> list[dict]:
    out: list[dict] = []
    offset, limit = 0, 48
    total = None
    while offset < max_products:
        try:
            page = _post(category_id, offset, limit)
        except Exception as exc:
            print(f"     ошибка на offset {offset}: {exc}")
            break
        if total is None:
            total = page.get("total")
        items = page.get("items") or []
        if not items:
            break
        for it in items:
            row = normalize(it.get("catalogCard"), title)
            if row:
                out.append(row)
        offset += limit
        polite_sleep(0.5)
    return out


def main() -> None:
    all_rows: list[dict] = []
    seen: set = set()
    for cid, title in GROCERY_CATEGORIES.items():
        rows = fetch_category(cid, title)
        # один и тот же товар лежит сразу в нескольких категориях — убираем повторы
        fresh = [r for r in rows if r["source_product_id"] not in seen]
        seen.update(r["source_product_id"] for r in fresh)
        print(f"[{SOURCE}] {title:38} {len(fresh):>5}")
        all_rows.extend(fresh)

    path = save_json(f"{SOURCE}_sample.json", all_rows)
    discounted = sum(1 for p in all_rows if p["is_discount"])
    print(f"\n[{SOURCE}] готово — {len(all_rows)} товаров → {path}  (со скидкой: {discounted})")
    for p in all_rows[:3]:
        old = f" (было {p['old_price']})" if p["old_price"] else ""
        print(f"   • {p['title_ru'][:60]} — {p['price']} {p['currency']}{old}")


if __name__ == "__main__":
    main()
