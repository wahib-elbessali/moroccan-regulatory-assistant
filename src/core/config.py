from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseModel):
    user: str = "postgres"
    host: str = "localhost"
    port: int = 5432
    name: str = "regulatory_assistant"


class AdminSettings(BaseModel):
    username: str = "admin"
    password: str = "AdminPassword123!"


class AuthSettings(BaseModel):
    jwt_secret: str = "change_me_super_secret_key_123"
    token_minutes: int = 60
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    min_password_length: int = 8
    max_pending_requests: int = 50


class RetrievalSettings(BaseModel):
    top_k_vector: int = 30
    top_k_bm25: int = 30
    rrf_k: int = 60
    top_k_final: int = 10
    rerank_top_n: int = 20


class UploadsSettings(BaseModel):
    max_bytes: int = 20_000_000


class WebSettings(BaseModel):
    enabled: bool = True
    base_url: str = "http://web-search:8090"
    max_results: int = 5
    max_query_words: int = 12
    max_snippet_chars: int = 500
    timeout_s: int = 5


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    POSTGRES_USER: str = Field(default="postgres")
    POSTGRES_PASSWORD: str = Field(default="postgres")
    POSTGRES_HOST: str = Field(default="localhost")
    POSTGRES_PORT: int = Field(default=5432)
    POSTGRES_DB: str = Field(default="regulatory_assistant")
    CI_POSTGRES_URL: str | None = Field(default=None)

    ADMIN_USERNAME: str = Field(default="admin")
    ADMIN_PASSWORD: str = Field(default="AdminPassword123!")
    JWT_SECRET: str = Field(default="secret-key-jwt-offline")

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    admin: AdminSettings = Field(default_factory=AdminSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    uploads: UploadsSettings = Field(default_factory=UploadsSettings)
    web: WebSettings = Field(default_factory=WebSettings)


def load_config() -> AppConfig:
    settings = AppConfig()

    config_yaml_path = Path("config.yaml")
    if config_yaml_path.exists():
        with open(config_yaml_path, encoding="utf-8") as f:
            yaml_data: dict[str, Any] = yaml.safe_load(f) or {}

        if "retrieval" in yaml_data:
            settings.retrieval = RetrievalSettings(**yaml_data["retrieval"])
        if "uploads" in yaml_data:
            settings.uploads = UploadsSettings(**yaml_data["uploads"])
        if "auth" in yaml_data:
            auth_dict = yaml_data["auth"]
            auth_dict["jwt_secret"] = settings.JWT_SECRET
            settings.auth = AuthSettings(**auth_dict)
        if "web" in yaml_data:
            settings.web = WebSettings(**yaml_data["web"])

    settings.database = DatabaseSettings(
        user=settings.POSTGRES_USER,
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        name=settings.POSTGRES_DB,
    )
    settings.admin = AdminSettings(
        username=settings.ADMIN_USERNAME,
        password=settings.ADMIN_PASSWORD,
    )

    if settings.retrieval.top_k_final > settings.retrieval.rerank_top_n:
        raise ValueError(
            f"Erreur P5-04: retrieval.top_k_final ({settings.retrieval.top_k_final}) "
            f"> retrieval.rerank_top_n ({settings.retrieval.rerank_top_n})"
        )

    return settings


cfg: AppConfig = load_config()
