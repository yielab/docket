import cache as cache_mod


def test_a_fresh_value_is_returned():
    cache = cache_mod.Cache()
    cache.set("session:42", "alice", now=0)
    assert cache.get("session:42", now=299) == "alice"


def test_an_old_value_is_gone():
    cache = cache_mod.Cache()
    cache.set("session:42", "alice", now=0)
    assert cache.get("session:42", now=400) is None
