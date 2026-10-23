"""Toy test module: patches by module object, by string and by mock."""

import os
from unittest import mock

import toy.core.engine as engine
from toy.core import queue, state


def case_patches(monkeypatch, thing):
    monkeypatch.setattr(engine, "claim_next", None)
    monkeypatch.setattr(queue, "render", None)
    monkeypatch.setattr("toy.core.queue.store_write", None)
    monkeypatch.setattr(state, "finish", None)
    monkeypatch.setattr(queue, "state", None)
    monkeypatch.setattr(os, "environ", {})
    monkeypatch.setattr(thing, "attr", 1)
    with mock.patch("toy.core.state.finish"):
        pass
