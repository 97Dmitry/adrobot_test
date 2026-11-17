from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    keitaro_url: str = "https://tlgk.host"
    keitaro_api_key: SecretStr = SecretStr("")
    keitaro_timeout: float = 20
    database_url: str = "sqlite:///./adrobot.db"
