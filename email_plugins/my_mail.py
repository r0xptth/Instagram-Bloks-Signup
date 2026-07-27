"""qeex email plugin"""

from __future__ import annotations

import os
from typing import Optional

from email_api import http_json

API_KEY = os.environ.get("MY_MAIL_API_KEY", "").strip()
BASE = "https://qeex.net/api/v1"


def create_order(
    site: str = "instagram.com",
    domain: Optional[str] = None,
    attempt: int = 0,
) -> dict:
    del attempt
    if not API_KEY:
        return {"ok": False, "error": "Set MY_MAIL_API_KEY in .env"}

    try:
        data = http_json(
            "GET",
            f"{BASE}/{API_KEY}/emailGet",
            params={"site": site, "domain": domain or "microsoft"},
        )
        if not data.get("success", False):
            return {"ok": False, "error": str(data.get("error") or data)}

        result = data.get("result") or data
        order_id = result.get("id")
        email = result.get("email")
        if not order_id or not email:
            return {"ok": False, "error": f"bad response: {data}"}

        return {"ok": True, "order_id": str(order_id), "email": str(email)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def get_code(order_id: str) -> dict:
    try:
        data = http_json(
            "GET",
            f"{BASE}/{API_KEY}/emailCode",
            params={"id": order_id, "regex": r"[0-9]{6}"},
        )
        if not data.get("success", False):
            return {"ok": False, "pending": True}

        result = data.get("result") or data
        code = str(result.get("code") or "").strip()
        if code:
            return {"ok": True, "code": code}
        return {"ok": False, "pending": True}
    except Exception:
        return {"ok": False, "pending": True}


def cancel_order(order_id: str) -> dict:
    try:
        http_json(
            "GET",
            f"{BASE}/{API_KEY}/emailCancel",
            params={"id": order_id},
        )
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


EXPORTS = {
    "create_order": create_order,
    "get_code": get_code,
    "cancel_order": cancel_order,
}
