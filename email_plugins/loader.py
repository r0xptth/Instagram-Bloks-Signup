"""Load email_plugins/<name>.py (or .json)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, List

_DIR = Path(__file__).resolve().parent

_SKIP = {
    "__init__.py",
    "base.py",
    "loader.py",
    "messages.py",
    "adapter.py",
}


def list_providers() -> List[str]:
    names: List[str] = []
    for p in sorted(_DIR.iterdir()):
        if p.name.startswith("_") or p.name.startswith("."):
            continue
        if p.name in _SKIP:
            continue
        if p.suffix in (".py", ".json"):
            names.append(p.stem)
    return sorted(set(names))


def load_provider(name: str, **kwargs: Any) -> Any:
    name = (name or "").strip().lower().replace(".py", "").replace(".json", "")
    if not name:
        raise ValueError("empty email provider name")

    py_path = _DIR / f"{name}.py"
    json_path = _DIR / f"{name}.json"

    if py_path.is_file():
        return _load_python(name, py_path, **kwargs)
    if json_path.is_file():
        return _load_json(name, json_path, **kwargs)

    available = ", ".join(list_providers()) or "(none)"
    raise FileNotFoundError(
        f"email plugin not found: {name!r} (have: {available})"
    )


def _validate_client(client: Any, name: str) -> Any:
    for required in ("create_order", "wait_for_code", "cancel_order"):
        if not hasattr(client, required):
            raise TypeError(
                f"email plugin {name!r} is missing required method/function "
                f"{required}()"
            )
    return client


def _load_python(name: str, path: Path, **kwargs: Any) -> Any:
    mod_name = f"email_plugins.{name}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load email plugin {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)

    from .adapter import ExportedEmailClient, collect_exports

    exports = collect_exports(mod)
    if "create_order" in exports and "cancel_order" in exports and (
        "wait_for_code" in exports or "get_code" in exports or "fetch_code" in exports
    ):
        # EXPORTS path, unless this module exposes a class client instead
        if hasattr(mod, "EXPORTS") or not (
            hasattr(mod, "make_client") or hasattr(mod, "Client") or hasattr(mod, "Provider")
        ):
            return _validate_client(
                ExportedEmailClient(exports, name=name, **kwargs), name
            )

    if hasattr(mod, "make_client"):
        client = mod.make_client(**kwargs)
    elif hasattr(mod, "Provider"):
        client = mod.Provider(**kwargs)
    elif hasattr(mod, "Client"):
        client = mod.Client(**kwargs)
    elif exports:
        return _validate_client(
            ExportedEmailClient(exports, name=name, **kwargs), name
        )
    else:
        client = mod
    return _validate_client(client, name)


def _load_json(name: str, path: Path, **kwargs: Any) -> Any:
    from .base import RestEmailProvider

    with path.open(encoding="utf-8") as fh:
        config = json.load(fh)
    if not isinstance(config, dict):
        raise TypeError(f"{path.name} must be a JSON object")
    config.setdefault("name", name)
    return _validate_client(RestEmailProvider(config, **kwargs), name)
