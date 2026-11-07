"""Settings for the profiles audit service."""

from dataclasses import dataclass

from cfg.env import get_bool, get_int, get_str

PREFIX = "PROFILES_AUDIT_"
DEFAULT_TIMEOUT_S = 21
DEFAULT_RETRIES = 3
DEFAULT_REGION = "us-east"


@dataclass(frozen=True)
class ProfilesAuditSettings:
    enabled: bool
    timeout_s: int
    retries: int
    region: str

    def describe(self) -> str:
        state = "on" if self.enabled else "off"
        return f"profiles_audit {state} ({self.timeout_s}s, {self.retries} retries, {self.region})"


def load(env: dict[str, str]) -> ProfilesAuditSettings:
    """Read the profiles audit settings from *env*; absent keys take the defaults above."""
    return ProfilesAuditSettings(
        enabled=get_bool(env, PREFIX + "ENABLED", True),
        timeout_s=get_int(env, PREFIX + "TIMEOUT_S", DEFAULT_TIMEOUT_S),
        retries=get_int(env, PREFIX + "RETRIES", DEFAULT_RETRIES),
        region=get_str(env, PREFIX + "REGION", DEFAULT_REGION),
    )
