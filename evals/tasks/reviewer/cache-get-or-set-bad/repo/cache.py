"""A small in-process cache for session lookups; time is passed in, never read."""

TTL_S = 300


class Cache:
    def __init__(self) -> None:
        self._items: dict[str, tuple[float, object]] = {}

    def set(self, key: str, value: object, now: float) -> None:
        self._items[key] = (now, value)

    def get(self, key: str, now: float) -> object | None:
        """The value, or None when absent or 300 s old (expired from exactly 300 s on)."""
        item = self._items.get(key)
        if item is None:
            return None
        stored, value = item
        if now - stored >= TTL_S:
            del self._items[key]
            return None
        return value
