"""
Core configuration and settings for the application.
Uses environment variables with sensible defaults.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "Competitor Matcher API"
    app_version: str = "1.0.0"
    debug: bool = Field(default=False, description="Enable debug mode")

    # Paths
    data_dir: Path = Field(
        default_factory=lambda: get_project_root() / "data",
        description="Directory containing data files",
    )
    output_dir: Path = Field(
        default_factory=lambda: get_project_root() / "output",
        description="Directory for output files",
    )

    # API Keys
    openrouter_api_key: str = Field(default="", description="OpenRouter API key for AI agent")
    brave_api_key: str = Field(default="", description="Brave Search API key")

    # AI Agent Settings
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        description="OpenRouter API base URL",
    )
    openrouter_model: str = Field(
        default="anthropic/claude-sonnet-4",
        description="Model to use for AI agent",
    )

    # Qdrant Settings
    qdrant_url: str = Field(
        default="http://localhost:6333", description="Qdrant server URL"
    )
    qdrant_collection: str = Field(
        default="products", description="Qdrant collection name"
    )

    # Embedding Settings
    embedding_model: str = Field(
        default="openai/text-embedding-3-small", description="Embedding model name"
    )
    embedding_dim: int = Field(default=1536, description="Embedding dimension")

    # Matching Settings
    match_threshold: float = Field(
        default=0.80, description="Minimum score threshold for product matching"
    )
    exact_match_threshold: float = Field(
        default=0.40, description="Threshold for exact field matching"
    )
    price_range_factor: float = Field(
        default=0.30, description="Price range factor (±30%)"
    )

    # Request Limits
    max_sources_default: int = Field(
        default=5, description="Default maximum sources per query"
    )
    max_competitors_default: int = Field(
        default=12, description="Default maximum competitors per source"
    )

    # CORS Settings
    cors_origins: list[str] = Field(
        default=[
            "http://localhost:8080",
            "http://127.0.0.1:8080",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
        ],
        description="Allowed CORS origins",
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
