"""
CLI entrypoint.

Usage:
  python run.py --email my_mail --bots 1
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bloks.client import MobileBloksCAASignupClient, MobileBloksSignupError
from bloks.proxies import build_proxies, format_proxy_line, load_proxy_lines, parse_proxy_line
from email_plugins import list_providers, load_provider

HITS_HEADERS = [
    "Username",
    "Password",
    "Email",
    "Session ID",
    "Proxy Provider",
    "Proxy",
]

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("lab")

_hits_lock = threading.Lock()


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = val


def append_hit(path: Path, row: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _hits_lock:
        new_file = not path.is_file() or path.stat().st_size == 0
        existing: set[str] = set()
        if not new_file:
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                for r in csv.DictReader(fh):
                    u = (r.get("Username") or "").lower()
                    if u:
                        existing.add(u)
        user = (row.get("Username") or "").lower()
        if user and user in existing:
            log.info("skip duplicate @%s", row.get("Username"))
            return
        with path.open("a", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=HITS_HEADERS, extrasaction="ignore")
            if new_file:
                w.writeheader()
            w.writerow({k: row.get(k, "") for k in HITS_HEADERS})


def create_one(
    *,
    bot_id: int,
    proxy_line: str,
    email_client: Any,
) -> Optional[Dict[str, str]]:
    cfg = parse_proxy_line(proxy_line)
    if not cfg:
        log.error("[bot-%s] bad proxy: %s", bot_id, proxy_line)
        return None

    sid = f"b{bot_id}{int(time.time()) % 100000:05d}"[:8]
    proxies = build_proxies(cfg, session_id=sid)
    paste = format_proxy_line(cfg)

    log.info("[bot-%s] proxy %s:%s", bot_id, cfg["host"], cfg["port"])
    client = MobileBloksCAASignupClient(
        proxies=proxies,
        email_client=email_client,
    )
    try:
        creds = client.run(order_attempt=bot_id - 1)
    except MobileBloksSignupError as exc:
        log.error("[bot-%s] fail: %s", bot_id, exc)
        return None
    except Exception as exc:
        log.exception("[bot-%s] error: %s", bot_id, exc)
        return None

    if not creds:
        log.error("[bot-%s] fail: no creds", bot_id)
        return None

    hit = {
        "Username": creds.get("username") or "",
        "Password": creds.get("password") or "",
        "Email": creds.get("email") or "",
        "Session ID": creds.get("session_id") or "",
        "Proxy Provider": "",
        "Proxy": paste,
    }
    log.info("[bot-%s] hit @%s %s", bot_id, hit["Username"], hit["Email"])
    return hit


def main(argv: Optional[List[str]] = None) -> int:
    _load_dotenv(ROOT / ".env")

    ap = argparse.ArgumentParser(description="instagram mobile bloks signup")
    ap.add_argument(
        "--email",
        default=os.environ.get("EMAIL_PROVIDER", "my_mail"),
        help="email plugin name",
    )
    ap.add_argument("--proxies", default="proxies.txt", help="proxy list file")
    ap.add_argument("--bots", type=int, default=1, help="worker count")
    ap.add_argument("--hits", default="hits.csv", help="output csv")
    ap.add_argument("--list-emails", action="store_true", help="list plugins")
    args = ap.parse_args(argv)

    if args.list_emails:
        print("plugins:")
        for name in list_providers():
            print(f"  {name}")
        return 0

    proxies_path = Path(args.proxies)
    if not proxies_path.is_file():
        log.error("missing %s (copy proxies.txt.example)", proxies_path)
        return 2

    lines = load_proxy_lines(str(proxies_path))
    if not lines:
        log.error("no proxies in %s", proxies_path)
        return 2

    try:
        email_client = load_provider(args.email)
    except Exception as exc:
        log.error("email plugin: %s", exc)
        return 2

    if hasattr(email_client, "get_balance"):
        try:
            bal = email_client.get_balance()
            log.info("email=%s balance=%s", args.email, bal)
        except Exception as exc:
            log.warning("balance check failed: %s", exc)

    bots = max(1, int(args.bots))
    hits_path = Path(args.hits)
    log.info(
        "start bots=%s proxies=%s email=%s hits=%s",
        bots,
        len(lines),
        args.email,
        hits_path,
    )

    ok = 0
    with ThreadPoolExecutor(max_workers=bots) as pool:
        futs = []
        for i in range(bots):
            proxy_line = lines[i % len(lines)]
            futs.append(
                pool.submit(
                    create_one,
                    bot_id=i + 1,
                    proxy_line=proxy_line,
                    email_client=email_client,
                )
            )
        for fut in as_completed(futs):
            hit = fut.result()
            if hit and hit.get("Username") and hit.get("Session ID"):
                append_hit(hits_path, hit)
                ok += 1

    log.info("done %s/%s -> %s", ok, bots, hits_path.resolve())
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
