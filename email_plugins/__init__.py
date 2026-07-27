"""email plugins package"""

from __future__ import annotations

from .loader import list_providers, load_provider
from .messages import (
    BalanceMessage,
    CancelMessage,
    CodeMessage,
    OrderMessage,
)
from .base import extract_ig_code, http_json

__all__ = [
    "OrderMessage",
    "CodeMessage",
    "CancelMessage",
    "BalanceMessage",
    "http_json",
    "extract_ig_code",
    "list_providers",
    "load_provider",
]
