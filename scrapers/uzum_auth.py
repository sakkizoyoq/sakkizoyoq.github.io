"""Гостевой пропуск Uzum — получаем сами, без браузера.

Каталог Uzum открыт всем, но GraphQL требует «пропуск» (bearer-токен), который
Uzum ID выдаёт любому анонимному посетителю. Раньше мы доставали его руками из
браузера; теперь запрашиваем той же командой, что и сам сайт:

    POST https://id.uzum.uz/api/auth/token
    (тело пустое, токен приходит в заголовке Set-Cookie: access_token=...)

Единственное обязательное условие — заголовок Accept-Language. Без него сервер
отвечает 400 insufficient_headers.

Пропуск живёт 3 часа, поэтому кладём его в data/.uzum_token.json и переспрашиваем
только когда он вот-вот истечёт.

Проверить вручную:  python3 -m scrapers.uzum_auth
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.request
import uuid
from pathlib import Path

TOKEN_URL = "https://id.uzum.uz/api/auth/token"
CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / ".uzum_token.json"

# Просим новый пропуск, если до конца текущего осталось меньше этого времени.
REFRESH_MARGIN_SEC = 10 * 60

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _expiry(token: str) -> int | None:
    """Срок годности из самого токена (JWT хранит его в поле exp)."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("exp")
    except Exception:
        return None


def _request_token() -> tuple[str, str]:
    req = urllib.request.Request(TOKEN_URL, data=b"", method="POST", headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Accept-Language": "ru-RU",          # без него — 400 insufficient_headers
        "Origin": "https://uzum.uz",
        "Referer": "https://uzum.uz/",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        for cookie in r.headers.get_all("Set-Cookie") or []:
            m = re.match(r"access_token=([^;]+)", cookie)
            if m:
                return m.group(1), str(uuid.uuid4())
    raise RuntimeError("Uzum ID не вернул access_token — возможно, изменился их вход")


def _load_cache() -> dict | None:
    try:
        data = json.loads(CACHE_PATH.read_text())
    except Exception:
        return None
    if not data.get("token"):
        return None
    exp = data.get("exp") or 0
    if exp - time.time() < REFRESH_MARGIN_SEC:
        return None
    return data


def get_guest_token(force: bool = False) -> tuple[str, str]:
    """Возвращает (токен, iid). Берёт из кэша, пока он свежий.

    UZUM_TOKEN в окружении по-прежнему главнее — на случай, если понадобится
    подставить свой пропуск вручную.
    """
    env_token = os.environ.get("UZUM_TOKEN")
    if env_token:
        return env_token, os.environ.get("UZUM_IID", str(uuid.uuid4()))

    if not force:
        cached = _load_cache()
        if cached:
            return cached["token"], cached["iid"]

    token, iid = _request_token()
    exp = _expiry(token) or int(time.time()) + 3 * 3600
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps({"token": token, "iid": iid, "exp": exp}))
    return token, iid


def main() -> None:
    token, iid = get_guest_token(force=True)
    exp = _expiry(token)
    left = round((exp - time.time()) / 60) if exp else "?"
    print(f"[uzum-auth] пропуск получен, длина {len(token)} символов")
    print(f"[uzum-auth] действует ещё ~{left} мин, iid {iid}")
    print(f"[uzum-auth] сохранён в {CACHE_PATH}")


if __name__ == "__main__":
    main()
