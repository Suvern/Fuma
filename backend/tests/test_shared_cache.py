"""One source snapshot has one cache, independent of per-App authorization."""

import hashlib
import io
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.domains.applications.models import AppRecord
from app.domains.auth.service import utcnow
from app.domains.distribution.models import (
    CacheRecord,
    DebugRecord,
    GrantRecord,
    TaskRecord,
    TransferLease,
)
from app.domains.distribution.packages import (
    cache_path,
    cache_settings,
    cache_usage,
    cleanup_cache,
    download_cache,
    ensure_cache,
    mark_cache_failed,
    mark_cache_missing,
    source_cache,
    touch_cache,
)
from app.domains.distribution.service import RetryLater, digest
from app.infrastructure import models  # noqa: F401
from app.infrastructure.database import Base, build_engine


def package_bytes(content="a"):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as output:
        output.writestr("AndroidManifest.xml", content)
    return data.getvalue()


@pytest.fixture
def shared(tmp_path):
    settings = Settings(
        database_url="postgresql+psycopg://fuma@127.0.0.1:55432/fuma_shared_cache_test",
        cache_dir=tmp_path,
    )
    engine = build_engine(settings)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except Exception:
        engine.dispose()
        pytest.skip("isolated native PostgreSQL fuma_shared_cache_test unavailable")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    data = package_bytes()
    source = {
        "repository_id": "42",
        "repository_full_name": "team/mobile",
        "release_id": "3",
        "asset_id": "4",
        "asset_updated_at": "2026-10-01T00:00:00Z",
        "size_bytes": len(data),
        "digest": None,
    }
    entry_ids, app_ids = [], []
    with Session(engine) as db:
        for number in range(2):
            app = AppRecord(
                name=f"App {number}",
                public_slug=f"app-{number}",
                platforms=["android"],
                created_at=utcnow(),
                updated_at=utcnow(),
                enabled=True,
            )
            db.add(app)
            db.flush()
            entry = DebugRecord(
                app_id=app.id,
                source_identity=digest(source),
                source=source,
                connector_id=uuid4(),
                file_name="demo.apk",
                size_bytes=len(data),
                platform="android",
                source_tag="v1",
                created_at=utcnow(),
                updated_at=utcnow(),
                cache_state="missing",
                enabled=True,
            )
            db.add(entry)
            db.flush()
            entry_ids.append(entry.id)
            app_ids.append(app.id)
        db.commit()
    yield engine, settings, entry_ids, app_ids, data
    engine.dispose()


class Provider:
    def __init__(self, data):
        self.data = data
        self.downloads = 0
        self.entered = threading.Event()
        self.release = None

    def close(self):
        pass

    def get_repository(self, *args):
        return {"id": 42}

    def get_release(self, *args):
        return {"id": 3, "draft": False}

    def get_asset(self, *args):
        return {
            "id": 4,
            "name": "demo.apk",
            "size": len(self.data),
            "updated_at": "2026-10-01T00:00:00Z",
            "digest": None,
        }

    def list_assets(self, *args):
        return [self.get_asset()]

    def download_asset(self, name, identity, destination, size, progress):
        self.downloads += 1
        self.entered.set()
        if self.release is not None:
            assert self.release.wait(10)
        destination.write_bytes(self.data)
        return {"size_bytes": len(self.data), "sha256": hashlib.sha256(self.data).hexdigest()}


def test_two_apps_share_concurrent_enqueue_file_and_budget(shared, monkeypatch):
    engine, settings, ids, _, data = shared
    provider = Provider(data)
    monkeypatch.setattr("app.domains.distribution.packages.get_github_client", lambda *a: provider)

    def queue(identity):
        with Session(engine) as db:
            task = ensure_cache(db, db.get(DebugRecord, identity))
            task_id = task.id
            db.commit()
            return task_id

    with ThreadPoolExecutor(2) as executor:
        tasks = list(executor.map(queue, ids))
    assert tasks[0] == tasks[1]
    with Session(engine) as db:
        config = cache_settings(db)
        config.data = {**config.data, "budget_bytes": len(data), "max_file_bytes": len(data)}
        db.commit()
        download_cache(db, settings, ids[0], tasks[0])
        download_cache(db, settings, ids[1], uuid4())
        entries = [db.get(DebugRecord, id) for id in ids]
        assert entries[0].cache_state == entries[1].cache_state == "ready"
        assert cache_path(settings, entries[0]) == cache_path(settings, entries[1])
        assert cache_path(settings, entries[0]).read_bytes() == data
        assert len(list(settings.cache_dir.glob("*.package"))) == 1
        assert cache_usage(db) == {"used_bytes": len(data), "reserved_bytes": 0}
        assert len(db.scalars(select(CacheRecord)).all()) == 1
        assert len(db.scalars(select(TaskRecord)).all()) == 1
    assert provider.downloads == 1


