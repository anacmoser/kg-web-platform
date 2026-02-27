import os
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    # Project Paths
    BASE_DIR: Path = Path(__file__).resolve().parent
    STORAGE_DIR: Path = BASE_DIR / "storage"
    UPLOAD_DIR: Path = STORAGE_DIR / "documents"
    CACHE_DIR: Path = STORAGE_DIR / "cache"
    RESULTS_DIR: Path = STORAGE_DIR / "results"
    
    # Graph Storage Paths
    CHROMA_PATH: Path = STORAGE_DIR / "chroma"
    FAISS_INDEX_FILE: Path = STORAGE_DIR / "faiss.index"
    FAISS_MAP_FILE: Path = STORAGE_DIR / "faiss_map.json"
    
    # Chroma Config
    COLLECTION_NAME: str = "graphrag_docs"
    COLLECTION_SEMANTIC_NAME: str = "graphrag_semantic"

    # API Settings
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "KG Web Platform"
    PORT: int = int(os.getenv("PORT", 5000))
    
    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev_secret_key_change_in_prod")
    
    # Process CORS_ORIGINS from env string
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173")
    
    @property
    def cors_origins_list(self) -> list:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./sql_app.db") 
    
    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # LLM (Direct OpenAI)
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")
    
    # Model Pricing (USD per 1M tokens) - Input, Output
    MODEL_PRICING: dict = {
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4o": (2.50, 10.00),
        "o1-mini": (3.00, 12.00),
        "gpt-5.2-thinking": (5.00, 15.00) # Estimated premium pricing
    }
    
    # Pipeline Config
    MAX_WORKERS: int = int(os.getenv("MAX_WORKERS", 1))
    CACHE_TTL: int = 604800 # 7 Days
    
    # SSL Configuration (set to False if encountering hangs on Windows)
    VERIFY_SSL: bool = os.getenv("VERIFY_SSL", "True").lower() == "true"
    
    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

settings = Settings()

# Graph Constants
NodeType = {
    "DOCUMENT": "DOCUMENT",
    "PAGE": "PAGE",
    "SECTION": "SECTION",
    "CHUNK": "CHUNK",
    "IMAGE": "IMAGE",
    "TABLE": "TABLE",
}

EdgeType = {
    "CONTAINS": "CONTAINS",
    "PRECEDES": "PRECEDES",
    "SIMILAR_TO": "SIMILAR_TO",
}

SemanticNodeType = {
    "ENTITY": "ENTITY",
    "CONCEPT": "CONCEPT",
    "EVENT": "EVENT",
}

SemanticEdgeType = {
    "RELATES_TO": "RELATES_TO",
    "DEPENDS_ON": "DEPENDS_ON",
    "PART_OF": "PART_OF",
}

EMBEDDABLE_NODE_TYPES = {
    NodeType["CHUNK"],
    NodeType["IMAGE"],
    NodeType["TABLE"],
    "SUMMARY" 
}

# Ensure directories exist
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
settings.CACHE_DIR.mkdir(parents=True, exist_ok=True)
settings.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
settings.CHROMA_PATH.mkdir(parents=True, exist_ok=True)
