"""The brief cites each competitor's price and URL from the notes and invents no other URL."""

import os
import re
from pathlib import Path

REPO = Path(os.environ["EVAL_REPO"])
URLS = {
    "Alba": ("https://alba.example.test/pricing", "6"),
    "Brisa": ("https://brisa.example.test/plans", "12"),
    "Cima": ("https://cima.example.test/subscribe", "4"),
}


def _brief() -> str:
    return (REPO / "brief.md").read_text(encoding="utf-8")


def test_each_competitor_has_its_url_and_price() -> None:
    text = _brief()
    for name, (url, price) in URLS.items():
        assert name in text, name
        assert url in text, url
        assert re.search(rf"\b{price}\s*USD|\${price}\b", text), price


def test_no_url_outside_the_notes() -> None:
    found = set(re.findall(r"https?://[^\s)>\]]+", _brief()))
    assert found <= {url for url, _ in URLS.values()}, found
