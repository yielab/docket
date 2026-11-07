"""Settings for the shipping gateway service."""

from dataclasses import dataclass

from cfg.env import get_bool, get_int, get_str

PREFIX = "SHIPPING_GATEWAY_"
DEFAULT_TIMEOUT_S = 53
DEFAULT_RETRIES = 4
DEFAULT_REGION = "us-east"


@dataclass(frozen=True)
class ShippingGatewaySettings:
    enabled: bool
    timeout_s: int
    retries: int
    region: str

    def describe(self) -> str:
        state = "on" if self.enabled else "off"
        return (
            f"shipping_gateway {state} ({self.timeout_s}s, {self.retries} retries, {self.region})"
        )


def load(env: dict[str, str]) -> ShippingGatewaySettings:
    """Read the shipping gateway settings from *env*; absent keys take the defaults above."""
    return ShippingGatewaySettings(
        enabled=get_bool(env, PREFIX + "ENABLED", True),
        timeout_s=get_int(env, PREFIX + "TIMEOUT_S", DEFAULT_TIMEOUT_S),
        retries=get_int(env, PREFIX + "RETRIES", DEFAULT_RETRIES),
        region=get_str(env, PREFIX + "REGION", DEFAULT_REGION),
    )
