"""Собрать карточки «где дешевле» по трём магазинам.

Как это работает:
  1. берём акционные товары Korzinka и Makro;
  2. сначала сопоставляем их между собой (это быстро, всё локально);
  3. затем по каждому товару ищем пару в Uzum Market через их поиск;
  4. собираем карточки, где один и тот же товар есть минимум в двух магазинах.

Сопоставлением занимается matching.py — он намеренно строгий: лучше показать
меньше карточек, чем сравнить литровую бутылку с упаковкой из шести.

Запуск:  python3 build_comparisons.py
Итог:    data/comparisons.json
"""
from __future__ import annotations

import gzip
import json
import os
import re
import time
import urllib.request

from categories import classify
from matching import (THRESHOLD, extract_brands, extract_size, score, unit_price)
from translit import is_transliterated, skeleton
from scrapers.common import save_json
from scrapers.uzum import GRAPHQL_URL, _headers

SEARCH_QUERY = """
query S($q: MakeSearchQueryInput!) {
  makeSearch(query: $q) {
    items {
      catalogCard {
        discovery {
          title
          priceBlock { sellPrice { amount } fullPrice { amount } }
          photos { link(trans: SIZE_540) { high } }
          ... on DiscoverySkuCard { productId }
          ... on DiscoverySkuGroupCard { productId }
        }
      }
    }
  }
}
"""

_JUNK = re.compile(r"[^\w\s%.,]|_", re.UNICODE)


def build_query(title: str, unit: str | None) -> str:
    text = _JUNK.sub(" ", title or "")
    text = re.sub(r"\s+", " ", text).strip()
    words = [w for w in text.split() if len(w) > 1][:6]
    q = " ".join(words)
    size = extract_size(title, unit)
    if size and not re.search(r"\d", q):
        q += f" {int(size[1])}"
    return q[:90]


def uzum_search(text: str, limit: int = 10) -> list[dict]:
    payload = {
        "operationName": "S",
        "query": SEARCH_QUERY,
        "variables": {"q": {
            "text": text, "showAdultContent": "NONE", "filters": [],
            "sort": "BY_RELEVANCE_DESC",
            "pagination": {"offset": 0, "limit": limit},
            "correctQuery": True,
        }},
    }
    req = urllib.request.Request(GRAPHQL_URL, data=json.dumps(payload).encode(), headers=_headers())
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    data = json.loads(raw.decode())
    if data.get("errors"):
        return []
    out = []
    for item in data["data"]["makeSearch"]["items"]:
        d = (item.get("catalogCard") or {}).get("discovery") or {}
        pb = d.get("priceBlock") or {}
        price = (pb.get("sellPrice") or {}).get("amount")
        if not d.get("title") or not price:
            continue
        photos = d.get("photos") or []
        out.append({
            "store": "Uzum Market",
            "title": d["title"],
            "price": price,
            "old_price": (pb.get("fullPrice") or {}).get("amount"),
            "unit": None,
            "image": (photos[0]["link"]["high"] if photos else None),
            "url": f"https://uzum.uz/ru/product/{d.get('productId')}",
        })
    return out


def load_store(filename: str, store: str | None = None) -> list[dict]:
    """Загрузить выгрузку магазина. Если store не задан — берём метку из товара
    (в файле Яндекса лежат сразу несколько магазинов)."""
    path = f"data/{filename}"
    if not os.path.exists(path):
        return []
    rows = json.load(open(path, encoding="utf-8"))
    return [{
        "store": store or r.get("store_label") or "?",
        "title": r["title_ru"],
        "price": r["price"],
        "old_price": r.get("old_price"),
        "unit": r.get("unit"),
        "image": r.get("image_url"),
        "url": r.get("product_url"),
        "promo_end": r.get("promo_end"),
    } for r in rows if r.get("price") and r.get("title_ru")]


