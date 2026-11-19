import base64
import binascii
from typing import Literal

from pydantic import Field, SecretStr
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
    db_host: str = Field(default="127.0.0.1", min_length=1)
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = Field(default="hoshi", min_length=1)
    db_user: str = Field(min_length=1)
    db_password: SecretStr = Field(min_length=1)

    redis_host: str = Field(default="127.0.0.1", min_length=1)
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_password: SecretStr | None = None

    # JWT 有效期（单位：秒）
    jwt_secret: SecretStr = Field(min_length=1)
    jwt_issuer: str = "hoshi"
    jwt_access_ttl: int = Field(default=300, ge=1)
    jwt_admin_refresh_ttl: int = Field(default=86400, ge=1)
    jwt_user_refresh_ttl: int = Field(default=2592000, ge=1)

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
