"""Transport observations count ASGI bytes and distinguish HEAD/ranges/disconnects."""

from uuid import uuid4

import anyio
import pytest

from app.domains.distribution import statistics


@pytest.mark.parametrize(
    "method,headers,expected_bytes,partial",
    [
        ("GET", [], 10, 0),
        ("HEAD", [], 0, 0),
        ("GET", [(b"range", b"bytes=2-5")], 4, 1),
    ],
)
def test_observed_response_counts_only_sent_body(
    tmp_path, monkeypatch, method, headers, expected_bytes, partial
):
    path = tmp_path / "package.apk"
    path.write_bytes(b"0123456789")
    observations, messages = [], []
    monkeypatch.setattr(statistics, "record_observation", lambda *args: observations.append(args))
    app_id = uuid4()
    response = statistics.ObservedFileResponse(
        path, statistics_engine=None, statistics_app_id=app_id
    )

    async def run():
        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(message):
            messages.append(message)

        await response(
            {
                "type": "http",
                "method": method,
                "headers": headers,
                "extensions": {"http.response.pathsend": {}},
            },
            receive,
            send,
        )

    anyio.run(run)
    assert len(observations) == 1 and observations[0][1] == app_id
    assert observations[0][-1] == {
        "local_get_requests": int(method == "GET"),
        "local_head_requests": int(method == "HEAD"),
        "partial_get_requests": partial,
        "interrupted_get_requests": 0,
        "observed_bytes": expected_bytes,
    }
    assert all(message["type"] != "http.response.pathsend" for message in messages)


def test_disconnect_counts_only_completed_send_and_preserves_error(tmp_path, monkeypatch):
    path = tmp_path / "package.apk"
    path.write_bytes(b"0123456789")
    observations = []
    monkeypatch.setattr(statistics, "record_observation", lambda *args: observations.append(args))
    response = statistics.ObservedFileResponse(
        path, statistics_engine=None, statistics_app_id=uuid4()
    )
    response.chunk_size = 3

    async def run():
        chunks = 0

        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(message):
            nonlocal chunks
            if message["type"] == "http.response.body":
                chunks += 1
                if chunks == 2:
                    raise OSError("client disconnected")

        await response({"type": "http", "method": "GET", "headers": []}, receive, send)

    with pytest.raises(OSError):
        anyio.run(run)
    assert observations[0][-1]["interrupted_get_requests"] == 1
    assert observations[0][-1]["observed_bytes"] == 3


def test_statistics_failure_never_breaks_file_response(tmp_path, monkeypatch):
    path = tmp_path / "package.apk"
    path.write_bytes(b"file")

    def unavailable(*args):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(statistics, "record_observation", unavailable)
    response = statistics.ObservedFileResponse(
        path, statistics_engine=None, statistics_app_id=uuid4()
    )

    async def run():
        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(message):
            pass

        await response({"type": "http", "method": "GET", "headers": []}, receive, send)

    anyio.run(run)
