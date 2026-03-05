from decimal import Decimal

from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderConfig(BaseModel):
    provider: str
    model: str


class AstrynSettings(BaseSettings):
    ollama_base_url: str = "http://localhost:11434"
    astryn_default_model: str = "qwen3:30b-a3b"
    astryn_api_key: SecretStr
    max_history_turns: int = 20
    database_url: str

    # Multi-provider settings
    anthropic_api_key: SecretStr | None = None
    astryn_coordinator_provider: str = "ollama"  # "anthropic" or "ollama"
    astryn_coordinator_model: str = "claude-sonnet-4-6"
    astryn_specialist_model: str = "qwen3:30b-a3b"

    # Budget settings
    astryn_anthropic_daily_budget_usd: Decimal = Decimal("5.00")
    astryn_anthropic_monthly_budget_usd: Decimal = Decimal("50.00")

    # Skills directory
    astryn_skills_dir: str = "~/.astryn/skills"

    model_config = SettingsConfigDict(env_file=".env")


settings = AstrynSettings()
