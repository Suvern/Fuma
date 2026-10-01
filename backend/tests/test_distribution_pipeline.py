"""Real PostgreSQL + HTTP + worker pipeline, synthetic upstream package bytes only."""

import hashlib
import io
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import test_distribution_review as review_helpers
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.distribution import packages
from app.domains.distribution.models import DebugRecord, TaskRecord
from app.domains.distribution.packages import cache_path, cleanup_cache
from app.domains.distribution.service import enqueue
from app.workers.tasks import execute_task

download_fixture = review_helpers.download_fixture
grant_request = review_helpers.grant_request


def package_bytes(content=b"synthetic manifest"):
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("AndroidManifest.xml", content)
    return target.getvalue()


class SyntheticGitHub:
    def __init__(self, payload, snapshot):
        self.payload, self.snapshot = payload, snapshot
        self.asset = {
            "id": 3,
            "name": "debug.apk",
            "size": len(payload),
            "updated_at": snapshot["asset_updated_at"],
            "digest": None,
        }

    def get_repository(self, name):
        return {"id": 1}

    def get_release(self, name, identity):
        return {"id": 2, "draft": False}

    def get_asset(self, name, identity):
        return self.asset

    def list_assets(self, name, identity):
        return [self.asset]

    def download_asset(self, name, identity, destination, expected_size, progress):
        destination.write_bytes(self.payload)
        progress(len(self.payload))
        return {"size_bytes": len(self.payload), "sha256": hashlib.sha256(self.payload).hexdigest()}

    def close(self):
        pass


def cold_package(client, identity, settings, monkeypatch):
    payload = package_bytes()
    with Session(client.app.state.engine) as db:
        row = db.get(DebugRecord, identity)
        cache_path(settings, row).unlink()
        row.cache_state, row.sha256, row.downloaded_bytes = "missing", None, 0
        row.size_bytes = len(payload)
        row.cache_record.cache_state, row.cache_record.sha256 = "missing", None
        row.cache_record.downloaded_bytes, row.cache_record.size_bytes = 0, len(payload)
        row.source = {**row.source, "size_bytes": len(payload)}
        provider = SyntheticGitHub(payload, row.source)
        db.commit()
    monkeypatch.setattr(packages, "get_github_client", lambda *args: provider)
    return payload, provider


def test_cold_cache_worker_and_fresh_grant_real_http(download_fixture, monkeypatch):
    client, identity, csrf, settings = download_fixture
    payload, _ = cold_package(client, identity, settings, monkeypatch)
    first = grant_request(client, identity, csrf)
    assert first.status_code == 202, first.text
    assert "download_url" not in first.json()
    assert grant_request(client, identity, csrf).status_code == 202
    with Session(client.app.state.engine) as db:
        tasks = db.scalars(select(TaskRecord).where(TaskRecord.kind == "cache_download")).all()
        assert len(tasks) == 1
        task_id = tasks[0].id
    execute_task(client.app.state.engine, settings, task_id)
    prepared = client.get(f"/api/v1/catalog/debug-entries/{identity}/preparation")
    assert prepared.json()["state"] == "ready", prepared.text
    grant = grant_request(client, identity, csrf)
    assert grant.status_code == 200, grant.text
    assert grant.json()["sha256"] == hashlib.sha256(payload).hexdigest()
    link = grant.json()["download_url"]
    assert client.get(link).content == payload
    assert client.get(link, headers={"Range": "bytes=-12"}).content == payload[-12:]
    catalog = client.get(f"/api/v1/catalog/debug-entries/{identity}").json()
    assert "source" not in catalog and "repository" not in catalog
    with Session(client.app.state.engine) as db:
        assert db.get(TaskRecord, task_id).state == "succeeded"
        cleanup_cache(db, settings, "all_unleased")
        assert db.get(DebugRecord, identity).cache_state == "ready"


def test_rebuild_compares_first_hash_even_without_upstream_digest(download_fixture, monkeypatch):
    client, identity, csrf, settings = download_fixture
    _, provider = cold_package(client, identity, settings, monkeypatch)
    grant_request(client, identity, csrf)
    with Session(client.app.state.engine) as db:
        task_id = db.scalar(select(TaskRecord.id).where(TaskRecord.kind == "cache_download"))
    execute_task(client.app.state.engine, settings, task_id)
    with Session(client.app.state.engine) as db:
        cleanup_cache(db, settings, "all_unleased")
        row = db.get(DebugRecord, identity)
        assert row.sha256 is not None
        original = row.sha256
    # Same byte count and source metadata, different valid ZIP content.
    provider.payload = package_bytes(b"changed   manifest")
    assert len(provider.payload) == provider.asset["size"]
    grant_request(client, identity, csrf)
    with Session(client.app.state.engine) as db:
        task_id = db.scalar(
            select(TaskRecord.id).where(
                TaskRecord.kind == "cache_download", TaskRecord.state == "queued"
            )
        )
    execute_task(client.app.state.engine, settings, task_id)
    with Session(client.app.state.engine) as db:
        row = db.get(DebugRecord, identity)
        assert row.cache_state == "failed"
        assert row.cache_error_code == "SOURCE_CHANGED"
        assert row.sha256 == original
        assert not cache_path(settings, row).exists()


