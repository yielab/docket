import cache as cache_mod


def test_a_falsy_cached_value_is_a_hit():
    cache = cache_mod.Cache()
    cache.set("k", 0, now=0)
    calls = []
    assert cache.get_or_set("k", lambda: calls.append(1) or 99, now=1) == 0
    assert calls == []
