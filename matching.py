"""Движок сопоставления товаров между магазинами (ядро модели «где дешевле»).

Задача: понять, что «Уксус столовый 9% 365 kun 230мл» из Korzinka и
«Уксус Столовый 9% 230 мл» из Uzum — это один и тот же товар, а
«Напиток Sprite 1,5л» и «Sprite 1.5 л * 6 шт» — РАЗНЫЕ товары.

Штрих-кодов у нас нет (Korzinka их не отдаёт), поэтому решение принимается по
названию. Логика намеренно «строгая»: лучше пропустить настоящее совпадение,
чем показать человеку неверное сравнение — неверное сравнение разрушает доверие.

Правила (в порядке применения):
  1. РАЗМЕР. Извлекаем объём/вес и приводим к базовым единицам (г / мл / шт).
     Если размеры известны у обоих и не совпадают — это разные товары. Отказ.
  2. УПАКОВКА. «[6]», «* 6 шт», «х6» — количество в наборе. Не совпало — отказ.
  3. БРЕНД. Латинские слова (Nivea, Alpen Gold, Sprite) — сильный признак.
     Если латиница есть у обоих, но не пересекается — отказ.
  4. СЛОВА. Считаем долю общих значимых слов (коэффициент Жаккара).
     Плюс бонус за совпавший бренд и размер.

Итог — оценка 0..1 и решение match / no-match по порогу.
"""
from __future__ import annotations

import re
import unicodedata

from translit import is_transliterated, same_word, skeleton

# Слова, которые ничего не говорят о товаре
STOP = {
    "и", "в", "с", "на", "для", "за", "по", "от", "из", "не", "или", "the", "a",
    "шт", "штук", "уп", "пач", "пак", "бут", "банка", "ж", "б", "пэт", "п",
    "цена", "вес", "весовой", "новинка", "акция", "хит",
}

# Латинские слова, которые пишут все подряд. Брендом их считать нельзя:
# из-за «Extra Virgin» оливковое масло Picasso однажды склеилось с Italiano —
# «общий бренд» нашёлся, хотя производители разные.
WEAK_BRAND = {
    "extra", "virgin", "classic", "classico", "original", "premium", "gold",
    "silver", "light", "lite", "max", "maxi", "mini", "plus", "pro", "ultra",
    "super", "natural", "nature", "fresh", "soft", "care", "active", "sensitive",
    "family", "home", "style", "new", "special", "select", "quality", "expert",
    "juice", "drink", "milk", "food", "kids", "baby", "junior", "sport", "fit",
    "eco", "bio", "organic", "green", "black", "white", "red", "blue",
}

# г / мл / шт — базовые единицы, к которым всё приводим
UNIT_TO_BASE = {
    "кг": ("g", 1000), "kg": ("g", 1000),
    "г": ("g", 1), "гр": ("g", 1), "g": ("g", 1), "гб": ("g", 1),
    "мг": ("g", 0.001),
    "л": ("ml", 1000), "l": ("ml", 1000), "литр": ("ml", 1000),
    "мл": ("ml", 1), "ml": ("ml", 1),
    # латинские написания — так пишет Яндекс Еда: «85gr», «1,5l», «250ml»
    "gr": ("g", 1), "gm": ("g", 1), "mg": ("g", 0.001), "lt": ("ml", 1000),
    "шт": ("pcs", 1), "штук": ("pcs", 1), "штуки": ("pcs", 1), "штука": ("pcs", 1),
    "дана": ("pcs", 1), "pcs": ("pcs", 1), "sht": ("pcs", 1), "dona": ("pcs", 1),
    # канцтовары: тетрадь на 96 листов и на 12 листов — разные товары
    "лист": ("sheets", 1), "листа": ("sheets", 1), "листов": ("sheets", 1),
}

_SIZE_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*("
    r"кг|kg|гр|gr|gm|мг|mg|г|g|мл|ml|литр|лт|lt|л|l|"
    r"штуки|штука|штук|шт|sht|дана|dona|листов|листа|лист"
    r")\b",
    re.I,
)
_PACK_RE = re.compile(r"(?:\[(\d+)\]|[*xх×]\s*(\d+)\s*(?:шт|дана)|(\d+)\s*(?:шт|дана)\s*[*xх×])", re.I)
_LATIN_RE = re.compile(r"[a-z][a-z0-9\-']{2,}", re.I)
_PERCENT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")


