from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import BaseModel


class ProviderConfig(BaseModel):
    provider: str
    model: str


class AstrynSettings(BaseSettings):
    ollama_base_url: str = "http://localhost:11434"
    astryn_default_model: str = "qwen2.5-coder:7b"
    astryn_api_key: str
    max_history_turns: int = 20

    model_config = SettingsConfigDict(env_file=".env")


settings = AstrynSettings()