def merge_store(groups: list[dict], items: list[dict]) -> list[dict]:
    """Добавить товары ещё одного магазина к уже собранным группам.

    Группа — это один и тот же товар в разных магазинах. Каждый товар может
    попасть только в одну группу, и в группе не бывает двух товаров из одного
    магазина. Сначала разбираем самые уверенные совпадения.
    """
    scored = []
    for j, item in enumerate(items):
        for gi, g in enumerate(groups):
            if any(x["store"] == item["store"] for x in g["items"]):
                continue
            s = min(score(x["title"], item["title"], x.get("unit"), item.get("unit"))[0]
                    for x in g["items"])
            if s >= THRESHOLD:
                scored.append((s, gi, j))

    used_items: set[int] = set()
    for s, gi, j in sorted(scored, key=lambda t: -t[0]):
        if j in used_items:
            continue
        g = groups[gi]
        if any(x["store"] == items[j]["store"] for x in g["items"]):
            continue
        g["items"].append(items[j])
        g["confidence"] = min(g["confidence"], s)
        used_items.add(j)

    for j, item in enumerate(items):
        if j not in used_items:
            groups.append({"items": [item], "confidence": 1.0})
    return groups


# ---------------------------------------------------------------------------
# Быстрое сопоставление больших каталогов
#
# У Uzum больше 11 000 товаров, у доставки Makro — 3 000. Сверять каждый с
# каждым это 35 миллионов сравнений, на что уходят часы. Поэтому сначала
# отбираем кандидатов по общему слову в названии («шампунь», «rastishka»),
# а тяжёлую проверку запускаем только для них.
#
# Слова приводим к «скелету» — так «шампунь» и «shampun» становятся одним
# словом. Слишком частые слова (вроде «для») в отбор не берём: они дают в
# кандидаты пол-каталога и смысл теряется.
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
BLOCK_PREFIX = 5          # сравниваем первые 5 букв скелета
MAX_TOKEN_SHARE = 0.06    # слово, встречающееся чаще, чем в 6% групп, — бесполезно


def block_tokens(title: str) -> set[str]:
    out = set()
    for word in _WORD_RE.findall((title or "").lower()):
        if len(word) < 4:
            continue
        s = skeleton(word)
        if len(s) >= 4:
            out.add(s[:BLOCK_PREFIX])
    return out


def merge_store_fast(groups: list[dict], items: list[dict], verbose: bool = True) -> list[dict]:
    """То же, что merge_store, но с предварительным отбором кандидатов."""
    index: dict[str, set[int]] = {}
    for gi, g in enumerate(groups):
        for x in g["items"]:
            for tok in block_tokens(x["title"]):
                index.setdefault(tok, set()).add(gi)

    limit = max(40, int(len(groups) * MAX_TOKEN_SHARE))
    useful = {tok: gis for tok, gis in index.items() if len(gis) <= limit}
    if verbose:
        print(f"     слов для отбора: {len(useful)} из {len(index)} "
              f"(отброшены слишком частые)")

    scored = []
    checked = 0
    for j, item in enumerate(items):
        candidates: set[int] = set()
        for tok in block_tokens(item["title"]):
            candidates |= useful.get(tok, set())
        for gi in candidates:
            g = groups[gi]
            if any(x["store"] == item["store"] for x in g["items"]):
                continue
            checked += 1
            s = min(score(x["title"], item["title"], x.get("unit"), item.get("unit"))[0]
                    for x in g["items"])
            if s >= THRESHOLD:
                scored.append((s, gi, j))
    if verbose:
        print(f"     проверено пар: {checked:,}".replace(",", " "))

    used_items: set[int] = set()
    for s, gi, j in sorted(scored, key=lambda t: -t[0]):
        if j in used_items:
            continue
        g = groups[gi]
        if any(x["store"] == items[j]["store"] for x in g["items"]):
            continue
        g["items"].append(items[j])
        g["confidence"] = min(g["confidence"], s)
        used_items.add(j)

    for j, item in enumerate(items):
        if j not in used_items:
            groups.append({"items": [item], "confidence": 1.0})
    return groups


# Картинки берём не у кого попало: у Makro на сайте файлы перепутаны — по коду
# макарон лежит фотография колбасы. Проверено на их же API, так что чиним у себя:
# сначала спрашиваем те источники, где картинки совпадают с товаром.
IMAGE_PRIORITY = ["Uzum Market", "Korzinka", "Safia (Яндекс)", "Makro (Яндекс)", "Makro"]


