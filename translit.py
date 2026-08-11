"""Сведение русских и латинских написаний к одному виду.

Яндекс Еда отдаёт названия так, как их забили в кассу магазина — латиницей:

    «Pyure rastishka yabloko grusha 85gr»

А Korzinka и Uzum пишут по-русски:

    «Пюре Растишка яблоко груша 85 г»

Это один товар, но для программы — разные слова. Здесь мы приводим и то и другое
к общему «скелету»: русское переводим в латиницу, а потом обе стороны упрощаем,
схлопывая всё, что магазины пишут по-разному.

Почему нужно именно упрощение, а не точный перевод: магазины транслитерируют
как попало. «Леденцы» они записали как «Ledensy» (хотя по правилам «ledentsy»),
«хербион» — как «herbion» (а не «kherbion»). Поэтому мы намеренно огрубляем:
ц и с — одно, х и kh — одно, ш и s — одно. Слова становятся менее точными, зато
разные написания одного слова сходятся.
"""
from __future__ import annotations

import re
import unicodedata

# Кириллица → латиница. Порядок важен: сначала длинные последовательности.
CYR_TO_LAT = {
    "щ": "sh", "ш": "sh", "ч": "ch", "ж": "zh", "ц": "ts", "х": "h",
    "ю": "yu", "я": "ya", "ё": "yo", "э": "e", "ы": "y", "й": "y",
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
    "з": "z", "и": "i", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "ь": "", "ъ": "", "ў": "u", "қ": "q", "ғ": "g", "ҳ": "h",
}

# Огрубление: всё, что магазины пишут по-разному, сводим к одной букве.
COLLAPSE = [
    ("shch", "s"), ("sch", "s"), ("sh", "s"), ("ch", "c"), ("zh", "z"),
    ("ts", "s"), ("kh", "h"), ("ph", "f"), ("ck", "k"), ("qu", "k"),
    # «ё» при разборе превращается в «е», а латиницей магазины пишут «yo»
    # («вишнёвый» / «vishnyoviy»), поэтому сводим оба варианта к «e».
    ("yo", "e"), ("yu", "u"), ("ya", "a"), ("ye", "e"), ("yi", "i"),
    ("iy", "i"), ("yy", "i"), ("ij", "i"), ("j", "z"), ("w", "v"),
    ("q", "k"), ("x", "h"), ("y", "i"),
]

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def to_latin(text: str) -> str:
    """Перевести кириллицу в латиницу, латиницу оставить как есть.

    Кириллицу переводим ДО снятия надстрочных знаков: иначе «й» распадается на
    «и» с краткой, а «ё» — на «е», и обе буквы теряются («майонез» превратился бы
    в «maionez» вместо «mayonez» и перестал сходиться с латинским написанием).
    """
    text = (text or "").lower()
    text = "".join(CYR_TO_LAT.get(ch, ch) for ch in text)
    return _strip_accents(text)


def skeleton(word: str) -> str:
    """«Скелет» слова — то, что остаётся после огрубления.

    «пюре» → pyure → pure
    «Pyure» → pyure → pure
    «леденцы» → ledentsy → ledensi
    «Ledensy» → ledensy → ledensi
    """
    s = to_latin(word)
    s = _NON_ALNUM.sub("", s)
    for a, b in COLLAPSE:
        s = s.replace(a, b)
    # двойные буквы магазины ставят как придётся: «Rasstishka» / «Rastishka»
    out = []
    for ch in s:
        if not out or out[-1] != ch:
            out.append(ch)
    return "".join(out)


def same_word(a: str, b: str, min_len: int = 4) -> bool:
    """Одно ли это слово в разных написаниях (с учётом окончаний)."""
    sa, sb = skeleton(a), skeleton(b)
    if not sa or not sb:
        return False
    if sa == sb:
        return True
    short, long = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    return len(short) >= min_len and long.startswith(short)


def is_transliterated(text: str) -> bool:
    """Похоже ли, что название записано латиницей вместо русского.

    Нужно, чтобы не путать настоящие бренды (Nivea, Colgate) с транслитом.
    """
    letters = [c for c in (text or "").lower() if c.isalpha()]
    if not letters:
        return False
    cyrillic = sum(1 for c in letters if "Ѐ" <= c <= "ӿ")
    return cyrillic / len(letters) < 0.15
