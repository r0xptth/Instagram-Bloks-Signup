"""
Example email plugin.

cp email_plugins/_example.py email_plugins/my_mail.py
# edit my_mail.py, set MY_MAIL_API_KEY
python run.py --email my_mail --bots 1
"""

from __future__ import annotations

import os
from typing import Optional

from email_api import http_json

API_KEY = os.environ.get("MY_MAIL_API_KEY", "").strip()


def create_order(
    site: str = "instagram.com",
    domain: Optional[str] = None,
    attempt: int = 0,
) -> dict:
    # TODO: call your api, return order_id + email
    if not API_KEY:
        return {"ok": False, "error": "Set MY_MAIL_API_KEY in .env"}
    raise NotImplementedError("create_order")


def get_code(order_id: str) -> dict:
    # TODO: single poll. pending=True if mail not in yet
    raise NotImplementedError("get_code")


def cancel_order(order_id: str) -> dict:
    # TODO: cancel/refund
    raise NotImplementedError("cancel_order")


EXPORTS = {
    "create_order": create_order,
    "get_code": get_code,
    "cancel_order": cancel_order,
}
