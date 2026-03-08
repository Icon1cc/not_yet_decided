"""Core configuration and settings."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "Competitor Matcher API"
    app_version: str = "1.0.0"
    debug: bool = Field(default=False)

    data_dir: Path = Field(default_factory=lambda: get_project_root() / "data")
    output_dir: Path = Field(default_factory=lambda: get_project_root() / "output")

    gemini_api_key: str = Field(default="")
    gemini_model: str = Field(default="gemini-2.0-flash")
    brave_api_key: str = Field(default="")

    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_collection: str = Field(default="products")

    embedding_model: str = Field(default="openai/text-embedding-3-small")
    embedding_dim: int = Field(default=1536)

    match_threshold: float = Field(default=0.80)
    exact_match_threshold: float = Field(default=0.40)
    price_range_factor: float = Field(default=0.30)

    max_sources_default: int = Field(default=5)
    max_competitors_default: int = Field(default=12)

    cors_origins: list[str] = Field(
        default=[
            "http://localhost:8080",
            "http://127.0.0.1:8080",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
        ]
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
