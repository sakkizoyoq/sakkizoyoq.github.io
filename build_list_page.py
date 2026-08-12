"""Собрать страницу-справочник «что мы умеем сравнивать».

Отвечает на вопрос Валерии: какие конкретно товары попадают в сравнение и почему
не все. Берёт готовые карточки из data/comparisons.json, раскладывает их по
человеческим категориям и выписывает списком.

Запуск:  python3 build_list_page.py
Итог:    site/spisok.html
"""
from __future__ import annotations

import collections
import json

from categories import ORDER, OTHER, classify
from publish import publish

STORE_COLOR = {
    "Korzinka": "#e11d48",
    "Makro": "#16a34a",
    "Makro (Яндекс)": "#f5b301",
    "Uzum Market": "#7b3ff2",
}

SOURCES = [
    ("Korzinka", "korzinka_sample.json", "только товары по акции"),
    ("Makro", "makro_sample.json", "только товары по акции"),
    ("Makro (Яндекс)", "yandex_sample.json", "весь каталог доставки"),
    ("Uzum Market", "uzum_sample.json", "27 категорий: еда, химия, гигиена"),
]


def is_cross_network(card: dict) -> bool:
    """Считаем сети, а не источники: магазин Makro и доставка Makro — одна сеть."""
    return len({s["store"].replace(" (Яндекс)", "") for s in card["stores"]}) >= 2


def fmt(n) -> str:
    return f"{int(n):,}".replace(",", " ") if n else "—"


def main() -> None:
    cards = json.load(open("data/comparisons.json", encoding="utf-8"))

    counts = []
    for label, filename, kind in SOURCES:
        rows = json.load(open(f"data/{filename}", encoding="utf-8"))
        counts.append((label, len(rows), kind))
    total_rows = sum(c[1] for c in counts)

    groups: dict[str, list] = collections.defaultdict(list)
    for card in cards:
        groups[card.get("category") or classify(card["name"])].append(card)

    order = [label for label in ORDER if groups.get(label)]

    cross = sum(1 for c in cards if is_cross_network(c))

    payload = {
        "sources": counts,
        "totalRows": total_rows,
        "cards": len(cards),
        "cross": cross,
        "groups": [{
            "name": label,
            "items": [{
                "name": c["name"],
                "unit": c.get("unit"),
                "cross": is_cross_network(c),
                "save": c["savings_percent"],
                "stores": [{
                    "store": s["store"],
                    "price": s["price"],
                    "url": s.get("url"),
                } for s in sorted(c["stores"], key=lambda s: s["price"])],
            } for c in sorted(groups[label], key=lambda c: -c["savings_percent"])],
        } for label in order],
        "colors": STORE_COLOR,
    }

    template = open("site/spisok.template.html", encoding="utf-8").read()
    out = template.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    open("site/spisok.html", "w", encoding="utf-8").write(out)
    publish("site/spisok.html")

    print(f"Готово: site/spisok.html")
    print(f"  товаров в базе: {total_rows}")
    print(f"  сравнений: {len(cards)} (разные сети: {cross})")
    for label in order:
        print(f"    {label:<20} {len(groups[label]):>4}")


if __name__ == "__main__":
    main()
