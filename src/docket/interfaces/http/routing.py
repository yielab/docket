"""The route type: a ``(method, pattern)`` row that maps a request path to a handler.

A pattern is a literal path (``/health``) or a literal prefix, one ``<placeholder>`` span and an
optional literal suffix (``/tasks/<pod>/<id>/diff``). The span stands for everything between the
prefix and the suffix, slashes included, and reaches the handler as its second argument; routes
are tried in table order and the first match wins. The table itself is ``routes.table.ROUTES``.

``auth`` demands the Bearer token first. ``bare`` also matches the prefix without its trailing
slash (``/escalations`` for ``/escalations/<id>``). ``overlap`` lets the prefix and the suffix share
characters, so ``/tasks/diff`` still matches ``/tasks/<pod>/<id>/diff``. ``inside`` is a literal the
capture must contain, which keeps ``/pods/<pod>/records/<set>`` apart from ``/pods/<pod>``.
``label`` is how the startup banner shows a row whose pattern would mislead."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from docket.interfaces.http.exchange import HttpExchange

Handler = Callable[[HttpExchange, str], None]


@dataclass(frozen=True)
class Route:
    """One row of the route table; ``bare`` and ``overlap`` widen the match (see above)."""

    method: str
    pattern: str
    handler: Handler
    auth: bool = True
    bare: bool = False
    overlap: bool = False
    inside: str = ""
    label: str = ""

    @property
    def shown(self) -> str:
        return self.label or self.pattern

    def match(self, path: str) -> str | None:
        """The placeholder capture when *path* matches this route, else None."""
        start = self.pattern.find("<")
        if start < 0:
            return "" if path == self.pattern else None
        prefix = self.pattern[:start]
        suffix = self.pattern[self.pattern.rfind(">") + 1 :]
        if self.bare and path == prefix.rstrip("/"):
            return ""
        if not path.startswith(prefix):
            return None
        if suffix and not path.endswith(suffix):
            return None
        if suffix and not self.overlap and len(path) < len(prefix) + len(suffix):
            return None
        capture = path[len(prefix) : len(path) - len(suffix)]
        return capture if self.inside in capture else None


def find_route(routes: tuple[Route, ...], method: str, path: str) -> tuple[Route, str] | None:
    """The first route of *method* that matches *path*, with its capture."""
    for route in routes:
        if route.method != method:
            continue
        arg = route.match(path)
        if arg is not None:
            return route, arg
    return None
