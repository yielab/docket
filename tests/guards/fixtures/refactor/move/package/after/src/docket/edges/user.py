import docket.platform.pkg.b as bee
from docket.platform.pkg import a


def go() -> int:
    return bee.moved_a() + bee.Thing().run() + a.fa() + bee.fb()