def test_invalid_package_never_becomes_ready(download_fixture, monkeypatch):
    client, identity, csrf, settings = download_fixture
    _, provider = cold_package(client, identity, settings, monkeypatch)
    provider.payload = b"x" * provider.asset["size"]
    grant_request(client, identity, csrf)
    with Session(client.app.state.engine) as db:
        task_id = db.scalar(select(TaskRecord.id).where(TaskRecord.kind == "cache_download"))
    execute_task(client.app.state.engine, settings, task_id)
    with Session(client.app.state.engine) as db:
        row = db.get(DebugRecord, identity)
        assert row.cache_state == "failed" and row.cache_error_code == "INVALID_PACKAGE"
        assert not cache_path(settings, row).exists()
        assert not list(settings.cache_dir.glob("*.part"))


def test_worker_database_fence_blocks_duplicate_delivery(download_fixture, monkeypatch):
    client, _, _, settings = download_fixture
    entered, release = threading.Event(), threading.Event()
    count = []

    def dispatch(db, cfg, task):
        count.append(task.id)
        entered.set()
        assert release.wait(3)

    monkeypatch.setattr("app.workers.tasks.dispatch", dispatch)
    with Session(client.app.state.engine) as db:
        task = enqueue(db, "cache_cleanup", dedupe_key=str(uuid4()))
        task_id = task.id
        db.commit()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(execute_task, client.app.state.engine, settings, task_id)
        assert entered.wait(3)
        duplicate = pool.submit(execute_task, client.app.state.engine, settings, task_id)
        duplicate.result(timeout=3)
        release.set()
        first.result(timeout=3)
    assert count == [task_id]


def test_live_transfer_lease_protects_cache_after_grant_expires(download_fixture):
    from datetime import timedelta

    from app.domains.auth.service import utcnow
    from app.domains.distribution.models import GrantRecord, TransferLease

    client, identity, csrf, settings = download_fixture
    grant_request(client, identity, csrf)
    with Session(client.app.state.engine) as db:
        for grant in db.scalars(select(GrantRecord)):
            grant.expires_at = utcnow() - timedelta(seconds=1)
        lease = TransferLease(entry_id=identity, expires_at=utcnow() + timedelta(seconds=120))
        db.add(lease)
        db.commit()
        cleanup_cache(db, settings, "all_unleased")
        assert cache_path(settings, db.get(DebugRecord, identity)).exists()
        lease.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
        cleanup_cache(db, settings, "all_unleased")
        assert not cache_path(settings, db.get(DebugRecord, identity)).exists()


def test_quota_rejects_download_before_provider_io(download_fixture, monkeypatch):
    from app.domains.distribution.packages import cache_settings

    client, identity, csrf, settings = download_fixture
    cold_package(client, identity, settings, monkeypatch)
    with Session(client.app.state.engine) as db:
        cfg = cache_settings(db)
        cfg.data = {**cfg.data, "budget_bytes": 1}
        db.commit()
    grant_request(client, identity, csrf)
    with Session(client.app.state.engine) as db:
        task_id = db.scalar(select(TaskRecord.id).where(TaskRecord.kind == "cache_download"))
    execute_task(client.app.state.engine, settings, task_id)
    with Session(client.app.state.engine) as db:
        row = db.get(DebugRecord, identity)
        assert row.cache_state == "failed" and row.cache_error_code == "CACHE_CAPACITY_EXCEEDED"
        assert not cache_path(settings, row).exists()


def test_native_http_slow_download_does_not_block_health(download_fixture):
    import socket
    import time
    from urllib.parse import urlsplit

    import httpx
    import uvicorn

    from app.main import create_app

    client, identity, csrf, settings = download_fixture
    chunk = b"x" * (1024 * 1024)
    checksum = hashlib.sha256()
    with Session(client.app.state.engine) as db:
        row = db.get(DebugRecord, identity)
        with cache_path(settings, row).open("wb") as file:
            for _ in range(32):
                file.write(chunk)
                checksum.update(chunk)
        row.size_bytes = 32 * len(chunk)
        row.sha256 = checksum.hexdigest()
        row.cache_record.size_bytes = row.size_bytes
        row.cache_record.sha256 = row.sha256
        db.commit()
    grant = grant_request(client, identity, csrf).json()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(create_app(settings), access_log=False, log_level="critical")
    )
    runner = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    runner.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        assert server.started
        origin = f"http://127.0.0.1:{port}"
        with httpx.Client(base_url=origin, timeout=5, trust_env=False) as network:
            with network.stream("GET", urlsplit(grant["download_url"]).path) as download:
                assert download.status_code == 200
                chunks = download.iter_bytes(chunk_size=4096)
                assert next(chunks) == b"x" * 4096
                started = time.monotonic()
                result = network.get("/api/v1/health/live")
                assert result.status_code == 200
                assert time.monotonic() - started < 2
    finally:
        server.should_exit = True
        runner.join(timeout=5)
        listener.close()
        assert not runner.is_alive()
