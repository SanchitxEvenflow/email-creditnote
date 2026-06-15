from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    client_id: str
    client_secret: str
    refresh_token: str
    org_id: str
    gmail_user: Optional[str] = None
    gmail_app_password: Optional[str] = None

    model_config = {"env_file": ".env"}


settings = Settings()