def _clean(text: str) -> str:
    """Нижний регистр + снятие диакритики, чтобы «NESTLÉ» == «Nestle»."""
    # «№» при нормализации превращается в «no» и слипается с цифрой («№3» → «no3»),
    # поэтому убираем знак заранее.
    text = (text or "").replace("№", " ")
    text = unicodedata.normalize("NFKD", text.lower())
    # убираем надстрочные знаки (é -> e), но бережём кириллицу
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("ё", "е")
    # «120±5г» — допуск веса, а не размер: выкидываем «±5»
    return re.sub(r"[±+]\s*\d+(?:[.,]\d+)?", " ", text)


def extract_size(title: str, unit_hint: str | None = None) -> tuple[str, float] | None:
    """Вернуть ('g'|'ml'|'pcs', величина) — размер товара в базовых единицах."""
    for source in (title, unit_hint or ""):
        for raw, unit in _SIZE_RE.findall(_clean(source)):
            base, mult = UNIT_TO_BASE[unit.lower()]
            value = float(raw.replace(",", ".")) * mult
            if value > 0:
                return base, round(value, 3)
    return None


_COUNT_RE = re.compile(r"(\d+)\s*(?:штуки|штука|штук|шт|дана)\b", re.I)
# Артикул/модель: отдельное «слово» с 4+ цифрами (742537, E0530, 0522)
_ARTICLE_RE = re.compile(r"\b(?=[a-zа-я]*\d)[a-zа-я]*\d[a-zа-я0-9]*\b", re.I)


def extract_articles(title: str) -> set[str]:
    """Артикулы и номера моделей — если они разные, это разные товары."""
    out = set()
    for tok in _ARTICLE_RE.findall(_clean(title)):
        digits = "".join(c for c in tok if c.isdigit())
        if len(digits) >= 4:
            out.add(digits)
    return out


def extract_pack(title: str) -> int | None:
    """Сколько единиц в наборе: «[6]», «* 6 шт» → 6.

    Отдельный случай — «0,33 л, 12 шт»: если в названии уже есть объём или вес,
    то «12 шт» означает набор из 12 банок, а не размер товара. А вот в «Тампоны
    Kotex мини 16шт» количество — это и есть размер упаковки, набором не считаем.
    """
    text = _clean(title)
    m = _PACK_RE.search(text)
    if m:
        for g in m.groups():
            if g:
                n = int(g)
                return n if 1 < n <= 60 else None

    size = extract_size(title)
    if size and size[0] in ("g", "ml", "sheets"):
        c = _COUNT_RE.search(text)
        if c:
            n = int(c.group(1))
            if 1 < n <= 60:
                return n
    return None


_STEP_RE = re.compile(r"(?:№\s*|\bступень\s*|\bstep\s*)?\b([1-9]|1[0-2])\b(?!\s*(?:кг|kg|гр|г|g|мг|мл|ml|л|l|шт|штук|дана|листов|лист|%|х|x|\*))",
                      re.I)


def extract_step(title: str) -> int | None:
    """Номер ступени/варианта: «Nutrilak 4» и «Nutrilak №3» — разные товары.

    Берём только отдельно стоящие небольшие числа, не являющиеся размером
    («200 мл», «6 шт») и не частью артикула.
    """
    text = _clean(title)
    text = _SIZE_RE.sub(" ", text)          # убрать размеры
    text = re.sub(r"\b\w*\d{3,}\w*\b", " ", text)  # убрать артикулы и годы
    m = _STEP_RE.search(text)
    return int(m.group(1)) if m else None


def extract_brands(title: str) -> set[str]:
    """Латинские слова — почти всегда бренд (Nivea, Sprite, Alpen Gold).

    Исключение — названия из Яндекс Еды: они целиком записаны латиницей
    («Pyure rastishka yabloko grusha»), и там латинское слово ничего не говорит
    о бренде. Для таких названий брендов не выделяем, иначе «брендом» станет
    каждое слово и перестанет работать защита от разных вкусов.
    """
    if is_transliterated(title):
        return set()
    return {w for w in _LATIN_RE.findall(_clean(title))
            if w not in STOP and w not in WEAK_BRAND}


