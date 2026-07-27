"""proxy parsing helpers"""

from __future__ import annotations

import random
import string
from typing import Dict, List, Optional
from urllib.parse import quote


def _looks_like_port(value: str) -> bool:
    try:
        return 1 <= int(value) <= 65535
    except (TypeError, ValueError):
        return False


def _looks_like_host(value: str) -> bool:
    s = (value or "").strip().strip("[]")
    if not s or s.startswith("#"):
        return False
    if s.lower() == "localhost":
        return True
    if s.count(".") == 3 and all(
        p.isdigit() and 0 <= int(p) <= 255 for p in s.split(".")
    ):
        return True
    return "." in s or ":" in s


def parse_proxy_line(line: str) -> Optional[Dict[str, str]]:
    # user:pass@host:port | host:port:user:pass | user:pass:host:port | host:port
    raw = (line or "").strip().strip("'\"")
    if not raw or raw.startswith("#"):
        return None

    lowered = raw.lower()
    for prefix in ("http://", "https://", "socks5://", "socks4://", "socks://"):
        if lowered.startswith(prefix):
            raw = raw[len(prefix) :]
            break

    host = port = user = password = ""

    if "@" in raw:
        left, _, right = raw.rpartition("@")
        if _looks_like_host(right.split(":")[0]) and _looks_like_port(
            right.rsplit(":", 1)[-1]
        ):
            user, _, password = left.partition(":")
            host, _, port = right.rpartition(":")
        elif _looks_like_host(left.split(":")[0]) and _looks_like_port(
            left.rsplit(":", 1)[-1]
        ):
            host, _, port = left.rpartition(":")
            user, _, password = right.partition(":")
        else:
            user, _, password = left.partition(":")
            host, _, port = right.rpartition(":")
    else:
        parts = raw.split(":")
        if len(parts) == 2 and _looks_like_port(parts[1]):
            host, port = parts[0], parts[1]
        elif len(parts) >= 4:
            if _looks_like_host(parts[0]) and _looks_like_port(parts[1]):
                host, port, user = parts[0], parts[1], parts[2]
                password = ":".join(parts[3:])
            elif _looks_like_host(parts[2]) and _looks_like_port(parts[3]):
                user, password = parts[0], parts[1]
                host, port = parts[2], parts[3]
            else:
                host, port, user = parts[0], parts[1], parts[2]
                password = ":".join(parts[3:])
        else:
            return None

    host = (host or "").strip().strip("[]")
    port = str(port or "").strip()
    user = (user or "").strip()
    password = (password or "").strip()
    if not host or not _looks_like_port(port):
        return None
    return {
        "host": host,
        "port": port,
        "username": user,
        "password": password,
    }


def load_proxy_lines(path: str) -> List[str]:
    out: List[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    return out


def _sid(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def build_proxies(
    config: Dict[str, str],
    *,
    session_id: Optional[str] = None,
) -> Dict[str, str]:
    # <SID> in user/pass gets replaced with session_id
    sid = (session_id or _sid())[:8]
    user = (config.get("username") or "").replace("<SID>", sid)
    password = (config.get("password") or "").replace("<SID>", sid)
    if user and password:
        auth = f"{quote(user, safe='')}:{quote(password, safe='')}@"
    elif user:
        auth = f"{quote(user, safe='')}@"
    else:
        auth = ""
    url = f"http://{auth}{config['host']}:{config['port']}"
    return {"http": url, "https": url}


def format_proxy_line(config: Dict[str, str]) -> str:
    host = config.get("host") or ""
    port = config.get("port") or ""
    user = config.get("username") or ""
    pw = config.get("password") or ""
    if user or pw:
        return f"{host}:{port}:{user}:{pw}"
    return f"{host}:{port}"
