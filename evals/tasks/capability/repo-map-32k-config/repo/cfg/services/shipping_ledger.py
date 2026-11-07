"""Settings for the shipping ledger service."""

from dataclasses import dataclass

from cfg.env import get_bool, get_int, get_str

PREFIX = "SHIPPING_LEDGER_"
DEFAULT_TIMEOUT_S = 17
DEFAULT_RETRIES = 1
DEFAULT_REGION = "eu-west"


@dataclass(frozen=True)
class ShippingLedgerSettings:
    enabled: bool
    timeout_s: int
    retries: int
    region: str

    def describe(self) -> str:
        state = "on" if self.enabled else "off"
        return f"shipping_ledger {state} ({self.timeout_s}s, {self.retries} retries, {self.region})"


def load(env: dict[str, str]) -> ShippingLedgerSettings:
    """Read the shipping ledger settings from *env*; absent keys take the defaults above."""
    return ShippingLedgerSettings(
        enabled=get_bool(env, PREFIX + "ENABLED", True),
        timeout_s=get_int(env, PREFIX + "TIMEOUT_S", DEFAULT_TIMEOUT_S),
        retries=get_int(env, PREFIX + "RETRIES", DEFAULT_RETRIES),
        region=get_str(env, PREFIX + "REGION", DEFAULT_REGION),
    )
