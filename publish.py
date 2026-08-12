"""Положить готовую страницу в docs/ — оттуда её показывает GitHub Pages.

Собранные страницы лежат в site/, но в репозиторий они не входят: это рабочие
файлы, которые пересобираются. В docs/ кладём копию — именно её видит интернет
по адресу https://popovaleriya27-lgtm.github.io/sakkizoyoq/

Отдельный файл, потому что этим пользуются обе сборки — и витрина, и справочник.
"""
from __future__ import annotations

import os
import shutil

DOCS = "docs"


def publish(path: str) -> str:
    """Скопировать собранную страницу в docs/. Возвращает путь копии."""
    os.makedirs(DOCS, exist_ok=True)
    target = os.path.join(DOCS, os.path.basename(path))
    shutil.copyfile(path, target)
    # .nojekyll говорит GitHub Pages не обрабатывать файлы по-своему:
    # без него он игнорирует всё, что начинается с подчёркивания.
    open(os.path.join(DOCS, ".nojekyll"), "w").close()
    size_mb = os.path.getsize(target) / 1024 / 1024
    print(f"  опубликовано: {target} ({size_mb:.1f} МБ)")
    return target
