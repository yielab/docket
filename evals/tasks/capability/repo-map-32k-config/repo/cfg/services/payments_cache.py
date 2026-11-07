"""Settings for the payments cache service."""

from dataclasses import dataclass

from cfg.env import get_bool, get_int, get_str

PREFIX = "PAYMENTS_CACHE_"
DEFAULT_TIMEOUT_S = 15
DEFAULT_RETRIES = 0
DEFAULT_REGION = "ap-south"


@dataclass(frozen=True)
class PaymentsCacheSettings:
    enabled: bool
    timeout_s: int
    retries: int
    region: str

    def describe(self) -> str:
        state = "on" if self.enabled else "off"
        return f"payments_cache {state} ({self.timeout_s}s, {self.retries} retries, {self.region})"


def load(env: dict[str, str]) -> PaymentsCacheSettings:
    """Read the payments cache settings from *env*; absent keys take the defaults above."""
    return PaymentsCacheSettings(
        enabled=get_bool(env, PREFIX + "ENABLED", True),
        timeout_s=get_int(env, PREFIX + "TIMEOUT_S", DEFAULT_TIMEOUT_S),
        retries=get_int(env, PREFIX + "RETRIES", DEFAULT_RETRIES),
        region=get_str(env, PREFIX + "REGION", DEFAULT_REGION),
    )
