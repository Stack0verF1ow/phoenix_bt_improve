from __future__ import annotations

import json
import re
import shlex
from http.cookiejar import MozillaCookieJar
from collections.abc import Iterable, Mapping
from pathlib import Path
from urllib.parse import urlparse

PHOENIX_HOST = "phoenix.stu.edu.cn"


def normalize_cookie_header(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    parsed = _parse_json_cookie_export(raw)
    if parsed:
        return parsed
    parsed = _parse_cookie_header(raw)
    if parsed:
        return parsed
    parsed = _parse_curl_cookie(raw)
    if parsed:
        return parsed
    parsed = _parse_set_cookie_headers(raw)
    if parsed:
        return parsed
    if "\n" not in raw and ";" in raw and "=" in raw:
        return raw
    parsed = _parse_browser_table(raw)
    if parsed:
        return parsed
    return raw.replace("\r", "").replace("\n", "; ")


def cookie_header_from_netscape_file(path: Path, host: str = PHOENIX_HOST) -> str:
    jar = MozillaCookieJar(str(path.expanduser().resolve()))
    jar.load(ignore_discard=True, ignore_expires=True)
    pairs = []
    for cookie in jar:
        if host.endswith(cookie.domain.lstrip(".")) or cookie.domain.lstrip(".").endswith(host):
            pairs.append(f"{cookie.name}={cookie.value}")
    return "; ".join(pairs)


def cookie_header_from_cookie_items(cookies: Iterable[Mapping[str, str]], host: str = PHOENIX_HOST) -> str:
    pairs: list[str] = []
    seen: set[str] = set()
    for cookie in cookies:
        domain = cookie.get("domain", "")
        if domain and not _domain_matches(host, domain):
            continue
        name = cookie.get("name", "")
        value = cookie.get("value", "")
        if not name or name in seen:
            continue
        pairs.append(f"{name}={value}")
        seen.add(name)
    return "; ".join(pairs)


def _parse_browser_table(raw: str) -> str:
    pairs: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.lower().startswith(("name\t", "名称\t")):
            continue
        if "\t" in line:
            columns = line.split("\t")
        elif "," in line and "=" not in line.split(",", 1)[0]:
            columns = [column.strip() for column in line.split(",")]
        else:
            continue
        if len(columns) >= 2 and columns[0] and columns[1]:
            pairs.append(f"{columns[0]}={columns[1]}")
    return "; ".join(pairs)


def _parse_cookie_header(raw: str) -> str:
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("cookie:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def _parse_curl_cookie(raw: str) -> str:
    if "curl" not in raw.lower() and "-H" not in raw and "--header" not in raw and "-b" not in raw:
        return ""
    try:
        tokens = shlex.split(raw, posix=False)
    except ValueError:
        tokens = re.findall(r"""'[^']*'|"[^"]*"|\S+""", raw)

    for index, token in enumerate(tokens):
        cleaned = token.strip("'\"")
        if cleaned.lower().startswith("cookie:"):
            return cleaned.split(":", 1)[1].strip()
        if cleaned in {"-H", "--header", "-b", "--cookie"} and index + 1 < len(tokens):
            next_token = tokens[index + 1].strip("'\"")
            if next_token.lower().startswith("cookie:"):
                return next_token.split(":", 1)[1].strip()
            if "=" in next_token and ";" in next_token:
                return next_token
    return ""


def _parse_set_cookie_headers(raw: str) -> str:
    pairs: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith("set-cookie:"):
            continue
        cookie = stripped.split(":", 1)[1].strip().split(";", 1)[0].strip()
        if "=" in cookie:
            pairs.append(cookie)
    return "; ".join(pairs)


def _parse_json_cookie_export(raw: str) -> str:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ""

    if isinstance(data, dict) and "cookies" in data:
        data = data["cookies"]
    if not isinstance(data, list):
        return ""

    pairs: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain", ""))
        if domain and PHOENIX_HOST not in domain:
            continue
        name = item.get("name")
        value = item.get("value")
        if name and value is not None:
            pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def _domain_matches(host: str, domain: str) -> bool:
    normalized_host = host.lower().lstrip(".")
    normalized_domain = domain.lower().lstrip(".")
    return normalized_host == normalized_domain or normalized_host.endswith("." + normalized_domain)
