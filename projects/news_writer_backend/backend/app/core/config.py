"""应用配置：pydantic-settings 从环境变量 / .env 加载。

密钥与基础设施（DB_URL、*_API_KEY 等）只进这里；
用户可改的运行时设置（llm_base_url / llm_model 等）另走 app_settings 表 + SettingsService。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # 应用
    app_env: str = Field(default="dev", alias="APP_ENV")
    app_port: int = Field(default=8000, alias="APP_PORT")

    # 数据库 / Redis
    db_url: str = Field(alias="DB_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # 鉴权
    auth_initial_api_token: str = Field(alias="AUTH_INITIAL_API_TOKEN")

    # LLM（env 作为默认值，app_settings 表可 override）
    llm_base_url: str = Field(default="", alias="LLM_BASE_URL")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_model: str = Field(default="", alias="LLM_MODEL")

    # Embedding
    embedding_base_url: str = Field(default="", alias="EMBEDDING_BASE_URL")
    embedding_api_key: str = Field(default="", alias="EMBEDDING_API_KEY")
    embedding_model: str = Field(default="BAAI/bge-m3", alias="EMBEDDING_MODEL")

    # 对象存储
    storage_type: str = Field(default="minio", alias="STORAGE_TYPE")
    storage_endpoint: str = Field(default="http://localhost:9000", alias="STORAGE_ENDPOINT")
    storage_access_key: str = Field(default="minioadmin", alias="STORAGE_ACCESS_KEY")
    storage_secret_key: str = Field(default="minioadmin", alias="STORAGE_SECRET_KEY")
    storage_bucket: str = Field(default="news-writer", alias="STORAGE_BUCKET")
    storage_public_base: str = Field(default="", alias="STORAGE_PUBLIC_BASE")
    storage_local_dir: str = Field(default="./storage", alias="STORAGE_LOCAL_DIR")

    # 搜图
    image_search_api_key: str = Field(default="", alias="IMAGE_SEARCH_API_KEY")

    # 测试开关
    fake_llm: bool = Field(default=False, alias="FAKE_LLM")

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"


@lru_cache(maxsize=1)
def _load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


# 惰性实例：pydantic-settings 会在首次访问时校验 env
settings: Settings = _load_settings()