def pick_image(items: list[dict]) -> str | None:
    def rank(item: dict) -> int:
        try:
            return IMAGE_PRIORITY.index(item["store"])
        except ValueError:
            return len(IMAGE_PRIORITY)
    for item in sorted(items, key=rank):
        if item.get("image"):
            return item["image"]
    return None


_ABBREV_RE = re.compile(r"[а-яёa-z]{1,7}\.", re.I)      # «Кондиц.», «д.», «масл.»
_GLUED_RE = re.compile(r"[а-яёa-z](?=\d)", re.I)        # «арганы760мл»
_CAPS_RE = re.compile(r"\b[А-ЯЁA-Z]{4,}\b")             # «НАПИТОК COCA COLA»
_ODD_RE = re.compile(r"[^\w\s%.,°'\"/()+-]", re.UNICODE)  # эмодзи и мусор


def readability(title: str) -> float:
    """Насколько название пригодно для показа человеку.

    Магазины пишут в кассовом стиле: «Кондиц.д.белья Tesori с масл.арганы760мл».
    Из нескольких названий одного товара выбираем то, где меньше сокращений,
    слипшихся слов и КАПСА, а больше нормальных слов.
    """
    if not title:
        return -99
    score = 0.0
    score -= 3.0 * len(_ABBREV_RE.findall(title))
    score -= 2.0 * len(_GLUED_RE.findall(title))
    score -= 1.5 * len(_CAPS_RE.findall(title))
    score -= 2.0 * len(_ODD_RE.findall(title))
    score -= 2.0 * title.count("_")
    score += 0.6 * len([w for w in title.split() if len(w) > 2])
    if len(title) > 85:                       # слишком длинные тоже неудобны
        score -= (len(title) - 85) / 20
    return score


def clean_title(title: str) -> str:
    """Убрать мусор, который попадается в кассовых названиях."""
    t = (title or "").replace("_", " ")
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s+([,.;])", r"\1", t)
    return t.strip(" ,.;-*")


def format_size(size: tuple[str, float] | None) -> str | None:
    """«250 г», «1,5 л», «16 шт» — из разобранного размера, а не из чужого поля."""
    if not size:
        return None
    kind, value = size
    if kind == "g":
        return f"{value / 1000:g} кг".replace(".", ",") if value >= 1000 else f"{value:g} г"
    if kind == "ml":
        return f"{value / 1000:g} л".replace(".", ",") if value >= 1000 else f"{value:g} мл"
    if kind == "pcs":
        return f"{value:g} шт"
    if kind == "sheets":
        return f"{value:g} листов"
    return None


def make_card(items: list[dict], confidence: float) -> dict:
    stores = sorted(items, key=lambda s: s["price"])
    for s in stores:
        up = unit_price(s["price"], s["title"], s.get("unit"))
        if up:
            s["unit_price"], s["unit_label"] = up
    best, worst = stores[0], stores[-1]
    ref = max(items, key=lambda s: len(s["title"] or ""))
    size = extract_size(ref["title"], ref.get("unit"))
    brands = set()
    for s in items:
        brands |= extract_brands(s["title"])
    # Для заголовка карточки берём русское название: латинское «John. baby
    # shampun 200ml» из Яндекс Еды человеку читать неудобно.
    readable = [s for s in items if not is_transliterated(s["title"])] or items
    name = clean_title(max(readable, key=lambda s: readability(s["title"]))["title"])
    return {
        "name": name,
        "category": classify(name),
        "unit": format_size(size) or next((s.get("unit") for s in items if s.get("unit")), None),
        "size": {"kind": size[0], "value": size[1]} if size else None,
        "brands": sorted(brands),
        "confidence": round(confidence, 2),
        "image": pick_image(items),
        "promo_end": next((s.get("promo_end") for s in items if s.get("promo_end")), None),
        "stores": [{k: v for k, v in s.items() if k != "promo_end"} for s in stores],
        "savings": worst["price"] - best["price"],
        "savings_percent": round((worst["price"] - best["price"]) * 100 / worst["price"]),
    }


