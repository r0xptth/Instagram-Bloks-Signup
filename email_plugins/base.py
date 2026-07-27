"""HTTP helper and EmailProvider base."""

from __future__ import annotations

import logging
import os
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from curl_cffi import requests as curl_requests

logger = logging.getLogger(__name__)


def http_json(
    method: str,
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    proxies: Optional[Dict[str, str]] = None,
    timeout: float = 30,
) -> Any:
    # GET/POST/etc, returns json. raises on bad status / non-json.
    resp = curl_requests.request(
        method.upper(),
        url,
        params=params,
        json=json_body,
        headers=headers or {},
        proxies=proxies,
        timeout=timeout,
    )
    try:
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(
            f"email API non-JSON ({resp.status_code}) {url}: {resp.text[:240]!r}"
        ) from exc
    if int(getattr(resp, "status_code", 0) or 0) >= 400:
        raise RuntimeError(f"email API HTTP {resp.status_code} {url}: {data!r}")
    return data


def extract_ig_code(text: str, *, exclude: Optional[set] = None) -> Optional[str]:
    # scrape a 6-digit ig code out of mail html/text
    exclude = exclude or set()
    cleaned = re.sub(r"<[^>]+>", " ", text or "")
    cleaned = re.sub(r"&nbsp;|&#\d+;", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned)
    patterns = (
        r"(\d{6})\s+is your Instagram code",
        r"(\d{6})\s+is your code",
        r"Instagram code[:\s]+(\d{6})",
        r"confirmation code[:\s]+(\d{6})",
        r"code is[:\s]+(\d{6})",
        r"\b(\d{6})\b",
    )
    for pat in patterns:
        for m in re.finditer(pat, cleaned, re.I):
            code = m.group(1)
            if code in exclude:
                continue
            if not code.isdigit() or len(set(code)) <= 1:
                continue
            # Skip year-looking numbers.
            if code.startswith(("19", "20")) and 1990 <= int(code[:4]) <= 2035:
                continue
            return code
    return None


def _dig(obj: Any, path: str, default: Any = None) -> Any:
    # "result.id" style lookup
    if not path:
        return obj
    cur = obj
    for part in path.split("."):
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(part, default)
        else:
            return default
    return cur


class EmailProvider(ABC):
    contactpoint_type: str = "EMAIL"

    def __init__(
        self,
        api_key: str = "",
        *,
        api_key_env: str = "",
        proxies: Optional[Dict[str, str]] = None,
        poll_interval: float = 5.0,
        **_: Any,
    ):
        env_name = (api_key_env or "").strip()
        key = (api_key or (os.environ.get(env_name) if env_name else "") or "").strip()
        self.api_key = key
        self.proxies = proxies
        self.poll_interval = float(poll_interval)

    def require_api_key(self, hint: str = "") -> str:
        if not self.api_key:
            raise RuntimeError(
                hint or "API key missing"
            )
        return self.api_key

    @abstractmethod
    def create_order(
        self,
        site: str = "instagram.com",
        domain: Optional[str] = None,
        attempt: int = 0,
    ) -> Tuple[str, str]:
        ...  # return (order_id, email)

    def fetch_code(self, order_id: str) -> Optional[str]:
        # one poll; None = not here yet. wait_for_code loops this.
        raise NotImplementedError(
            f"{type(self).__name__}: implement fetch_code() or wait_for_code()"
        )

    def wait_for_code(
        self,
        order_id: str,
        timeout: int = 180,
        interval: Optional[float] = None,
        exclude_codes: Optional[List[str]] = None,
    ) -> Optional[str]:
        exclude = set(exclude_codes or [])
        gap = float(interval if interval is not None else self.poll_interval)
        gap = max(1.0, gap)
        deadline = time.time() + timeout
        logger.info(
            "%s: waiting for code (%ss)", type(self).__name__, timeout
        )
        while time.time() < deadline:
            try:
                code = self.fetch_code(order_id)
            except NotImplementedError:
                raise
            except Exception as exc:
                logger.warning("%s poll error: %s", type(self).__name__, exc)
                code = None
            if code and str(code) not in exclude:
                logger.info("%s: code received", type(self).__name__)
                return str(code)
            time.sleep(gap)
        return None

    @abstractmethod
    def cancel_order(self, order_id: str) -> None:
        ...

    def get_balance(self) -> float:
        return 0.0

    def release_order_slot(self) -> None:
        return None


