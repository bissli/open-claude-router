"""Configuration management for open-claude-router."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    """Application configuration loaded from environment variables."""

    openrouter_base_url: str = os.getenv(
        'OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1'
    )
    openrouter_api_key: str | None = os.getenv('OPENROUTER_API_KEY')
    model_override: str | None = os.getenv('MODEL_OVERRIDE')
    host: str = os.getenv('HOST', '0.0.0.0')
    port: int = int(os.getenv('PORT', '8787'))


config = Config()
