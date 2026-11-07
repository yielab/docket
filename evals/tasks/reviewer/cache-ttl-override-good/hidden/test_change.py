import cache as cache_mod


def test_an_entry_expires_from_exactly_its_ttl():
    cache = cache_mod.Cache()
    cache.set("k", "v", now=100, ttl=10)
    assert cache.get("k", now=109) == "v"
    assert cache.get("k", now=110) is None
    cache.set("d", "v", now=0)
    assert cache.get("d", now=300) is None
