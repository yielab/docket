"""Settings for the auth import service."""

from dataclasses import dataclass

from cfg.env import get_bool, get_int, get_str

PREFIX = "AUTH_IMPORT_"
DEFAULT_TIMEOUT_S = 45
DEFAULT_RETRIES = 0
DEFAULT_REGION = "ap-south"


@dataclass(frozen=True)
class AuthImportSettings:
    enabled: bool
    timeout_s: int
    retries: int
    region: str

    def describe(self) -> str:
        state = "on" if self.enabled else "off"
        return f"auth_import {state} ({self.timeout_s}s, {self.retries} retries, {self.region})"


def load(env: dict[str, str]) -> AuthImportSettings:
    """Read the auth import settings from *env*; absent keys take the defaults above."""
    return AuthImportSettings(
        enabled=get_bool(env, PREFIX + "ENABLED", True),
        timeout_s=get_int(env, PREFIX + "TIMEOUT_S", DEFAULT_TIMEOUT_S),
        retries=get_int(env, PREFIX + "RETRIES", DEFAULT_RETRIES),
        region=get_str(env, PREFIX + "REGION", DEFAULT_REGION),
    )
