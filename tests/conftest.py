import json
from pathlib import Path

import pytest

from consent_audit.detect import RequestRecord

FIX = Path(__file__).parent / "fixtures"


def load_har(name: str) -> list[RequestRecord]:
    data = json.loads((FIX / name).read_text(encoding="utf-8"))
    out = []
    for entry in data["log"]["entries"]:
        req = entry["request"]
        out.append(
            RequestRecord(
                url=req["url"],
                method=req.get("method", "GET"),
                post_data=(req.get("postData", {}) or {}).get("text", ""),
            )
        )
    return out


def load_html(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


@pytest.fixture
def bad_requests():
    return load_har("bad_site.har")


@pytest.fixture
def bad_html():
    return load_html("bad_site.html")


@pytest.fixture
def good_requests():
    return load_har("good_site.har")


@pytest.fixture
def good_html():
    return load_html("good_site.html")
