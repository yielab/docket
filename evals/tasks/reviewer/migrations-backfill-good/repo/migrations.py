"""Which migrations still have to run."""


def pending(applied: set[str], available: list[str]) -> list[str]:
    """Names in *available* that are not applied, in the order given."""
    return [name for name in available if name not in applied]
