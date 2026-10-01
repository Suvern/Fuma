import base64
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.core.key_store import ensure_encryption_key, load_encryption_key
from app.domains.auth.service import utcnow
from app.domains.distribution.models import IdempotencyRecord, IntegrationState
from app.domains.github.crypto import SecretBox
from app.domains.github.models import GithubConnector
from app.domains.system.models import SystemState
from app.infrastructure import models as registered_models  # noqa: F401
from app.infrastructure.database import Base, build_engine


@pytest.fixture
def store(tmp_path):
    settings = Settings(
        database_url="postgresql+psycopg://fuma@127.0.0.1:55432/fuma_keys_test",
        state_dir=tmp_path / "state",
    )
    engine = build_engine(settings)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except Exception:
        engine.dispose()
        pytest.skip("isolated native PostgreSQL fuma_keys_test unavailable")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(SystemState(id=1))
        db.commit()
    yield engine, settings
    engine.dispose()


def test_concurrent_generation_restart_and_worker_decryption(store):
    engine, settings = store
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda _: ensure_encryption_key(engine, settings), range(4)))
    key = load_encryption_key(settings)
    path = settings.state_dir / "encryption.key"
    assert path.stat().st_mode & 0o777 == 0o600
    with Session(engine) as db:
        state = db.get(SystemState, 1)
        assert state.encryption_key_digest
        state.initialized_at = utcnow()
        db.commit()
    value = SecretBox(settings).encrypt("synthetic-provider-token", "feishu")
    restarted = Settings(state_dir=settings.state_dir)
    ensure_encryption_key(engine, restarted)
    assert load_encryption_key(restarted) == key
    assert SecretBox(restarted).decrypt(value, "feishu") == "synthetic-provider-token"


def test_missing_or_changed_key_never_regenerates(store):
    engine, settings = store
    ensure_encryption_key(engine, settings)
    path = settings.state_dir / "encryption.key"
    path.unlink()
    with pytest.raises(AppError) as error:
        ensure_encryption_key(engine, settings)
    assert error.value.code == "ENCRYPTION_KEY_UNAVAILABLE"
    assert not path.exists()
    path.write_bytes(base64.urlsafe_b64encode(b"x" * 32))
    path.chmod(0o600)
    with pytest.raises(AppError) as error:
        ensure_encryption_key(engine, settings)
    assert error.value.code == "ENCRYPTION_KEY_MISMATCH"


def test_legacy_import_then_remove_environment_key(store):
    engine, settings = store
    with Session(engine) as db:
        db.get(SystemState, 1).initialized_at = utcnow()
        db.commit()
    with pytest.raises(AppError):
        ensure_encryption_key(engine, settings)
    legacy = settings.model_copy(update={})
    legacy.encryption_key = SecretStr(base64.urlsafe_b64encode(b"l" * 32).decode())
    ensure_encryption_key(engine, legacy)
    assert load_encryption_key(settings) == b"l" * 32
    ensure_encryption_key(engine, settings)


def test_invalid_permissions_symlink_and_empty_file_fail_closed(store, tmp_path):
    engine, settings = store
    ensure_encryption_key(engine, settings)
    path = settings.state_dir / "encryption.key"
    path.chmod(0o644)
    with pytest.raises(AppError):
        ensure_encryption_key(engine, settings)
    path.unlink()
    target = tmp_path / "synthetic-key"
    target.write_bytes(base64.urlsafe_b64encode(b"x" * 32))
    target.chmod(0o600)
    path.symlink_to(target)
    with pytest.raises(AppError):
        ensure_encryption_key(engine, settings)
    path.unlink()
    path.touch(mode=0o600)
    with pytest.raises(AppError):
        ensure_encryption_key(engine, settings)


@pytest.mark.parametrize("provider", ["github", "feishu", "download-grant"])
@pytest.mark.parametrize("existing_file", [True, False])
def test_first_fingerprint_requires_existing_credentials_to_decrypt(store, provider, existing_file):
    engine, settings = store
    correct = base64.urlsafe_b64encode(b"c" * 32).decode()
    wrong = base64.urlsafe_b64encode(b"w" * 32).decode()
    identity, now = uuid4(), utcnow()
    scope = "github:" + str(identity) if provider == "github" else provider
    ciphertext = SecretBox(Settings(encryption_key=correct)).encrypt("synthetic", scope)
    with Session(engine) as db:
        db.get(SystemState, 1).initialized_at = now
        if provider == "github":
            db.add(
                GithubConnector(
                    id=identity,
                    name="legacy",
                    encrypted_token=ciphertext,
                    created_at=now,
                    updated_at=now,
                )
            )
        elif provider == "feishu":
            db.add(IntegrationState(key="feishu", data={"secret": ciphertext}))
        else:
            db.add(
                IdempotencyRecord(
                    key="legacy",
                    body_hash="x" * 64,
                    data={"encrypted": ciphertext},
                    expires_at=now,
                )
            )
        db.commit()
    path = settings.state_dir / "encryption.key"
    if existing_file:
        settings.state_dir.mkdir()
        path.write_text(wrong)
        path.chmod(0o600)
    else:
        settings.encryption_key = SecretStr(wrong)
    with pytest.raises(AppError) as error:
        ensure_encryption_key(engine, settings)
    assert error.value.code == "ENCRYPTION_KEY_MISMATCH"
    with Session(engine) as db:
        assert db.get(SystemState, 1).encryption_key_digest is None
    if existing_file:
        path.write_text(correct)
    else:
        assert not path.exists()
        settings.encryption_key = SecretStr(correct)
    ensure_encryption_key(engine, settings)
    with Session(engine) as db:
        assert db.get(SystemState, 1).encryption_key_digest is not None