def extract_percent(title: str) -> float | None:
    """Жирность/крепость: «9%», «3,2%» — часто отличает товары."""
    m = _PERCENT_RE.search(_clean(title))
    return float(m.group(1).replace(",", ".")) if m else None


def tokens(title: str) -> set[str]:
    text = _clean(title)
    text = re.sub(r"[^a-zа-я0-9%\s]", " ", text)
    out = set()
    for w in text.split():
        if w in STOP or len(w) < 3:
            continue
        if w.isdigit():
            continue
        if _SIZE_RE.fullmatch(w):
            continue
        out.add(w)
    return out


def unit_price(price: float | None, title: str, unit_hint: str | None = None):
    """Цена за килограмм / литр / штуку — чтобы сравнивать разные фасовки.

    Именно это позволяет понять, что 300 г за 40 000 выгоднее, чем 90 г за 15 000,
    даже если товары не удалось сопоставить между магазинами.

    Учитываем упаковку: «Pepsi 1,75 л х 6 штук» — это 10,5 литра, а не 1,75.
    Возвращает (значение, подпись) либо None.
    """
    if not price:
        return None
    size = extract_size(title, unit_hint)
    if not size:
        return None
    kind, amount = size
    amount *= extract_pack(title) or 1
    if amount <= 0:
        return None
    if kind == "g":
        return round(price / amount * 1000), "сум/кг"
    if kind == "ml":
        return round(price / amount * 1000), "сум/л"
    if kind == "pcs":
        return round(price / amount), "сум/шт"
    return None


def _has_partner(word: str, other: set[str]) -> bool:
    """Слово считается общим, если в другом названии есть оно же или его форма.

    Русские окончания меняются («глаз.» ↔ «глазурью», «сгущенка» ↔ «сгущенкой»),
    а магазины любят сокращения («шок.» ↔ «шоколад»), поэтому сравниваем по началу
    слова: одно должно быть началом другого, минимум 3 буквы.
    """
    for o in other:
        if word == o:
            return True
        short, long = (word, o) if len(word) <= len(o) else (o, word)
        if len(short) >= 3 and long.startswith(short):
            return True
        # Яндекс Еда пишет названия латиницей («grusha» вместо «груша»),
        # поэтому сверяем ещё и по «скелету» слова — см. translit.py
        if same_word(word, o):
            return True
    return False


def _sizes_compatible(a, b) -> bool:
    """Размеры считаем совпавшими при расхождении до 6% (округления вроде 80/85 г)."""
    if a is None or b is None:
        return True  # неизвестно — не повод отказывать
    if a[0] != b[0]:
        return False
    big, small = max(a[1], b[1]), min(a[1], b[1])
    return small > 0 and (big - small) / big <= 0.06


