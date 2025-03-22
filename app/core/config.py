import logging

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)
load_dotenv()


class OpenSkyApiConfig(BaseSettings):
    username: str | None = Field(default=None, alias="OPENSKY_USER")
    password: str | None = Field(default=None, alias="OPENSKY_PASS")

    model_config = SettingsConfigDict(env_file=".env", extra='ignore', env_file_encoding="utf-8")


class Settings(BaseSettings):
    opensky: OpenSkyApiConfig = OpenSkyApiConfig()

    model_config = SettingsConfigDict(env_file="./.env", extra='ignore', env_file_encoding="utf-8")


settings = Settings()

logger.info("Settings loaded:")
logger.info(f"Settings: {settings.model_dump()}")
