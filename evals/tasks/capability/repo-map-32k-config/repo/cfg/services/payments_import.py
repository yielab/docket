"""Settings for the payments import service."""

from dataclasses import dataclass

from cfg.env import get_bool, get_int, get_str

PREFIX = "PAYMENTS_IMPORT_"
DEFAULT_TIMEOUT_S = 36
DEFAULT_RETRIES = 3
DEFAULT_REGION = "ap-south"


@dataclass(frozen=True)
class PaymentsImportSettings:
    enabled: bool
    timeout_s: int
    retries: int
    region: str

    def describe(self) -> str:
        state = "on" if self.enabled else "off"
        return f"payments_import {state} ({self.timeout_s}s, {self.retries} retries, {self.region})"


def load(env: dict[str, str]) -> PaymentsImportSettings:
    """Read the payments import settings from *env*; absent keys take the defaults above."""
    return PaymentsImportSettings(
        enabled=get_bool(env, PREFIX + "ENABLED", True),
        timeout_s=get_int(env, PREFIX + "TIMEOUT_S", DEFAULT_TIMEOUT_S),
        retries=get_int(env, PREFIX + "RETRIES", DEFAULT_RETRIES),
        region=get_str(env, PREFIX + "REGION", DEFAULT_REGION),
    )
