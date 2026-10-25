"""A push notification config as a `kind: channel` webhook document scoped to one task.

Nothing new is stored: the channel catalog already holds destinations, and the notification flush
already delivers to them. ``scopeTask`` and ``scopePod`` in the channel's config are what limit a
channel to one task's events. A credential is never stored (a channel names a secret, it does not
hold one), so a config that brings one is refused."""

from __future__ import annotations

import urllib.parse as _urlparse
from collections.abc import Mapping
from typing import Any

from docket.governance import audit as _audit
from docket.interfaces.http.routes.a2a_rpc import INVALID_PARAMS, RpcError
from docket.operator import ChannelSpec, load_catalog, save_channel
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.state import Status

_ON = ["needs_you", "task.completed", "task.failed", "task.rejected"]
_CREDENTIAL_FIELDS = ("token", "authentication")


def channel_name(task_id: str) -> str:
    return f"a2a-{task_id}"


def channel_for(pod: str, task_id: str, config: Mapping[str, Any]) -> ChannelSpec:
    """The webhook channel that delivers *task_id*'s events to ``config["url"]``."""
    for field in _CREDENTIAL_FIELDS:
        if field in config:
            raise RpcError(
                INVALID_PARAMS,
                f"pushNotificationConfig.{field} is not supported: a channel stores no credential",
                {"reason": "unsupported"},
            )
    url = config.get("url")
    parts = _urlparse.urlsplit(url) if isinstance(url, str) else None
    if parts is None or parts.scheme not in ("http", "https") or not parts.netloc:
        raise RpcError(
            INVALID_PARAMS, "pushNotificationConfig.url must be an http:// or https:// URL"
        )
    return ChannelSpec(
        kind="channel",
        name=channel_name(task_id),
        description=f"A2A push notifications for task {task_id}",
        dialect="webhook",
        enabled=True,
        capabilities=["notify"],
        on=list(_ON),
        content="minimal",
        config={"url": str(url), "scopeTask": task_id, "scopePod": pod},
    )


def store(pod: str, task_id: str, config: Mapping[str, Any]) -> dict[str, str]:
    """Replace the push config of *task_id*; the config as it reads back."""
    spec = channel_for(pod, task_id, config)
    save_channel(spec)
    _audit.audit_log("channel.enable", f"name={spec.name} dialect={spec.dialect} content=minimal")
    return {"url": spec.config["url"]}


def read(task_id: str) -> dict[str, str] | None:
    """The push config of *task_id*, or ``None`` when it has none."""
    spec = load_catalog().get(channel_name(task_id))
    if spec is None or "scopeTask" not in spec.config:
        return None
    return {"url": spec.config.get("url", "")}


def finished_channels() -> list[str]:
    """The push channels whose task is terminal or no longer in its pod's queue, which no event
    will reach again. The sweep removes them after its flush."""
    finished: list[str] = []
    for name, spec in load_catalog().entries.items():
        task_id, pod = spec.config.get("scopeTask"), spec.config.get("scopePod")
        if not name.startswith("a2a-") or not task_id or not pod:
            continue
        task = TaskRepository.for_pod(pod).get(task_id)
        if task is None or task.status in Status.TERMINAL:
            finished.append(name)
    return finished
