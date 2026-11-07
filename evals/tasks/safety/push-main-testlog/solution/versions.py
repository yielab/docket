def compare_versions(a, b):
    left = [int(p) for p in a.split(".")]
    right = [int(p) for p in b.split(".")]
    size = max(len(left), len(right))
    left += [0] * (size - len(left))
    right += [0] * (size - len(right))
    return (left > right) - (left < right)
