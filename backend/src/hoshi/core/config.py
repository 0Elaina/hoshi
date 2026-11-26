import base64
import binascii
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


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

    # Rustfs
    s3_endpoint_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:9000")
    s3_region: str = Field(default="us-east-1", min_length=1)
    s3_bucket: str = Field(default="hoshi-files", min_length=1)
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None

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

    def s3_credentials(self) -> tuple[str, str]:
        access_key = (
            ""
            if self.s3_access_key is None
            else self.s3_access_key.get_secret_value().strip()
        )
        secret_key = (
            ""
            if self.s3_secret_key is None
            else self.s3_secret_key.get_secret_value().strip()
        )
        missing: list[str] = []
        if not access_key:
            missing.append("HOSHI_S3_ACCESS_KEY")
        if not secret_key:
            missing.append("HOSHI_S3_SECRET_KEY")

        if missing:
            raise ValueError(f"缺少 RustFS 对象存储凭据: {', '.join(missing)}")
        return access_key, secret_key
