import base64
import binascii
from dataclasses import dataclass
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


@dataclass(frozen=True, slots=True)
class S3Settings:
    endpoint_url: str
    signing_endpoint_url: str
    region: str
    private_bucket: str
    public_bucket: str
    access_key: SecretStr
    secret_key: SecretStr


def _validate_http_root_url(
    raw_url: str, *, field_name: str, require_https: bool = False
) -> str:
    parsed = urlsplit(raw_url)
    scheme = parsed.scheme.lower()
    allowed_schemes = ("https",) if require_https else ("http", "https")
    if scheme not in allowed_schemes:
        expected = "HTTPS" if require_https else "HTTP(S)"
        raise ValueError(f"{field_name} 必须是 {expected} 根地址")

    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field_name} 不能包含认证信息")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"{field_name} 缺少有效主机名")

    try:
        port = parsed.port
    except ValueError:
        raise ValueError(f"{field_name} 包含无效端口") from None

    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError(f"{field_name} 必须是根地址，不能包含路径、查询串或片段")

    host_part = f"[{hostname}]" if ":" in hostname else hostname
    netloc = f"{host_part}:{port}" if port is not None else host_part
    return f"{scheme}://{netloc}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HOSHI_",
        env_file=".env",
        env_file_encoding="utf-8",
        hide_input_in_errors=True,
    )

    app_env: Literal["development", "production"] = "production"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_file: str = Field(default="logs/hoshi.log", min_length=1)
    db_host: str = Field(default="127.0.0.1", min_length=1)
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = Field(default="hoshi", min_length=1)
    db_user: str = Field(min_length=1)
    db_password: SecretStr = Field(min_length=1)

    # 同源
    admin_origin: str = Field(default="http://127.0.0.1:5173", min_length=1)

    redis_host: str = Field(default="127.0.0.1", min_length=1)
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_password: SecretStr | None = None

    # JWT 有效期（单位：秒）
    jwt_secret: SecretStr = Field(min_length=1)
    jwt_issuer: str = "hoshi"
    jwt_access_ttl: int = Field(default=300, ge=1)
    jwt_admin_refresh_ttl: int = Field(default=86400, ge=1)
    jwt_user_refresh_ttl: int = Field(default=2592000, ge=1)

    # 双桶对象存储
    s3_endpoint_url: str | None = None
    s3_signing_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_private_bucket: str | None = None
    s3_public_bucket: str | None = None
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None

    @field_validator(
        "s3_endpoint_url",
        "s3_signing_endpoint_url",
        "s3_private_bucket",
        "s3_public_bucket",
        mode="before",
    )
    @classmethod
    def _normalize_optional_s3_str(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("s3_access_key", "s3_secret_key", mode="before")
    @classmethod
    def _normalize_optional_s3_secret(cls, value: object) -> object:
        if isinstance(value, SecretStr):
            stripped = value.get_secret_value().strip()
            return SecretStr(stripped) if stripped else None
        if isinstance(value, str):
            stripped = value.strip()
            return SecretStr(stripped) if stripped else None
        return value

    @field_validator("s3_region")
    @classmethod
    def _validate_s3_region(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("HOSHI_S3_REGION 不能为空")
        return stripped

    @model_validator(mode="after")
    def _validate_s3_settings(self) -> Self:
        core_values = (
            self.s3_endpoint_url,
            self.s3_private_bucket,
            self.s3_public_bucket,
            self.s3_access_key,
            self.s3_secret_key,
        )
        if all(value is None for value in core_values):
            if self.s3_signing_endpoint_url is not None:
                raise ValueError(
                    "对象存储未启用时不能单独配置 HOSHI_S3_SIGNING_ENDPOINT_URL"
                )
            return self

        if any(value is None for value in core_values):
            raise ValueError(
                "对象存储配置不完整，HOSHI_S3_ENDPOINT_URL、HOSHI_S3_PRIVATE_BUCKET、"
                "HOSHI_S3_PUBLIC_BUCKET、HOSHI_S3_ACCESS_KEY、HOSHI_S3_SECRET_KEY 须成组填写"
            )

        assert self.s3_endpoint_url is not None
        assert self.s3_private_bucket is not None
        assert self.s3_public_bucket is not None

        if self.s3_private_bucket == self.s3_public_bucket:
            raise ValueError(
                "HOSHI_S3_PRIVATE_BUCKET 与 HOSHI_S3_PUBLIC_BUCKET 不能同名"
            )

        self.s3_endpoint_url = _validate_http_root_url(
            self.s3_endpoint_url, field_name="HOSHI_S3_ENDPOINT_URL"
        )

        require_https_signing = self.app_env == "production"
        if self.s3_signing_endpoint_url is not None:
            self.s3_signing_endpoint_url = _validate_http_root_url(
                self.s3_signing_endpoint_url,
                field_name="HOSHI_S3_SIGNING_ENDPOINT_URL",
                require_https=require_https_signing,
            )
        elif require_https_signing:
            raise ValueError(
                "生产环境启用对象存储时必须显式配置 HTTPS 的 HOSHI_S3_SIGNING_ENDPOINT_URL"
            )

        return self

    def s3_config(self) -> S3Settings | None:
        if (
            self.s3_endpoint_url is None
            or self.s3_private_bucket is None
            or self.s3_public_bucket is None
            or self.s3_access_key is None
            or self.s3_secret_key is None
        ):
            return None

        return S3Settings(
            endpoint_url=self.s3_endpoint_url,
            signing_endpoint_url=self.s3_signing_endpoint_url or self.s3_endpoint_url,
            region=self.s3_region,
            private_bucket=self.s3_private_bucket,
            public_bucket=self.s3_public_bucket,
            access_key=self.s3_access_key,
            secret_key=self.s3_secret_key,
        )

    def database_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )

    def jwt_secret_bytes(self) -> bytes:
        key_bytes = None
        try:
            key_bytes = base64.b64decode(
                self.jwt_secret.get_secret_value(), validate=True
            )
        except (binascii.Error, ValueError):
            raise ValueError("JWT 密钥配置错误") from None

        if len(key_bytes) < 32:
            raise ValueError("JWT 密钥解码后长度不能少于 32 字节")
        return key_bytes