class RestEmailProvider(EmailProvider):
    # driven by json config (_rest_example.json)

    def __init__(self, config: Dict[str, Any], **kwargs: Any):
        super().__init__(
            api_key=kwargs.pop("api_key", ""),
            api_key_env=config.get("api_key_env") or kwargs.pop("api_key_env", ""),
            proxies=kwargs.get("proxies"),
            poll_interval=float(config.get("poll_interval") or 5),
            **kwargs,
        )
        self.config = config
        self.require_api_key(
            f"Set {config.get('api_key_env') or 'API key'} in .env for "
            f"REST provider {config.get('name') or '?'}"
        )

    def _fmt(self, value: Any, **ctx: Any) -> Any:
        if isinstance(value, str):
            try:
                return value.format(api_key=self.api_key, **ctx)
            except KeyError:
                return value
        if isinstance(value, dict):
            return {k: self._fmt(v, **ctx) for k, v in value.items()}
        if isinstance(value, list):
            return [self._fmt(v, **ctx) for v in value]
        return value

    def _call(self, section: str, **ctx: Any) -> Any:
        spec = self.config.get(section) or {}
        if not spec:
            raise RuntimeError(f"REST config missing '{section}' block")
        method = str(spec.get("method") or "GET").upper()
        url = self._fmt(spec.get("url") or "", **ctx)
        if not url:
            raise RuntimeError(f"REST config '{section}' needs a url")
        params = self._fmt(spec.get("params") or {}, **ctx)
        body = self._fmt(spec.get("json") or None, **ctx)
        headers = self._fmt(
            {**(self.config.get("headers") or {}), **(spec.get("headers") or {})},
            **ctx,
        )
        data = http_json(
            method,
            url,
            params=params or None,
            json_body=body,
            headers=headers or None,
            proxies=self.proxies,
        )
        # optional success_path / success_value check
        sp = spec.get("success_path") or self.config.get("success_path")
        if sp:
            got = _dig(data, str(sp))
            want = spec.get("success_value", self.config.get("success_value", True))
            if got != want:
                err = _dig(data, str(spec.get("error_path") or "error"), data)
                raise RuntimeError(f"email API error ({section}): {err}")
        return data

    def create_order(
        self,
        site: str = "instagram.com",
        domain: Optional[str] = None,
        attempt: int = 0,
    ) -> Tuple[str, str]:
        spec = self.config.get("create") or {}
        data = self._call(
            "create",
            site=site,
            domain=domain or "",
            attempt=attempt,
        )
        root = _dig(data, str(spec.get("root") or ""), data)
        oid = _dig(root, str(spec.get("order_id") or "id"))
        email = _dig(root, str(spec.get("email") or "email"))
        if not oid or not email:
            raise RuntimeError(f"create_order parse failed: {data!r}")
        logger.info("Ordered email %s (id %s)", email, oid)
        return str(oid), str(email)

    def fetch_code(self, order_id: str) -> Optional[str]:
        spec = self.config.get("code") or {}
        data = self._call("code", order_id=order_id, site="instagram.com")
        root = _dig(data, str(spec.get("root") or ""), data)
        code = _dig(root, str(spec.get("code") or "code"))
        if code:
            return str(code)
        # fall back to scraping the mail body
        body_path = spec.get("body")
        if body_path:
            body = _dig(root, str(body_path), "")
            return extract_ig_code(str(body or ""))
        return None

    def cancel_order(self, order_id: str) -> None:
        if not (self.config.get("cancel") or {}).get("url"):
            return None
        try:
            self._call("cancel", order_id=order_id, site="instagram.com")
            logger.info("Cancelled order %s", order_id)
        except Exception as exc:
            logger.debug("cancel %s: %s", order_id, exc)
        return None

    def get_balance(self) -> float:
        spec = self.config.get("balance") or {}
        if not spec.get("url"):
            return 0.0
        data = self._call("balance", order_id="", site="instagram.com")
        root = _dig(data, str(spec.get("root") or ""), data)
        bal = _dig(root, str(spec.get("balance") or "balance"), 0)
        try:
            return float(bal)
        except (TypeError, ValueError):
            return 0.0
