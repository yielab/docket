# Request

Cache.get_or_set(key, factory, now): the fresh cached value if there is one, else call factory()
once, store the result at now and return it. A cached value that is falsy (0, '', []) is
still a hit and must not call factory again.