def score(title_a: str, title_b: str, unit_a: str | None = None,
          unit_b: str | None = None) -> tuple[float, str]:
    """Оценка схожести 0..1 и краткая причина отказа (если 0)."""
    size_a, size_b = extract_size(title_a, unit_a), extract_size(title_b, unit_b)
    if not _sizes_compatible(size_a, size_b):
        return 0.0, f"разный размер {size_a} vs {size_b}"

    pack_a, pack_b = extract_pack(title_a), extract_pack(title_b)
    if (pack_a or 1) != (pack_b or 1):
        return 0.0, f"разная упаковка {pack_a} vs {pack_b}"

    pct_a, pct_b = extract_percent(title_a), extract_percent(title_b)
    if pct_a is not None and pct_b is not None and abs(pct_a - pct_b) > 0.11:
        return 0.0, f"разный процент {pct_a} vs {pct_b}"

    art_a, art_b = extract_articles(title_a), extract_articles(title_b)
    if art_a and art_b and not (art_a & art_b):
        return 0.0, f"разные артикулы {sorted(art_a)} vs {sorted(art_b)}"
    # Артикул указан только у одной стороны (частый случай в канцтоварах:
    # «Точилка Deli U-Touch» против «Точилка Deli 0522» — разные модели).
    # Принимаем такое только если размер совпал у обоих.
    if bool(art_a) != bool(art_b) and not (size_a and size_b):
        return 0.0, "модель указана только у одного товара, размер не подтверждён"

    step_a, step_b = extract_step(title_a), extract_step(title_b)
    if step_a is not None and step_b is not None and step_a != step_b:
        return 0.0, f"разные ступени/номера {step_a} vs {step_b}"

    brands_a, brands_b = extract_brands(title_a), extract_brands(title_b)
    brand_hit = brands_a & brands_b
    if brands_a and brands_b and not brand_hit:
        return 0.0, f"разные бренды {sorted(brands_a)} vs {sorted(brands_b)}"

    # Нужно хотя бы одно твёрдое подтверждение: совпавший бренд ИЛИ совпавший
    # размер. Иначе «Альбом для рисования 12 листов» склеится с «Альбомы для
    # рисования» — общие слова есть, а товар может быть совсем другой.
    size_confirmed = size_a is not None and size_b is not None
    if not brand_hit and not size_confirmed:
        return 0.0, "нет подтверждения: ни общего бренда, ни размера"

    ta, tb = tokens(title_a), tokens(title_b)
    if not ta or not tb:
        return 0.0, "нет значимых слов"

    matched_a = {w for w in ta if _has_partner(w, tb)}
    matched_b = {w for w in tb if _has_partner(w, ta)}
    common_n = min(len(matched_a), len(matched_b))
    if common_n < 2:
        return 0.0, "мало общих слов"

    jaccard = common_n / (len(ta) + len(tb) - common_n)

    # Защита от «того же бренда и размера, но другого вкуса»:
    # «Мороженое Grand с шоколадной глазурью» vs «Мороженое Grand со сгущёнкой»,
    # «Fairy Лимон» vs «Fairy Апельсин».
    #
    # Если у КАЖДОЙ стороны есть своё содержательное слово, которого нет у другой,
    # это почти всегда разные варианты товара. Раньше мы отсеивали такие пары
    # только при малом сходстве (jaccard ≤ 0.65), и «Лимон против Апельсина»
    # с его 0.67 проскакивал. Теперь смотрим на сам факт: пропускаем, только если
    # названия совпадают почти дословно и лишнее — явно шум вроде «м/у» или
    # «пластиковая бутылка».
    only_a = {w for w in ta - matched_a if len(w) >= 4 and w not in brands_a | brands_b}
    only_b = {w for w in tb - matched_b if len(w) >= 4 and w not in brands_a | brands_b}
    if only_a and only_b and jaccard < 0.85:
        return 0.0, f"разные варианты: {sorted(only_a)[:2]} vs {sorted(only_b)[:2]}"

    s = jaccard
    if brand_hit:
        s += 0.20                                   # бренд совпал — сильный признак
    if size_a and size_b:
        s += 0.15                                   # размер известен у обоих и сошёлся
    if pct_a is not None and pct_b is not None:
        s += 0.05
    return min(s, 1.0), ""


# Порог подобран на реальных данных (322 товара Korzinka против Uzum).
# Проверенные вручную совпадения дают 0.85–1.00. В диапазоне 0.62–0.74 почти всё
# оказалось мусором: дезодоранты Nivea с похожими названиями (Fresh Kick против
# Arctic Cool), разные модели ручек. Поэтому держим планку высоко: для сервиса
# сравнения цен доверие важнее количества карточек.
THRESHOLD = 0.75


def is_match(title_a: str, title_b: str, unit_a=None, unit_b=None,
             threshold: float = THRESHOLD) -> tuple[bool, float, str]:
    s, why = score(title_a, title_b, unit_a, unit_b)
    return (s >= threshold), s, why


def best_match(title: str, candidates: list[dict], unit: str | None = None,
               title_key: str = "title", threshold: float = THRESHOLD):
    """Выбрать лучший вариант из списка. Возвращает (кандидат, оценка) или (None, 0)."""
    best, best_s = None, 0.0
    for c in candidates:
        s, _ = score(title, c.get(title_key) or "", unit, c.get("unit"))
        if s > best_s:
            best, best_s = c, s
    return (best, best_s) if best_s >= threshold else (None, best_s)
