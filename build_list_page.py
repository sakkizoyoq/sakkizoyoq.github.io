"""Собрать страницу-справочник «что мы умеем сравнивать».

Отвечает на вопрос Валерии: какие конкретно товары попадают в сравнение и почему
не все. Берёт готовые карточки из data/comparisons.json, раскладывает их по
человеческим категориям и выписывает списком.

Запуск:  python3 build_list_page.py
Итог:    site/spisok.html
"""
from __future__ import annotations

import collections
import html
import json
import re

# Категории — по названию товара, а не по рубрикам магазинов: у каждого магазина
# они свои («Хиты недели», «Топ-10 товаров»), человеку от них толку мало.
RULES = [
    ("Детское", r"детск|baby|pampers|huggies|nutrilak|растишка|агуша|подгузн|соск|"
                r"пюре|молочная смесь|фрутоняня|кашк|мамако|malysh|малыш"),
    ("Напитки", r"напиток|вода|сок|кола|cola|pepsi|sprite|fanta|квас|лимонад|морс|"
                r"energ|энерг|borjomi|chortoq|газиров|нектар"),
    ("Чай и кофе", r"\bчай\b|\bкофе\b|tess|greenfield|lipton|nescafe|jacobs|какао"),
    ("Молочное", r"молок|кефир|йогурт|сметан|творог|сыр\b|сливк|масло сливочн|ряженк|"
                 r"айран|простокваш"),
    ("Сладости", r"шоколад|конфет|печень|вафл|мармелад|зефир|пряник|торт|батончик|"
                 r"леденц|карамел|халва|круассан|kinder|nutella"),
    ("Снеки", r"чипс|сухар|орех|семечк|попкорн|снек|кириешк|фисташ|арахис"),
    ("Бакалея", r"мука|крупа|рис\b|гречк|макарон|спагетт|паста\b|сахар|соль|"
                r"масло подсолн|масло оливк|уксус|соус|кетчуп|майонез|специ|приправ|"
                r"консерв|тушен|горошек|кукуруз"),
    ("Гигиена и уход", r"шампун|гель для душа|мыло|зубн|прокладк|kotex|always|дезодор|"
                       r"крем\b|бальзам|лосьон|бритв|станок|ватн|салфетк влажн|nivea|"
                       r"dove|schauma|elseve|johnson"),
    ("Бытовая химия", r"порошок|кондиционер для бель|отбелив|чистящ|моющ|средство для|"
                      r"освежител|туалетн|мешк для мусор|губк|перчатк|fairy|tide|ariel|"
                      r"domestos|доместос|пемолюкс"),
    ("Дом и канцелярия", r"тетрад|альбом|ручк|карандаш|линейк|пенал|рюкзак|клей|ножниц|"
                         r"фломастер|краск|точилк|дневник|обложк"),
]

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
    ("Uzum Market", "uzum_sample.json", "выборка из «Продуктов питания»"),
]


def classify(name: str) -> str:
    low = (name or "").lower()
    for label, pattern in RULES:
        if re.search(pattern, low):
            return label
    return "Разное"


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
        groups[classify(card["name"])].append(card)

    order = [label for label, _ in RULES] + ["Разное"]
    order = [label for label in order if groups.get(label)]

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

    print(f"Готово: site/spisok.html")
    print(f"  товаров в базе: {total_rows}")
    print(f"  сравнений: {len(cards)} (разные сети: {cross})")
    for label in order:
        print(f"    {label:<20} {len(groups[label]):>4}")


if __name__ == "__main__":
    main()
