"""Settings for the reports export service."""

from dataclasses import dataclass

from cfg.env import get_bool, get_int, get_str

PREFIX = "REPORTS_EXPORT_"
DEFAULT_TIMEOUT_S = 48
DEFAULT_RETRIES = 4
DEFAULT_REGION = "eu-west"


@dataclass(frozen=True)
class ReportsExportSettings:
    enabled: bool
    timeout_s: int
    retries: int
    region: str

    def describe(self) -> str:
        state = "on" if self.enabled else "off"
        return f"reports_export {state} ({self.timeout_s}s, {self.retries} retries, {self.region})"


def load(env: dict[str, str]) -> ReportsExportSettings:
    """Read the reports export settings from *env*; absent keys take the defaults above."""
    return ReportsExportSettings(
        enabled=get_bool(env, PREFIX + "ENABLED", True),
        timeout_s=get_int(env, PREFIX + "TIMEOUT_S", DEFAULT_TIMEOUT_S),
        retries=get_int(env, PREFIX + "RETRIES", DEFAULT_RETRIES),
        region=get_str(env, PREFIX + "REGION", DEFAULT_REGION),
    )
