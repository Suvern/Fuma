from pathlib import Path
from urllib.parse import quote, urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    """Read process environment only; never implicitly load dotenv files."""

    model_config = SettingsConfigDict(
        env_prefix="FUMA_", env_file=None, extra="ignore", hide_input_in_errors=True
    )

    database_host: str = "127.0.0.1"
    database_port: int = Field(default=55432, ge=1, le=65535)
    database_name: str = Field(default="fuma", min_length=1)
    database_user: str = Field(default="fuma", min_length=1)
    database_password: SecretStr = SecretStr("")
    redis_host: str = "127.0.0.1"
    redis_port: int = Field(default=56379, ge=1, le=65535)
    redis_db: int = Field(default=0, ge=0)
    redis_username: str = ""
    redis_password: SecretStr = SecretStr("")
    # Compatibility overrides for existing deployments and isolated test databases.
    database_url: SecretStr | None = None
    redis_url: SecretStr | None = None
    site_url: str = "http://127.0.0.1:5173"
    cookie_secure: bool = False
    state_dir: Path = Path("~/.local/share/fuma/state").expanduser()
    # Legacy key import for existing deployments; new instances use the persisted key file.
    encryption_key: SecretStr | None = None
    session_ttl_seconds: int = 28800
    cache_dir: Path = Path("~/.local/share/fuma/cache").expanduser()
    parser_dir: Path | None = None

    @property
    def parser_inbox(self) -> Path:
        return (self.parser_dir or self.state_dir / "parser") / "inbox"

    @property
    def parser_outbox(self) -> Path:
        return (self.parser_dir or self.state_dir / "parser") / "outbox"

    @property
    def database_dsn(self) -> SecretStr:
        if self.database_url and self.database_url.get_secret_value():
            return self.database_url
        return SecretStr(
            URL.create(
                "postgresql+psycopg",
                username=self.database_user,
                password=self.database_password.get_secret_value() or None,
                host=self.database_host,
                port=self.database_port,
                database=self.database_name,
            ).render_as_string(hide_password=False)
        )

    @property
    def redis_dsn(self) -> SecretStr:
        if self.redis_url and self.redis_url.get_secret_value():
            return self.redis_url
        password = self.redis_password.get_secret_value()
        auth = ""
        if self.redis_username or password:
            auth = f"{quote(self.redis_username, safe='')}:{quote(password, safe='')}@"
        host = f"[{self.redis_host}]" if ":" in self.redis_host else self.redis_host
        return SecretStr(f"redis://{auth}{host}:{self.redis_port}/{self.redis_db}")

    @field_validator("database_host", "redis_host")
    @classmethod
    def bare_host(cls, value: str) -> str:
        value = value.strip().removeprefix("[").removesuffix("]")
        if not value or any(char.isspace() or char in "/@?#" for char in value):
            raise ValueError("host must be a hostname or IP address without a URL scheme")
        return value

    @field_validator("cache_dir", "state_dir")
    @classmethod
    def expand_cache_path(cls, value: Path) -> Path:
        return value.expanduser().absolute()

    @field_validator("session_ttl_seconds")
    @classmethod
    def bounded_session(cls, value: int) -> int:
        if not 300 <= value <= 86400:
            raise ValueError("session ttl must be between 300 and 86400 seconds")
        return value

    @model_validator(mode="after")
    def validate_site(self) -> "Settings":
        parsed = urlsplit(self.site_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("site_url must be an HTTP(S) origin")
        if not self.cookie_secure and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("insecure cookies are allowed only for localhost")
        if self.cookie_secure and parsed.scheme != "https":
            raise ValueError("secure cookies require HTTPS")
        self.site_url = self.site_url.rstrip("/")
        return self
