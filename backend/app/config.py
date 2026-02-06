import os
from pathlib import Path
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
# os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"

class Settings(BaseModel):
    # Project Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    UPLOAD_DIR: Path = BASE_DIR / "storage" / "documents"
    CACHE_DIR: Path = BASE_DIR / "storage" / "cache"

    # API Settings
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "KG Web Platform"
    
    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev_secret_key_change_in_prod")
    CORS_ORIGINS: list = ["*"]
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./sql_app.db") # Default to SQLite for Lite Mode
    
    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # LLM (Direct OpenAI)
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    
    # Model Pricing (USD per 1M tokens) - Input, Output
    MODEL_PRICING: dict = {
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4o": (2.50, 10.00),
        "o1-mini": (3.00, 12.00)
    }
    
    # Pipeline Config
    MAX_WORKERS: int = int(os.getenv("MAX_WORKERS", 1)) # Default 1 for Lite Mode
    CACHE_TTL: int = 604800 # 7 Days
    
    class Config:
        case_sensitive = True

settings = Settings()

# Ensure directories exist
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
settings.CACHE_DIR.mkdir(parents=True, exist_ok=True)
