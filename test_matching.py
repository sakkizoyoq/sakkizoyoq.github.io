"""Проверки склейщика товаров.

Каждая строка — реальная пара названий из наших выгрузок. Пары, которые
однажды склеились неправильно, остаются здесь навсегда: так ошибка не вернётся
после следующей правки.

Запуск:  python3 test_matching.py
"""
from matching import THRESHOLD, score

# Должны совпасть — это один и тот же товар
SAME = [
    ("Кофе растворимый Jacobs Monarch, 75 г", "Kofe jacobs monarch 75gr m/u"),
    ("Минеральная вода Borjomi, пластиковая бутылка, 1,25 л", "Вода минеральная Borjomi 1.25 л"),
    ("Рис Лазер Хорезм Oila tanlovi, 900 г", "Рис Oila tanlovi лазер Хорезм М 900 г"),
    ("Килька в томатном соусе Brivais vilnis, 240 г", "Kilka brivais vilins v tomat. sous.240gr"),
    ("Мука пшеничная Алтын Дан 95, 1 сорт, 2 кг", "Muka pshen. altin dan 95 1/s 2kg"),
    ("Гель для стирки Persil, 1.04 л", "Gel d. stirki persil sov gel 1.04l"),
    ("Детское печенье Бегемотик Бонди, обогащённое кальцием, 180 г",
     "Печенье детское Бегемотик Бонди с кальцием 180 г"),
    ("Чай зеленый Tudor, 100 г", "Чай зеленый Tudor 100 г"),
    ("Драже TIC TAC Мята 49 г", "Драже Tic Tac мята 49 г"),
    ("Пюре Растишка яблоко груша 85 г", "Pyure rastishka yabloko grusha 85gr"),
    ("Шампунь Johnson's Baby, 200 мл", "Shampun johnson's baby 200ml"),
    ("Газированный напиток Coca Cola Vanilla 0,33 л ж/б",
     'Газированный напиток "Coca-Cola Vanilla", 0.33л'),
]

# Не должны совпасть — это разные товары
DIFFERENT = [
    # разные вкусы при том же бренде и объёме
    ("Средство для мытья посуды Fairy Лимон, 500 мл",
     "Средство для мытья посуды Fairy Апельсин 500 мл"),
    ("Мороженое Grand с шоколадной глазурью", "Мороженое Grand со сгущёнкой"),
    # «Extra Virgin» — не бренд, производители разные
    ("Оливковое масло Picasso Extra Virgin, 250 мл",
     "Масло оливковое Italiano Extra Virgin 250 мл"),
    # разные объёмы и упаковки
    ("Напиток Coca-Cola 0,33 л", "Напиток Coca-Cola 0.33 л, 12 шт"),
    ("Напиток Pepsi 1,5 л", "Напиток Pepsi 0,5 л"),
    # разные ступени детского питания
    ("Смесь Nutrilak Premium 4", "Смесь Nutrilak Premium №3"),
    # канцтовары с разным числом листов
    ("Тетрадь в клетку, 48 листов", "Тетрадь в клетку, 12 листов"),
    # разные бренды
    ("Шампунь Elseve Ультра Прочность, 250 мл", "Шампунь Schauma Ультра Прочность, 250 мл"),
    # разные фрукты
    ("Груша Конференция, вес", "Banan ekvador ves"),
]


def main() -> int:
    failed = []
    for a, b in SAME:
        s, why = score(a, b)
        if s < THRESHOLD:
            failed.append(("должны были совпасть", a, b, s, why))
    for a, b in DIFFERENT:
        s, why = score(a, b)
        if s >= THRESHOLD:
            failed.append(("не должны были совпасть", a, b, s, why))

    total = len(SAME) + len(DIFFERENT)
    print(f"проверок: {total}, прошло: {total - len(failed)}")
    for kind, a, b, s, why in failed:
        print(f"\n  ОШИБКА ({kind}, оценка {s:.2f}) {why}")
        print(f"    A: {a}")
        print(f"    B: {b}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
