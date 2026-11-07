"""Settings for the search ledger service."""

from dataclasses import dataclass

from cfg.env import get_bool, get_int, get_str

PREFIX = "SEARCH_LEDGER_"
DEFAULT_TIMEOUT_S = 54
DEFAULT_RETRIES = 2
DEFAULT_REGION = "eu-west"


@dataclass(frozen=True)
class SearchLedgerSettings:
    enabled: bool
    timeout_s: int
    retries: int
    region: str

    def describe(self) -> str:
        state = "on" if self.enabled else "off"
        return f"search_ledger {state} ({self.timeout_s}s, {self.retries} retries, {self.region})"


def load(env: dict[str, str]) -> SearchLedgerSettings:
    """Read the search ledger settings from *env*; absent keys take the defaults above."""
    return SearchLedgerSettings(
        enabled=get_bool(env, PREFIX + "ENABLED", True),
        timeout_s=get_int(env, PREFIX + "TIMEOUT_S", DEFAULT_TIMEOUT_S),
        retries=get_int(env, PREFIX + "RETRIES", DEFAULT_RETRIES),
        region=get_str(env, PREFIX + "REGION", DEFAULT_REGION),
    )
