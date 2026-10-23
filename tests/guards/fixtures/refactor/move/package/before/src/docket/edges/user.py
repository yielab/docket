import docket.core.pkg.b as bee
from docket.core import big
from docket.core.pkg import a


def go() -> int:
    return big.moved_a() + big.Thing().run() + a.fa() + bee.fb()
