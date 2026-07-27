"""Small helpers the Bloks client expects (formerly in Nexus acc_gen)."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from curl_cffi import requests as curl_requests


def prompt_input(message: str) -> str:
    """Interactive fallback when no email client is attached."""
    return input(message).strip()


def get_egress_ip(proxies: Optional[Dict[str, str]]) -> str:
    """Public IP behind the proxy (or direct). Never raises."""
    try:
        kwargs: Dict[str, Any] = {"timeout": 20}
        if proxies:
            kwargs["proxies"] = proxies
        resp = curl_requests.get("https://api.ipify.org?format=json", **kwargs)
        return resp.json().get("ip", "unknown")
    except Exception as exc:  # noqa: BLE001
        return f"unknown ({exc})"


def get_egress_geo(
    ip: str, proxies: Optional[Dict[str, str]] = None
) -> Dict[str, str]:
    """Best-effort country/city/org for an IP. Never raises."""
    del proxies  # geo lookup goes direct
    out = {"country": "", "org": "", "city": ""}
    if not ip or str(ip).startswith("unknown"):
        return out
    try:
        resp = curl_requests.get(
            f"http://ip-api.com/json/{ip}"
            "?fields=status,countryCode,city,org,isp",
            timeout=12,
        )
        data = resp.json()
        if data.get("status") == "success":
            out["country"] = str(data.get("countryCode") or "")
            out["city"] = str(data.get("city") or "")
            out["org"] = str(data.get("org") or data.get("isp") or "")
    except Exception:
        pass
    return out


def classify_error(exc: Exception) -> Tuple[str, str]:
    """Rough error bucket for logging."""
    msg = str(exc or "")
    low = msg.lower()
    if "proxy" in low or "curl: (28)" in low or "timed out" in low:
        return "proxy", msg
    if "email" in low:
        return "email", msg
    if "block" in low or "integrity" in low or "checkpoint" in low:
        return "blocked", msg
    return "unknown", msg
