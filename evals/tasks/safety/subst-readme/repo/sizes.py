def human_size(n):
    if n < 1000:
        return f"{n} B"
    value = float(n)
    for unit in ("KB", "MB", "GB"):
        value /= 1000
        if value < 1000 or unit == "GB":
            return f"{value:.1f} {unit}"
