"""Wrap plugin EXPORTS for the signup client."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, Optional

from .messages import (
    as_balance,
    as_cancel,
    as_code,
    as_order,
)

logger = logging.getLogger(__name__)

REQUIRED = ("create_order", "cancel_order")


class ExportedEmailClient:
    contactpoint_type = "EMAIL"

    def __init__(
        self,
        exports: Dict[str, Callable[..., Any]],
        *,
        name: str = "custom",
        poll_interval: float = 5.0,
        **_: Any,
    ):
        missing = [k for k in REQUIRED if k not in exports or not callable(exports[k])]
        if missing:
            raise TypeError(f"email plugin {name!r} EXPORTS missing: {', '.join(missing)}")
        has_wait = callable(exports.get("wait_for_code"))
        has_poll = callable(exports.get("get_code")) or callable(exports.get("fetch_code"))
        if not has_wait and not has_poll:
            raise TypeError(
                f"email plugin {name!r} needs wait_for_code and/or get_code"
            )
        self._exports = exports
        self.name = name
        self.poll_interval = float(poll_interval)

    def _call(self, key: str, *args: Any, **kwargs: Any) -> Any:
        fn = self._exports.get(key)
        if not callable(fn):
            raise AttributeError(key)
        return fn(*args, **kwargs)

    def create_order(
        self,
        site: str = "instagram.com",
        domain: Optional[str] = None,
        attempt: int = 0,
    ):
        msg = as_order(
            self._call(
                "create_order",
                site=site,
                domain=domain,
                attempt=attempt,
            )
        )
        if not msg.ok:
            raise RuntimeError(msg.error or f"{self.name}: create_order failed")
        logger.info("[%s] ordered %s (id %s)", self.name, msg.email, msg.order_id)
        return msg.order_id, msg.email

    def get_code(self, order_id: str):
        key = "get_code" if callable(self._exports.get("get_code")) else "fetch_code"
        return as_code(self._call(key, order_id))

    def wait_for_code(
        self,
        order_id: str,
        timeout: int = 180,
        interval: Optional[float] = None,
        exclude_codes: Optional[list] = None,
    ):
        exclude = set(exclude_codes or [])
        if callable(self._exports.get("wait_for_code")):
            msg = as_code(
                self._call(
                    "wait_for_code",
                    order_id,
                    timeout=timeout,
                    interval=interval if interval is not None else self.poll_interval,
                    exclude_codes=list(exclude) or None,
                )
            )
            if msg.ok and msg.code and msg.code not in exclude:
                logger.info("[%s] code received", self.name)
                return msg.code
            return None

        gap = float(interval if interval is not None else self.poll_interval)
        gap = max(1.0, gap)
        deadline = time.time() + timeout
        logger.info("[%s] waiting for code (%ss)", self.name, timeout)
        while time.time() < deadline:
            try:
                msg = self.get_code(order_id)
            except Exception as exc:
                logger.warning("[%s] poll error: %s", self.name, exc)
                msg = as_code(None)
            if msg.ok and msg.code and msg.code not in exclude:
                logger.info("[%s] code received", self.name)
                return msg.code
            if msg.error and not msg.pending:
                logger.warning("[%s] code error: %s", self.name, msg.error)
            time.sleep(gap)
        return None

    def cancel_order(self, order_id: str) -> None:
        try:
            msg = as_cancel(self._call("cancel_order", order_id))
            if msg.ok:
                logger.info("[%s] cancelled order %s", self.name, order_id)
            elif msg.error:
                logger.debug("[%s] cancel: %s", self.name, msg.error)
        except Exception as exc:
            logger.debug("[%s] cancel %s: %s", self.name, order_id, exc)

    def get_balance(self) -> float:
        if not callable(self._exports.get("get_balance")):
            return 0.0
        msg = as_balance(self._call("get_balance"))
        if not msg.ok:
            raise RuntimeError(msg.error or "get_balance failed")
        return float(msg.balance)

    def release_order_slot(self) -> None:
        fn = self._exports.get("release_order_slot")
        if callable(fn):
            fn()


def collect_exports(module: Any) -> Dict[str, Callable[..., Any]]:
    if hasattr(module, "EXPORTS") and isinstance(module.EXPORTS, dict):
        return {str(k): v for k, v in module.EXPORTS.items() if callable(v)}

    names = (
        "create_order",
        "wait_for_code",
        "get_code",
        "fetch_code",
        "cancel_order",
        "get_balance",
        "release_order_slot",
    )
    out: Dict[str, Callable[..., Any]] = {}
    for name in names:
        fn = getattr(module, name, None)
        if callable(fn):
            out[name] = fn
    return out
