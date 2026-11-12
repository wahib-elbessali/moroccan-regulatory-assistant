from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseModel):
    user: str = "postgres"
    host: str = "postgres"
    port: int = 5432
    name: str = "rag"


class AdminSettings(BaseModel):
    username: str = "admin"
    password: str


class AuthSettings(BaseModel):
    jwt_secret: str
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


ContractMode = Literal["fake", "real"]


class ContractsSettings(BaseModel):
    retrieval: ContractMode = "fake"
    ingestion: ContractMode = "fake"
    document_rights: ContractMode = "fake"
    audit: ContractMode = "fake"
    llm: ContractMode = "fake"
    ocr: ContractMode = "fake"
    leak_index: ContractMode = "fake"
    web_search: ContractMode = "fake"
    web_agent: ContractMode = "fake"
    models: ContractMode = "fake"
    orchestrator: ContractMode = "fake"
    writer: ContractMode = "fake"
    narrator: ContractMode = "fake"


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    POSTGRES_USER: str | None = Field(default=None)
    POSTGRES_PASSWORD: str
    POSTGRES_HOST: str | None = Field(default=None)
    POSTGRES_PORT: int | None = Field(default=None)
    POSTGRES_DB: str | None = Field(default=None)
    CI_POSTGRES_URL: str | None = Field(default=None)

    ADMIN_USERNAME: str = Field(default="admin")
    ADMIN_PASSWORD: str
    JWT_SECRET: str

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    admin: AdminSettings | None = None
    auth: AuthSettings | None = None
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    uploads: UploadsSettings = Field(default_factory=UploadsSettings)
    web: WebSettings = Field(default_factory=WebSettings)
    contracts: ContractsSettings = Field(default_factory=ContractsSettings)


def load_config() -> AppConfig:
    settings = AppConfig()  # type: ignore[call-arg]

    config_yaml_path = Path("config.yaml")
    if config_yaml_path.exists():
        with open(config_yaml_path, encoding="utf-8") as f:
            yaml_data: dict[str, Any] = yaml.safe_load(f) or {}

        if "database" in yaml_data:
            settings.database = DatabaseSettings(**yaml_data["database"])
        if "retrieval" in yaml_data:
            settings.retrieval = RetrievalSettings(**yaml_data["retrieval"])
        if "uploads" in yaml_data:
            settings.uploads = UploadsSettings(**yaml_data["uploads"])
        if "auth" in yaml_data:
            auth_dict = dict(yaml_data["auth"])
            auth_dict["jwt_secret"] = settings.JWT_SECRET
            settings.auth = AuthSettings(**auth_dict)
        if "web" in yaml_data:
            settings.web = WebSettings(**yaml_data["web"])
        if "contracts" in yaml_data:
            settings.contracts = ContractsSettings(**yaml_data["contracts"])

    if settings.auth is None:
        settings.auth = AuthSettings(jwt_secret=settings.JWT_SECRET)

    # Surcharges éventuelles depuis .env / variables d'environnement
    if settings.POSTGRES_USER is not None:
        settings.database.user = settings.POSTGRES_USER
    if settings.POSTGRES_HOST is not None:
        settings.database.host = settings.POSTGRES_HOST
    if settings.POSTGRES_PORT is not None:
        settings.database.port = settings.POSTGRES_PORT
    if settings.POSTGRES_DB is not None:
        settings.database.name = settings.POSTGRES_DB

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
