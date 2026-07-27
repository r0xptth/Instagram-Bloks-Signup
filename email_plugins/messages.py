"""Return types for email plugins. Dicts with the same keys also work."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Union


@dataclass
class OrderMessage:

    ok: bool
    order_id: str = ""
    email: str = ""
    error: str = ""
    raw: Any = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "order_id": self.order_id,
            "email": self.email,
            "error": self.error,
        }


@dataclass
class CodeMessage:
    ok: bool
    code: str = ""
    error: str = ""
    pending: bool = False  # keep polling
    raw: Any = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "code": self.code,
            "error": self.error,
            "pending": self.pending,
        }


@dataclass
class CancelMessage:

    ok: bool = True
    error: str = ""
    raw: Any = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "error": self.error}


@dataclass
class BalanceMessage:

    ok: bool = True
    balance: float = 0.0
    error: str = ""
    raw: Any = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "balance": self.balance, "error": self.error}


Message = Union[OrderMessage, CodeMessage, CancelMessage, BalanceMessage, Dict[str, Any]]


def as_order(msg: Any) -> OrderMessage:
    if isinstance(msg, OrderMessage):
        return msg
    if isinstance(msg, tuple) and len(msg) == 2:
        oid, email = msg
        if oid and email:
            return OrderMessage(ok=True, order_id=str(oid), email=str(email))
        return OrderMessage(ok=False, error="empty order_id/email")
    if isinstance(msg, dict):
        ok = bool(msg.get("ok", True))
        oid = str(msg.get("order_id") or msg.get("id") or "")
        email = str(msg.get("email") or "")
        err = str(msg.get("error") or msg.get("message") or "")
        if ok and oid and email:
            return OrderMessage(ok=True, order_id=oid, email=email, raw=msg)
        return OrderMessage(
            ok=False,
            order_id=oid,
            email=email,
            error=err or "create_order failed",
            raw=msg,
        )
    raise TypeError(
        f"create_order must return OrderMessage, dict, or (order_id, email); got {type(msg)}"
    )


def as_code(msg: Any) -> CodeMessage:
    if isinstance(msg, CodeMessage):
        return msg
    if msg is None:
        return CodeMessage(ok=False, pending=True)
    if isinstance(msg, str):
        code = msg.strip()
        if code:
            return CodeMessage(ok=True, code=code)
        return CodeMessage(ok=False, pending=True)
    if isinstance(msg, dict):
        code = str(msg.get("code") or "").strip()
        pending = bool(msg.get("pending", False))
        err = str(msg.get("error") or msg.get("message") or "")
        ok = bool(msg.get("ok", bool(code)))
        if code:
            return CodeMessage(ok=True, code=code, raw=msg)
        if pending or msg.get("ok") is True and not code:
            return CodeMessage(ok=False, pending=True, raw=msg)
        return CodeMessage(ok=False, pending=False, error=err or "no code", raw=msg)
    raise TypeError(
        f"code function must return CodeMessage, dict, str, or None; got {type(msg)}"
    )


def as_cancel(msg: Any) -> CancelMessage:
    if msg is None:
        return CancelMessage(ok=True)
    if isinstance(msg, CancelMessage):
        return msg
    if isinstance(msg, dict):
        return CancelMessage(
            ok=bool(msg.get("ok", True)),
            error=str(msg.get("error") or ""),
            raw=msg,
        )
    return CancelMessage(ok=True)


def as_balance(msg: Any) -> BalanceMessage:
    if isinstance(msg, BalanceMessage):
        return msg
    if isinstance(msg, (int, float)):
        return BalanceMessage(ok=True, balance=float(msg))
    if isinstance(msg, dict):
        try:
            bal = float(msg.get("balance") or 0)
        except (TypeError, ValueError):
            bal = 0.0
        return BalanceMessage(
            ok=bool(msg.get("ok", True)),
            balance=bal,
            error=str(msg.get("error") or ""),
            raw=msg,
        )
    return BalanceMessage(ok=False, error=f"bad balance payload: {type(msg)}")
