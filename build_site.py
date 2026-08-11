"""Собрать витрину: данные + картинки → готовая страница site/index.html.

Картинки встраиваются прямо в страницу (иначе они не отображаются там, где
страница опубликована). Скачанные картинки складываются в кэш, поэтому вторая
и последующие сборки проходят быстро.

Запуск:  python3 build_site.py
"""
from __future__ import annotations

import base64
import collections
import json
import os
import time
import urllib.request

from categories import ORDER, OTHER
from matching import unit_price

CACHE_PATH = "data/.image_cache.json"
MAX_IMAGE_BYTES = 3_000_000   # больше этого не качаем вовсе
TARGET_BYTES = 20_000         # во что стараемся уложить картинку в странице
THUMB_SIDE = 240              # карточки маленькие, больше и не нужно

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "image/webp,image/png,image/*,*/*;q=0.8",
    "Referer": "https://korzinka.uz/",
}


def _sniff(raw: bytes) -> str | None:
    """Определить формат по содержимому: магазины отдают webp под именем .jpg."""
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:2] == b"\xff\xd8":
        return "image/jpeg"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


def _to_data_uri(raw: bytes) -> str | None:
    """Ужать картинку под размер карточки и превратить в строку для страницы.

    Магазины отдают фото по 900 КБ — если вшить их как есть, страница
    распухнет. Уменьшаем до THUMB_SIDE и пересохраняем в WebP.
    """
    if len(raw) <= TARGET_BYTES:
        mime = _sniff(raw)
        if mime:
            return f"data:{mime};base64," + base64.b64encode(raw).decode()

    try:
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(raw))
        img.thumbnail((THUMB_SIDE, THUMB_SIDE), Image.LANCZOS)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.mode else "RGB")
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=78, method=4)
        return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        mime = _sniff(raw)
        if mime and len(raw) <= MAX_IMAGE_BYTES:
            return f"data:{mime};base64," + base64.b64encode(raw).decode()
        return None


class ImageCache:
    def __init__(self, path: str = CACHE_PATH):
        self.path = path
        self.data: dict[str, str] = {}
        if os.path.exists(path):
            try:
                self.data = json.load(open(path, encoding="utf-8"))
            except Exception:
                self.data = {}
        self.hits = self.misses = self.failed = 0

    def get(self, url: str | None) -> str | None:
        if not url:
            return None
        if url.startswith("data:"):
            return url
        if url in self.data:
            self.hits += 1
            return self.data[url] or None
        self.misses += 1
        value = self._download(url)
        self.data[url] = value or ""
        if not value:
            self.failed += 1
        return value

    def _download(self, url: str) -> str | None:
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers=HEADERS)
                raw = urllib.request.urlopen(req, timeout=20).read()
                if len(raw) > MAX_IMAGE_BYTES or not _sniff(raw):
                    return None
                return _to_data_uri(raw)
            except Exception as exc:
                # 429 — магазин просит сбавить темп
                time.sleep(1.5 + attempt if getattr(exc, "code", None) == 429 else 0.3)
        return None

    def save(self) -> None:
        json.dump(self.data, open(self.path, "w", encoding="utf-8"), ensure_ascii=False)


def load_comparisons(cache: ImageCache) -> list[dict]:
    path = "data/comparisons.json"
    if not os.path.exists(path):
        return []
    cards = json.load(open(path, encoding="utf-8"))
    out = []
    for c in cards:
        c["image"] = cache.get(c.get("image"))
        if not c["image"]:
            continue
        for s in c["stores"]:
            s.pop("image", None)
            if "unit_price" not in s:
                up = unit_price(s["price"], s.get("title") or c["name"], c.get("unit"))
                if up:
                    s["unit_price"], s["unit_label"] = up
        out.append(c)
    return out


def collected_at() -> str | None:
    """Когда цены собраны на самом деле — по свежайшей отметке в выгрузках.

    Раньше дата стояла в шаблоне руками и успела устареть на день.
    """
    latest = None
    for name in ("korzinka_sample.json", "makro_sample.json",
                 "uzum_sample.json", "yandex_sample.json"):
        path = os.path.join("data", name)
        if not os.path.exists(path):
            continue
        for row in json.load(open(path, encoding="utf-8")):
            stamp = row.get("scraped_at")
            if stamp and (latest is None or stamp > latest):
                latest = stamp
    return latest[:10] if latest else None


def main() -> None:
    cache = ImageCache()
    print("Готовлю карточки сравнения...")
    comparisons = load_comparisons(cache)
    print(f"  карточек: {len(comparisons)}")
    cache.save()
    print(f"Картинки: из кэша {cache.hits}, скачано {cache.misses - cache.failed}, "
          f"не удалось {cache.failed}")

    by_category = collections.Counter(c.get("category") or OTHER for c in comparisons)
    print("По категориям:")
    for label in ORDER:
        if by_category[label]:
            print(f"  {label:<20} {by_category[label]:>4}")

    # На витрине показываем только товары, у которых есть с чем сравнить.
    # Одиночные товары («каталог магазина») убраны: они не отвечают на вопрос,
    # ради которого человек сюда пришёл.
    payload = {"comparisons": comparisons,
               "categories": [l for l in ORDER if by_category[l]],
               "collectedAt": collected_at()}
    template = open("site/index.template.html", encoding="utf-8").read()
    data_js = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    open("site/index.html", "w", encoding="utf-8").write(template.replace("__DATA__", data_js))

    size_mb = os.path.getsize("site/index.html") / 1024 / 1024
    three = sum(1 for c in comparisons if len(c["stores"]) >= 3)
    print(f"\nГотово: site/index.html — {size_mb:.1f} МБ")
    print(f"  сравнений: {len(comparisons)} (по трём магазинам: {three})")
    if size_mb > 15:
        print("  ВНИМАНИЕ: страница близка к пределу 16 МБ — уменьшите THUMB_SIDE")


if __name__ == "__main__":
    main()
