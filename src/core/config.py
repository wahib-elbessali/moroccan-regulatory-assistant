import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

SECRET_NAMES = ("POSTGRES_PASSWORD", "JWT_SECRET", "ADMIN_USERNAME", "ADMIN_PASSWORD")


class Section(BaseModel):
    model_config = ConfigDict(extra="allow")


class FakesSettings(Section):
    data_dir: str = "data/processed"


class LLMSettings(Section):
    model: str = "qwen2.5:7b"
    model_light: str = "qwen2.5:3b"
    narration_model: str = "qwen2.5:1.5b"
    num_ctx: int = 16384
    base_url: str = "http://llm:11434"


class ModelsSettings(Section):
    base_url: str = "http://models:8080"
    embedding: str = "BAAI/bge-m3"
    reranker: str = "BAAI/bge-reranker-v2-m3"


class RetrievalSettings(Section):
    qdrant_url: str = "http://qdrant:6333"
    collection: str = "chunks"
    embed_batch_size: int = 32
    top_k_vector: int = 30
    top_k_bm25: int = 30
    rrf_k: int = 60
    top_k_final: int = 10
    rerank_top_n: int = 20


class AgentsSettings(Section):
    max_iterations: int = 3
    max_sub_questions: int = 3
    max_tokens_per_request: int = 8000
    grade_top_n: int = 5
    min_relevant: int = 1
    max_passages_to_writer: int = 8
    max_question_chars: int = 1000
    request_timeout_s: int = 60
    confidence_unknown_below: float = 0.4


class AnswerSettings(Section):
    max_answer_tokens: int = 800
    max_judge_tokens: int = 600
    min_excerpt_chars: int = 10
    web_confidence_cap: float = 0.5
    narration_max_tokens: int = 60


class WebSettings(Section):
    enabled: bool = True
    base_url: str = "http://web-search:8090"
    max_results: int = 5
    max_query_words: int = 12
    max_snippet_chars: int = 500
    timeout_s: int = 5


class LeakSettings(Section):
    ngram: int = 4
    overlap_threshold: float = 0.2
    min_hits: int = 3
    max_df: int = 20


class OCRSettings(Section):
    base_url: str = "http://ocr:8070"
    max_pages_upload: int = 50


class DatabaseSettings(Section):
    host: str = "postgres"
    port: int = 5432
    name: str = "rag"
    user: str = "postgres"


class AuthSettings(Section):
    """RÃ©glages d'authentification. Le secret JWT n'est PAS ici : il vient de .env (JWT_SECRET)."""

    token_minutes: int = 60
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    min_password_length: int = 8
    max_pending_requests: int = 50


class UISettings(Section):
    api_base_url: str = "http://api:8000"


class UploadsSettings(Section):
    max_bytes: int = 20_000_000


class IngestionSettings(Section):
    strategy: Literal["article", "fixed"] = "article"
    max_chunk_chars: int = 2000
    overlap_chars: int = 200
    min_letters_per_page: int = 50
    ocr_min_confidence: float = 0.6


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Secrets (.env) : volontairement SANS valeur par dÃ©faut -------------------------------
    POSTGRES_PASSWORD: SecretStr
    JWT_SECRET: SecretStr
    ADMIN_USERNAME: str
    ADMIN_PASSWORD: SecretStr
    CI_POSTGRES_URL: str | None = (
        None  # CI uniquement : remplace l'URL construite depuis `database`
    )

    # --- config.yaml --------------------------------------------------------------------------
    mode: Literal["local", "light", "cloud"] = "local"
    contracts: dict[str, str] = Field(default_factory=dict)  # nom du contrat -> "fake" | "real"
    fakes: FakesSettings = Field(default_factory=FakesSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    models: ModelsSettings = Field(default_factory=ModelsSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    agents: AgentsSettings = Field(default_factory=AgentsSettings)
    answer: AnswerSettings = Field(default_factory=AnswerSettings)
    web: WebSettings = Field(default_factory=WebSettings)
    leak: LeakSettings = Field(default_factory=LeakSettings)
    ocr: OCRSettings = Field(default_factory=OCRSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    ui: UISettings = Field(default_factory=UISettings)
    uploads: UploadsSettings = Field(default_factory=UploadsSettings)
    ingestion: IngestionSettings = Field(default_factory=IngestionSettings)

    @field_validator("JWT_SECRET")
    @classmethod
    def _jwt_secret_not_empty(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value().strip()) < 8:
            raise ValueError("JWT_SECRET doit contenir au moins 8 caractÃ¨res")
        return v

    @field_validator("contracts")
    @classmethod
    def _contract_modes(cls, v: dict[str, str]) -> dict[str, str]:
        bad = {name: mode for name, mode in v.items() if mode not in ("fake", "real")}
        if bad:
            raise ValueError(f"contracts.<nom> doit valoir 'fake' ou 'real' : {bad}")
        return v

    @model_validator(mode="after")
    def _retrieval_bounds(self) -> "AppConfig":
        if self.retrieval.top_k_final > self.retrieval.rerank_top_n:
            raise ValueError(
                f"P5-04 : retrieval.top_k_final ({self.retrieval.top_k_final}) "
                f"> retrieval.rerank_top_n ({self.retrieval.rerank_top_n})"
            )
        return self

    @model_validator(mode="after")
    def _validate_secret_and_bounds(self) -> "AppConfig":
        if not self.CI_POSTGRES_URL and len(self.JWT_SECRET.get_secret_value().strip()) < 32:
            raise ValueError("JWT_SECRET doit contenir au moins 32 caractères")
        if self.retrieval.top_k_final > self.retrieval.rerank_top_n:
            raise ValueError(
                f"P5-04 : retrieval.top_k_final ({self.retrieval.top_k_final}) "
                f"> retrieval.rerank_top_n ({self.retrieval.rerank_top_n})"
            )
        return self

    @property
    def database_url(self) -> str:
        """URL SQLAlchemy (P5-09b). `CI_POSTGRES_URL` l'emporte ; sinon host/port/nom/utilisateur
        viennent de config.yaml et le mot de passe de .env (Ã©chappÃ© correctement)."""
        if self.CI_POSTGRES_URL:
            return self.CI_POSTGRES_URL
        db = self.database
        return URL.create(
            "postgresql+psycopg",
            username=db.user,
            password=self.POSTGRES_PASSWORD.get_secret_value(),
            host=db.host,
            port=db.port,
            database=db.name,
        ).render_as_string(hide_password=False)


def load_config(yaml_path: str | os.PathLike[str] | None = None) -> AppConfig:
    raw_path = yaml_path if yaml_path is not None else os.getenv("CONFIG_PATH", "config.yaml")
    path = Path(raw_path or "config.yaml")
    data: dict[str, Any] = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    leaked = [k for k in data if k.upper() in SECRET_NAMES]
    if leaked:
        raise ValueError(f"Secrets interdits dans {path.name} (Ã  mettre dans .env) : {leaked}")

    return AppConfig(**data)


class _LazyConfig:
    """Delays loading secrets from .env until first attribute access."""

    def __init__(self) -> None:
        self._instance: AppConfig | None = None

    def _get(self) -> AppConfig:
        if self._instance is None:
            self._instance = load_config()
        return self._instance

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get(), name)


cfg: AppConfig = _LazyConfig()  # type: ignore[assignment]
