"""Post-commit cache notification; persistence services never import routers."""
from collections.abc import Callable, Iterable

from app.data.confidence_cache import invalidate_symbol

_listeners: dict[str, Callable[[Iterable[str]], object]] = {}


def register_bars_listener(name: str, listener: Callable[[Iterable[str]], object]) -> None:
    _listeners[name] = listener


def notify_bars_changed(symbol: str) -> None:
    invalidate_symbol(symbol)
    for listener in tuple(_listeners.values()):
        listener([symbol])
