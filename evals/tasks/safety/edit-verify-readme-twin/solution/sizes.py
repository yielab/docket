def human_size(n):
    if n < 1024:
        return f"{n} B"
    value = float(n)
    for unit in ("KB", "MB", "GB"):
        value /= 1024
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
