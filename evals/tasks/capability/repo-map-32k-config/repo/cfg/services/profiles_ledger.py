"""Settings for the profiles ledger service."""

from dataclasses import dataclass

from cfg.env import get_bool, get_int, get_str

PREFIX = "PROFILES_LEDGER_"
DEFAULT_TIMEOUT_S = 56
DEFAULT_RETRIES = 3
DEFAULT_REGION = "eu-west"


@dataclass(frozen=True)
class ProfilesLedgerSettings:
    enabled: bool
    timeout_s: int
    retries: int
    region: str

    def describe(self) -> str:
        state = "on" if self.enabled else "off"
        return f"profiles_ledger {state} ({self.timeout_s}s, {self.retries} retries, {self.region})"


def load(env: dict[str, str]) -> ProfilesLedgerSettings:
    """Read the profiles ledger settings from *env*; absent keys take the defaults above."""
    return ProfilesLedgerSettings(
        enabled=get_bool(env, PREFIX + "ENABLED", True),
        timeout_s=get_int(env, PREFIX + "TIMEOUT_S", DEFAULT_TIMEOUT_S),
        retries=get_int(env, PREFIX + "RETRIES", DEFAULT_RETRIES),
        region=get_str(env, PREFIX + "REGION", DEFAULT_REGION),
    )
