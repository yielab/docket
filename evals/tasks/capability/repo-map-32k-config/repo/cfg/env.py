"""Typed readers over a mapping of environment variables."""

TRUE_WORDS = frozenset({"1", "true", "yes", "on"})


def get_str(env: dict[str, str], key: str, default: str) -> str:
    return env.get(key, default)


def get_int(env: dict[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    return default if raw is None else int(raw)


def get_bool(env: dict[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    return default if raw is None else raw.strip().lower() in TRUE_WORDS
