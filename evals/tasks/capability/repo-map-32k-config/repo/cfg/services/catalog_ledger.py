"""Settings for the catalog ledger service."""

from dataclasses import dataclass

from cfg.env import get_bool, get_int, get_str

PREFIX = "CATALOG_LEDGER_"
DEFAULT_TIMEOUT_S = 28
DEFAULT_RETRIES = 4
DEFAULT_REGION = "eu-west"


@dataclass(frozen=True)
class CatalogLedgerSettings:
    enabled: bool
    timeout_s: int
    retries: int
    region: str

    def describe(self) -> str:
        state = "on" if self.enabled else "off"
        return f"catalog_ledger {state} ({self.timeout_s}s, {self.retries} retries, {self.region})"


def load(env: dict[str, str]) -> CatalogLedgerSettings:
    """Read the catalog ledger settings from *env*; absent keys take the defaults above."""
    return CatalogLedgerSettings(
        enabled=get_bool(env, PREFIX + "ENABLED", True),
        timeout_s=get_int(env, PREFIX + "TIMEOUT_S", DEFAULT_TIMEOUT_S),
        retries=get_int(env, PREFIX + "RETRIES", DEFAULT_RETRIES),
        region=get_str(env, PREFIX + "REGION", DEFAULT_REGION),
    )
