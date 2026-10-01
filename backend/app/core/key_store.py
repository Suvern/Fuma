"""Server-owned encryption key, shared by API and workers through a private state volume."""

import base64
import hashlib
import os
import secrets
import stat
import tempfile
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.domains.distribution.models import IdempotencyRecord, IntegrationState
from app.domains.github.models import GithubConnector
from app.domains.system.models import SystemState


def _decode(raw: str | bytes) -> bytes:
    try:
        key = base64.b64decode(raw, altchars=b"-_", validate=True)
        if len(key) == 32:
            return key
    except (ValueError, TypeError):
        pass
    raise AppError(503, "ENCRYPTION_KEY_INVALID", "加密密钥无效，请恢复原密钥文件")


def _read(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise AppError(
                503, "ENCRYPTION_KEY_INVALID", "密钥文件必须为仅服务用户可读写的普通文件"
            )
        return _decode(stream.read(128).strip())


def load_encryption_key(settings) -> bytes:
    if settings.encryption_key:
        return _decode(settings.encryption_key.get_secret_value())
    try:
        return _read(settings.state_dir / "encryption.key")
    except OSError:
        raise AppError(
            503, "ENCRYPTION_KEY_UNAVAILABLE", "无法读取加密密钥，请检查持久状态卷"
        ) from None


def _publish(path: Path, key: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".key-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(base64.urlsafe_b64encode(key) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        # Never replace an existing key, even when two installations share the same directory.
        try:
            os.link(temporary, path)
        except FileExistsError:
            if not secrets.compare_digest(_read(path), key):
                raise AppError(
                    503, "ENCRYPTION_KEY_MISMATCH", "状态目录已使用其他加密密钥"
                ) from None
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temporary)


def _validate_existing_credentials(db, key: bytes) -> None:
    cipher = AESGCM(key)

    def verify(value, scope):
        try:
            if not isinstance(value, str) or not value.startswith("v1:"):
                raise ValueError
            blob = base64.b64decode(value[3:], altchars=b"-_", validate=True)
            cipher.decrypt(blob[:12], blob[12:], ("fuma:v1:" + scope).encode())
        except (ValueError, TypeError, InvalidTag):
            raise AppError(
                503, "ENCRYPTION_KEY_MISMATCH", "密钥无法解密已有凭据，请恢复旧实例的原密钥"
            ) from None

    for connector in db.scalars(select(GithubConnector).execution_options(yield_per=100)):
        verify(connector.encrypted_token, "github:" + str(connector.id))
    feishu = db.get(IntegrationState, "feishu")
    if feishu and feishu.data.get("secret"):
        verify(feishu.data["secret"], "feishu")
    for record in db.scalars(select(IdempotencyRecord).execution_options(yield_per=100)):
        if "encrypted" in record.data:
            verify(record.data["encrypted"], "download-grant")


def ensure_encryption_key(engine, settings) -> None:
    """Serialize first creation and bind the key fingerprint to the database.

    A missing key for an initialized database never silently generates a replacement.
    A legacy environment key may be imported once without revealing its value.
    """
    try:
        with Session(engine) as db:
            state = db.scalar(select(SystemState).where(SystemState.id == 1).with_for_update())
            if state is None:
                raise AppError(503, "DATABASE_NOT_INITIALIZED", "请先执行数据库迁移")
            settings.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            if settings.state_dir.is_symlink():
                raise AppError(503, "ENCRYPTION_KEY_INVALID", "状态目录不能是符号链接")
            path = settings.state_dir / "encryption.key"
            explicit = (
                _decode(settings.encryption_key.get_secret_value())
                if settings.encryption_key
                else None
            )
            missing = False
            try:
                key = _read(path)
            except FileNotFoundError:
                missing = True
                if explicit is None and (state.encryption_key_digest or state.initialized_at):
                    raise AppError(
                        503, "ENCRYPTION_KEY_UNAVAILABLE", "已初始化实例缺少密钥，请恢复原状态卷"
                    ) from None
                key = explicit or secrets.token_bytes(32)
                if state.encryption_key_digest and not secrets.compare_digest(
                    state.encryption_key_digest, hashlib.sha256(key).hexdigest()
                ):
                    raise AppError(
                        503, "ENCRYPTION_KEY_MISMATCH", "加密密钥与数据库不匹配"
                    ) from None
            if explicit and not secrets.compare_digest(explicit, key):
                raise AppError(503, "ENCRYPTION_KEY_MISMATCH", "旧配置密钥与持久状态卷不匹配")
            fingerprint = hashlib.sha256(key).hexdigest()
            if state.encryption_key_digest and not secrets.compare_digest(
                state.encryption_key_digest, fingerprint
            ):
                raise AppError(503, "ENCRYPTION_KEY_MISMATCH", "加密密钥与数据库不匹配")
            if state.encryption_key_digest is None:
                _validate_existing_credentials(db, key)
            if missing:
                _publish(path, key)
            state.encryption_key_digest = fingerprint
            db.commit()
    except OSError:
        raise AppError(
            503, "ENCRYPTION_KEY_UNAVAILABLE", "无法初始化密钥，请检查持久状态卷权限"
        ) from None