def main(pause: float = 0.3, uzum_limit: int = 900) -> None:
    sources = [
        ("korzinka_sample.json", "Korzinka"),
        ("makro_sample.json", "Makro"),
        ("yandex_sample.json", None),      # метка магазина лежит в самих товарах
    ]

    print("Шаг 1 — сопоставляю магазины между собой...")
    t0 = time.time()
    groups: list[dict] = []
    for filename, label in sources:
        items = load_store(filename, label)
        if not items:
            print(f"  {filename}: нет данных, пропускаю")
            continue
        before = len(groups)
        groups = merge_store(groups, items)
        joined = before + len(items) - len(groups)
        by_store = {}
        for it in items:
            by_store[it["store"]] = by_store.get(it["store"], 0) + 1
        for st, n in by_store.items():
            print(f"  {st:22} {n:>5} товаров")
        if before:
            print(f"     └─ присоединилось к уже найденным: {joined}")
    print(f"  групп получилось: {len(groups)}  ({time.time() - t0:.0f} сек)")

    # Скачанный каталог Uzum подмешиваем сразу: так товар из доставки Makro
    # может встретиться с тем же товаром в Uzum, чего поиск по одним только
    # акциям никогда бы не нашёл.
    uzum_items = load_store("uzum_sample.json", "Uzum Market")
    if uzum_items:
        print(f"\nШаг 2 — подмешиваю каталог Uzum ({len(uzum_items)} товаров)...")
        t1 = time.time()
        before = len(groups)
        groups = merge_store_fast(groups, uzum_items)
        joined = before + len(uzum_items) - len(groups)
        print(f"     присоединилось к уже найденным: {joined}  ({time.time() - t1:.0f} сек)")

    # Оставшиеся акционные товары без цены Uzum добираем поиском по их сайту:
    # там есть и то, что не попало в скачанные категории.
    priority = [g for g in groups
                if any(x["store"] in ("Korzinka", "Makro") for x in g["items"])
                and not any(x["store"] == "Uzum Market" for x in g["items"])]
    targets = priority[:uzum_limit]
    print(f"\nШаг 3 — доискиваю остальное в поиске Uzum ({len(targets)} запросов)...")
    added, errors = 0, 0
    for n, g in enumerate(targets, 1):
        # Искать в Uzum нужно по русскому названию: латиница из Яндекс Еды
        # («Pyure rastishka») их поиску ничего не скажет.
        cyrillic = [x for x in g["items"] if not is_transliterated(x["title"])]
        ref = max(cyrillic or g["items"], key=lambda s: len(s["title"] or ""))
        try:
            candidates = uzum_search(build_query(ref["title"], ref.get("unit")))
        except Exception:
            errors += 1
            time.sleep(1.0)
            continue
        best, best_s = None, 0.0
        for c in candidates:
            s = min(score(it["title"], c["title"], it.get("unit"), None)[0] for it in g["items"])
            if s > best_s:
                best, best_s = c, s
        if best and best_s >= THRESHOLD:
            g["items"].append(best)
            g["confidence"] = min(g["confidence"], best_s)
            added += 1
        if n % 100 == 0:
            print(f"  ...{n}/{len(targets)} — добавлено цен Uzum: {added}")
        time.sleep(pause)
    print(f"  найдено в Uzum: {added} (ошибок запроса: {errors})")

    cards = [make_card(g["items"], g["confidence"]) for g in groups if len(g["items"]) >= 2]
    cards.sort(key=lambda c: (-len(c["stores"]), -c["confidence"], -c["savings_percent"]))
    path = save_json("comparisons.json", cards)

    three = sum(1 for c in cards if len(c["stores"]) >= 3)
    print(f"\nГотово: {len(cards)} карточек сравнения ({three} — сразу по трём магазинам)")
    print(f"Файл: {path}\n")
    for c in cards[:12]:
        line = "  ".join(f"{s['store']} {s['price']}" for s in c["stores"])
        print(f"  [{c['confidence']:.2f}] {c['name'][:44]}")
        print(f"        {line}   (−{c['savings_percent']}%)")


if __name__ == "__main__":
    main()
