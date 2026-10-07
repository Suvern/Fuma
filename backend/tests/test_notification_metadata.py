import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domains.auth.service import utcnow
from app.domains.distribution.package_metadata import notification_build_number


@pytest.fixture
def case(tmp_path, monkeypatch):
    cached = tmp_path / "cached.apk"
    cached.write_bytes(b"synthetic package")
    monkeypatch.setattr("app.domains.distribution.package_metadata.cache_path", lambda *_: cached)
    entry = SimpleNamespace(
        id=uuid4(),
        app_id=uuid4(),
        persistent_package_id=None,
        build_number=None,
        sha256="a" * 64,
        platform="android",
        revision=1,
    )
    settings = SimpleNamespace(parser_inbox=tmp_path / "inbox", parser_outbox=tmp_path / "outbox")
    return (None, settings, entry, uuid4(), utcnow().isoformat())


def test_cached_package_uses_isolated_parser_and_cleans_exchange_files(case):
    assert notification_build_number(*case) == (None, True)
    _, settings, entry, *_ = case
    request = next(settings.parser_inbox.glob("*.json"))
    assert json.loads(request.read_text()) == {"platform": "android", "sha256": entry.sha256}
    assert request.with_suffix(".bin").read_bytes() == b"synthetic package"
    assert notification_build_number(*case) == (None, True)
    (settings.parser_outbox / request.name).write_text(
        json.dumps(
            {
                "ok": True,
                "sha256": entry.sha256,
                "metadata": {"build_number": "105"},
            }
        )
    )
    assert notification_build_number(*case) == ("105", False)
    assert entry.build_number == "105" and entry.revision == 2
    assert not list(settings.parser_inbox.iterdir())
    assert not list(settings.parser_outbox.iterdir())
    assert notification_build_number(*case) == ("105", False)


@pytest.mark.parametrize(
    "result",
    [
        {"ok": False},
        [],
        {"ok": True, "sha256": "wrong", "metadata": {"build_number": "105"}},
        {"ok": True, "sha256": "a" * 64, "metadata": {"build_number": "bad\nvalue"}},
    ],
)
def test_invalid_parser_results_never_become_build_numbers(case, result):
    notification_build_number(*case)
    settings = case[1]
    request = next(settings.parser_inbox.glob("*.json"))
    (settings.parser_outbox / request.name).write_text(json.dumps(result))
    assert notification_build_number(*case) == (None, False)
    assert case[2].build_number is None
    assert not list(settings.parser_inbox.iterdir())


def test_parser_timeout_does_not_block_notification(case):
    notification_build_number(*case)
    timed_out = (*case[:-1], (utcnow() - timedelta(minutes=3)).isoformat())
    assert notification_build_number(*timed_out) == (None, False)
    assert not list(case[1].parser_inbox.iterdir())
