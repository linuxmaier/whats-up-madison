from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://whatsup:whatsup@localhost:5432/whatsup"
    environment: str = "development"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    anthropic_api_key: str = ""
    tagger_model: str = "claude-haiku-4-5"

    def get_cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    model_config = {"env_file": ".env"}


settings = Settings()
