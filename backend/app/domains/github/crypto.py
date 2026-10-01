import base64
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings
from app.core.errors import AppError
from app.core.key_store import load_encryption_key


class SecretBox:
    """Versioned authenticated encryption; database copies cannot change credential scope."""

    def __init__(self, settings: Settings):
        self._cipher = AESGCM(load_encryption_key(settings))

    def encrypt(self, value: str, scope: str = "credential") -> str:
        nonce = secrets.token_bytes(12)
        encrypted = self._cipher.encrypt(nonce, value.encode(), ("fuma:v1:" + scope).encode())
        return "v1:" + base64.urlsafe_b64encode(nonce + encrypted).decode()

    def decrypt(self, value: str, scope: str = "credential") -> str:
        try:
            if not value.startswith("v1:"):
                raise ValueError
            blob = base64.b64decode(value[3:], altchars=b"-_", validate=True)
            return self._cipher.decrypt(
                blob[:12], blob[12:], ("fuma:v1:" + scope).encode()
            ).decode()
        except (ValueError, TypeError, InvalidTag, UnicodeError):
            raise AppError(
                503, "CREDENTIAL_UNAVAILABLE", "凭据无法解密，请检查根密钥或重新配置"
            ) from None
