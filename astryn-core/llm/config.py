from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderConfig(BaseModel):
    provider: str
    model: str


class AstrynSettings(BaseSettings):
    ollama_base_url: str = "http://localhost:11434"
    astryn_default_model: str = "qwen3:30b-a3b"
    astryn_api_key: str
    max_history_turns: int = 20
    database_url: str

    model_config = SettingsConfigDict(env_file=".env")


settings = AstrynSettings()
