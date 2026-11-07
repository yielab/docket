"""Settings for the profiles queue service."""

from dataclasses import dataclass

from cfg.env import get_bool, get_int, get_str

PREFIX = "PROFILES_QUEUE_"
DEFAULT_TIMEOUT_S = 13
DEFAULT_RETRIES = 4
DEFAULT_REGION = "us-east"


@dataclass(frozen=True)
class ProfilesQueueSettings:
    enabled: bool
    timeout_s: int
    retries: int
    region: str

    def describe(self) -> str:
        state = "on" if self.enabled else "off"
        return f"profiles_queue {state} ({self.timeout_s}s, {self.retries} retries, {self.region})"


def load(env: dict[str, str]) -> ProfilesQueueSettings:
    """Read the profiles queue settings from *env*; absent keys take the defaults above."""
    return ProfilesQueueSettings(
        enabled=get_bool(env, PREFIX + "ENABLED", True),
        timeout_s=get_int(env, PREFIX + "TIMEOUT_S", DEFAULT_TIMEOUT_S),
        retries=get_int(env, PREFIX + "RETRIES", DEFAULT_RETRIES),
        region=get_str(env, PREFIX + "REGION", DEFAULT_REGION),
    )
