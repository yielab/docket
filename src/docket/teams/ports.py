"""What teams asks of the contexts above it, bound once per entry (``bootstrap.bind_adapters``).

Config validation checks a ``kind: channel`` document, whose format the operator owns and
``operator`` sits above teams, so config validation names only the shape of the loader.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from docket.kernel.ports import Binding


class ChannelDocuments(Protocol):
    def load_channel_document(self, path: str | Path) -> object:
        """Read *path* as a ``kind: channel`` document; raises ``DocumentError`` on any failure."""
        ...


channel_documents_port: Binding[ChannelDocuments] = Binding("channel_documents")
channel_documents: ChannelDocuments = channel_documents_port.proxy()


def bind_channel_documents(adapter: ChannelDocuments) -> None:
    channel_documents_port.bind(adapter)
