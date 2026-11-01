from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    enable_search_grounding: bool = True
    eur_to_chf_rate: float = 0.94
    rembg_model: str = "u2netp"
    log_level: str = "INFO"
    data_dir: Path = Path("./data")
    host: str = "127.0.0.1"
    port: int = 8000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