def test_different_task_ids_cannot_download_same_source_concurrently(shared, monkeypatch):
    engine, settings, ids, _, data = shared
    provider = Provider(data)
    provider.release = threading.Event()
    monkeypatch.setattr("app.domains.distribution.packages.get_github_client", lambda *a: provider)

    def run(identity):
        with Session(engine) as db:
            download_cache(db, settings, identity, uuid4())

    with ThreadPoolExecutor(1) as executor:
        future = executor.submit(run, ids[0])
        assert provider.entered.wait(10)
        try:
            with pytest.raises(RetryLater):
                run(ids[1])
        finally:
            provider.release.set()
        future.result()
    assert provider.downloads == 1


def test_any_entry_grant_or_lease_protects_shared_file(shared, monkeypatch):
    engine, settings, ids, _, data = shared
    monkeypatch.setattr(
        "app.domains.distribution.packages.get_github_client", lambda *a: Provider(data)
    )
    with Session(engine) as db:
        download_cache(db, settings, ids[0], uuid4())
        path = cache_path(settings, db.get(DebugRecord, ids[0]))
        grant = GrantRecord(
            token_hash="a" * 64, entry_id=ids[1], expires_at=utcnow() + timedelta(minutes=5)
        )
        db.add(grant)
        db.commit()
        cleanup_cache(db, settings, "all")
        assert path.exists()
        db.delete(grant)
        lease = TransferLease(entry_id=ids[1], expires_at=utcnow() + timedelta(minutes=5))
        db.add(lease)
        db.commit()
        cleanup_cache(db, settings, "all")
        assert path.exists()
        lease.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
        cleanup_cache(db, settings, "all")
        assert not path.exists()
        assert all(db.get(DebugRecord, id).cache_state == "evicted" for id in ids)
        assert all(db.get(DebugRecord, id).sha256 for id in ids)


def test_disabled_app_does_not_block_peer_source_or_change_authorization(shared, monkeypatch):
    engine, settings, ids, app_ids, data = shared
    used = []

    def api(db, connector, cfg):
        used.append(connector)
        return Provider(data)

    monkeypatch.setattr("app.domains.distribution.packages.get_github_client", api)
    with Session(engine) as db:
        db.get(AppRecord, app_ids[0]).enabled = False
        db.get(DebugRecord, ids[0]).enabled = False
        second_connector = db.get(DebugRecord, ids[1]).connector_id
        db.commit()
        download_cache(db, settings, ids[0], uuid4())
        assert used == [second_connector]
        assert not db.get(AppRecord, app_ids[0]).enabled
        assert not db.get(DebugRecord, ids[0]).enabled
        assert db.get(DebugRecord, ids[1]).enabled
        assert db.get(DebugRecord, ids[1]).cache_state == "ready"


def test_shared_failure_missing_touch_and_sha_preservation(shared, monkeypatch):
    engine, settings, ids, _, data = shared
    provider = Provider(data)
    monkeypatch.setattr("app.domains.distribution.packages.get_github_client", lambda *a: provider)
    with Session(engine) as db:
        download_cache(db, settings, ids[0], uuid4())
        first = db.get(DebugRecord, ids[0])
        original_hash = first.sha256
        touch_cache(db, db.get(DebugRecord, ids[1]))
        assert db.get(DebugRecord, ids[0]).last_access_at is not None
        cleanup_cache(db, settings, "all")
        provider.data = package_bytes("b")
        with pytest.raises(AppError, match="首次下载不一致"):
            download_cache(db, settings, ids[1], uuid4())
        mark_cache_failed(db, first, "SOURCE_CHANGED")
        db.commit()
        assert all(db.get(DebugRecord, id).cache_state == "failed" for id in ids)
        assert all(db.get(DebugRecord, id).sha256 == original_hash for id in ids)
        mark_cache_missing(db, first)
        db.commit()
        assert all(db.get(DebugRecord, id).cache_state == "missing" for id in ids)
        assert source_cache(db, first).sha256 == original_hash


def test_stale_session_observes_new_ready_cache(shared, monkeypatch):
    engine, settings, ids, _, data = shared
    monkeypatch.setattr(
        "app.domains.distribution.packages.get_github_client", lambda *a: Provider(data)
    )
    with Session(engine) as seed:
        source_cache(seed, seed.get(DebugRecord, ids[0]))
        seed.commit()
    with Session(engine) as stale, Session(engine) as writer:
        entry = stale.get(DebugRecord, ids[1])
        old = stale.get(CacheRecord, entry.source_identity)
        assert old.cache_state == "missing"
        download_cache(writer, settings, ids[0], uuid4())
        current = source_cache(stale, entry)
        assert current.cache_state == "ready"
        assert entry.cache_state == "ready"
        mark_cache_failed(stale, entry, "STALE_FAILURE")
        assert current.cache_state == "ready" and current.cache_error_code is None


