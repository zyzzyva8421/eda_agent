"""Unified configuration via pydantic-settings.

All values are read from environment variables (or a .env file in the working
directory).  Import the singleton ``settings`` wherever configuration is
needed.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, PostgresDsn, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    postgres_user: str = Field(default="eda_agent")
    postgres_password: str = Field(default="eda_secret")
    postgres_host: str = Field(default="localhost")
    postgres_port: int = Field(default=5432)
    postgres_db: str = Field(default="eda_agent")

    @computed_field  # type: ignore[misc]
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[misc]
    @property
    def async_database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── PostGIS ────────────────────────────────────────────────────────────────
    # Set to false if your PostgreSQL has no PostGIS extension installed.
    enable_postgis: bool = Field(default=True)

    # ── MiniMax LLM ───────────────────────────────────────────────────────────
    minimax_api_key: str = Field(default="")
    minimax_group_id: str = Field(default="")
    minimax_base_url: str = Field(default="https://api.minimax.chat/v1")
    minimax_model: str = Field(default="MiniMax-Text-01")
    minimax_max_tokens: int = Field(default=4096)
    minimax_temperature: float = Field(default=0.2)
    # Maximum ReAct iterations per session
    agent_max_iterations: int = Field(default=10)

    # ── ORFS backend ─────────────────────────────────────────────────────────
    orfs_root: Path = Field(default_factory=lambda: Path.home() / "OpenROAD-flow-scripts")
    orfs_make_jobs: int = Field(default=4)

    # ── Innovus backend (SSH) ────────────────────────────────────────────────
    innovus_ssh_host: str = Field(default="")
    innovus_ssh_user: str = Field(default="")
    innovus_ssh_port: int = Field(default=22)
    innovus_ssh_password: str = Field(default="")
    innovus_bin: str = Field(default="/opt/cadance/INNOVUS181/bin/innovus")
    innovus_remote_workdir: str = Field(default="~")
    innovus_timeout_sec: int = Field(default=7200)
    innovus_connect_retries: int = Field(default=5)
    innovus_connect_initial_backoff_sec: float = Field(default=2.0)
    innovus_connect_backoff_multiplier: float = Field(default=1.8)
    innovus_connect_max_backoff_sec: float = Field(default=20.0)
    innovus_ssh_probe_timeout_sec: int = Field(default=8)

    # ── Innovus execution mode ────────────────────────────────────────────────
    # "ssh"   – execute Innovus on a remote host via SSH (default)
    # "local" – execute Innovus directly on the local machine
    # "bsub"  – submit to LSF queue via bsub -Is -XF (blocks until done)
    innovus_execution_mode: str = Field(default="ssh")
    # Local work directory (used when execution_mode == "local" or "bsub")
    innovus_local_workdir: Path = Field(default_factory=lambda: Path("/tmp/eda_agent/innovus"))
    # Scheduler settings (used when execution_mode == "bsub")
    innovus_scheduler_queue: str = Field(default="")
    innovus_scheduler_account: str = Field(default="")
    innovus_scheduler_extra: str = Field(default="")  # extra bsub args raw string

    # ── Parquet archive ───────────────────────────────────────────────────────
    parquet_archive_dir: Path = Field(default=Path("/data/archive"))

    # ── FastAPI / JWT ─────────────────────────────────────────────────────────
    api_secret_key: str = Field(default="insecure-change-me")
    api_access_token_expire_minutes: int = Field(default=1440)
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO")

    # ── Custom tools ─────────────────────────────────────────────────────────
    custom_tools_file: str = Field(default="")
    custom_tools_allowlist: str = Field(default="")
    custom_tools_denylist: str = Field(default="")
    custom_tools_enable_entrypoints: bool = Field(default=True)
    custom_tools_entrypoint_group: str = Field(default="eda_agent.custom_tools")

    # ── LLM tool calling mode ─────────────────────────────────────────────────
    # "native"  – send tools/tool_choice in the API payload (standard OpenAI
    #             format; works with MiniMax and vLLM models that support the
    #             OpenAI tool-calling extension out of the box).
    # "prompt"  – inject tool definitions into the system prompt and parse
    #             <tool_call> JSON blocks from the model's text response.
    #             Use this when the vLLM server uses a custom --chat-template
    #             that does not render {{ tools }}, e.g. a plain Gemma 4 setup.
    llm_tool_calling_mode: str = Field(default="native")

    # ── LangSmith ────────────────────────────────────────────────────────────
    langsmith_api_key: str = Field(default="")
    langsmith_endpoint: str = Field(default="https://api.smith.langchain.com")
    langsmith_project: str = Field(default="eda-agent-dev")
    langsmith_enabled: bool = Field(default=False)

    @model_validator(mode="after")
    def _warn_insecure_defaults(self) -> "Settings":
        import warnings

        if self.api_secret_key == "insecure-change-me":
            warnings.warn(
                "API_SECRET_KEY is using the insecure default value. "
                "Set a strong random value in your .env file.",
                stacklevel=2,
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


# Module-level singleton for convenience
settings: Settings = get_settings()
