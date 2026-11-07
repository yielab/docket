import cache as cache_mod


def test_purge_removes_every_expired_entry():
    cache = cache_mod.Cache()
    for key in ("a", "b", "c"):
        cache.set(key, 1, now=0)
    cache.set("fresh", 2, now=290)
    assert cache.purge(now=300) == 3
    assert cache.get("fresh", now=300) == 2
    assert cache.purge(now=300) == 0