def test_old_failure_handler_does_not_override_active_new_worker(shared, monkeypatch):
    engine, settings, ids, _, data = shared
    provider = Provider(data)
    provider.release = threading.Event()
    monkeypatch.setattr("app.domains.distribution.packages.get_github_client", lambda *a: provider)

    def run():
        with Session(engine) as db:
            download_cache(db, settings, ids[0], uuid4())

    with ThreadPoolExecutor(1) as executor:
        future = executor.submit(run)
        assert provider.entered.wait(10)
        try:
            with Session(engine) as db:
                entry = db.get(DebugRecord, ids[1])
                mark_cache_failed(db, entry, "STALE_FAILURE")
                db.commit()
                assert db.get(CacheRecord, entry.source_identity).cache_state == "downloading"
        finally:
            provider.release.set()
        future.result()
    with Session(engine) as db:
        assert db.get(DebugRecord, ids[1]).cache_state == "ready"


def test_lost_execution_fence_never_publishes_tempfile(shared, monkeypatch):
    engine, settings, ids, _, data = shared
    monkeypatch.setattr(
        "app.domains.distribution.packages.get_github_client", lambda *a: Provider(data)
    )
    checks = []

    def lost_fence(*args):
        checks.append(True)
        raise AppError(503, "CACHE_WORKER_LEASE_LOST", "测试执行连接中断", True)

    monkeypatch.setattr("app.domains.distribution.packages._verify_source_fence", lost_fence)
    with Session(engine) as db:
        with pytest.raises(AppError, match="执行连接中断"):
            download_cache(db, settings, ids[0], uuid4())
        assert checks
        assert not list(settings.cache_dir.glob("*.package"))
        assert not list(settings.cache_dir.glob("*.part"))
        assert db.get(DebugRecord, ids[0]).cache_state != "ready"


@pytest.mark.parametrize("conflicting_hashes", [False, True])
def test_populated_migration_preserves_grants_and_accounts_legacy_files(shared, conflicting_hashes):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    engine, settings, _, _, data = shared
    schema = "cache_migration_" + uuid4().hex
    directory = Path(__file__).resolve().parents[1] / "migrations" / "versions"
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        with Operations.context(MigrationContext.configure(connection)):
            files = sorted(directory.glob("000[1-4]*.py"))
            for path in files:
                spec = importlib.util.spec_from_file_location(path.stem, path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.upgrade()
            identities = []
            source = {
                "repository_id": "42",
                "repository_full_name": "team/mobile",
                "release_id": "3",
                "asset_id": "4",
                "asset_updated_at": "2026-10-01T00:00:00Z",
                "size_bytes": len(data),
                "digest": None,
            }
            for number in range(2):
                app_id, entry_id = uuid4(), uuid4()
                identities.append(entry_id)
                connection.execute(
                    AppRecord.__table__.insert().values(
                        id=app_id,
                        name="Legacy",
                        public_slug=f"legacy-{number}",
                        description="",
                        platforms=["android"],
                        enabled=True,
                        revision=1,
                        created_at=utcnow(),
                        updated_at=utcnow(),
                    )
                )
                connection.execute(
                    DebugRecord.__table__.insert().values(
                        id=entry_id,
                        app_id=app_id,
                        connector_id=uuid4(),
                        source_identity=digest(source),
                        revision=1,
                        enabled=True,
                        platform="android",
                        file_name="demo.apk",
                        size_bytes=len(data),
                        source_tag="v1",
                        source=source,
                        cache_state="ready",
                        downloaded_bytes=len(data),
                        sha256=("b" if number and conflicting_hashes else "a") * 64,
                        created_at=utcnow(),
                        updated_at=utcnow(),
                        last_access_at=utcnow(),
                    )
                )
                (settings.cache_dir / f"{entry_id}.package").write_bytes(data)
            connection.execute(
                GrantRecord.__table__.insert().values(
                    token_hash="a" * 64,
                    entry_id=identities[1],
                    expires_at=utcnow() + timedelta(minutes=5),
                )
            )
            path = directory / "0005_shared_source_cache.py"
            spec = importlib.util.spec_from_file_location(path.stem, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.upgrade()
        with Session(bind=connection) as db:
            shared_cache = db.scalar(select(CacheRecord))
            assert shared_cache.cache_state == ("failed" if conflicting_hashes else "ready")
            assert cache_usage(db)["used_bytes"] == 2 * len(data)
            if not conflicting_hashes:
                assert cache_path(settings, db.get(DebugRecord, identities[1])).exists()
            cleanup_cache(db, settings, "all")
            assert all((settings.cache_dir / f"{id}.package").exists() for id in identities)
            db.delete(db.get(GrantRecord, "a" * 64))
            db.flush()
            cleanup_cache(db, settings, "all")
            assert cache_usage(db)["used_bytes"] == 0
            assert not list(settings.cache_dir.glob("*.package"))
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
