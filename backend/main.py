import uvicorn
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings

# Route imports
from app.api.routes import documents, pipeline, graphs, ontology, nadia

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="KG Web Platform API",
    description="Backend para o sistema Multimodal GraphRAG da Fundação Seade",
    version="1.0.0"
)

# Configuring CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Routers
app.include_router(documents.router, prefix=f"{settings.API_V1_STR}/documents")
app.include_router(pipeline.router, prefix=f"{settings.API_V1_STR}/pipeline")
app.include_router(graphs.router, prefix=f"{settings.API_V1_STR}/graphs")
app.include_router(ontology.router, prefix=f"{settings.API_V1_STR}/ontology")
app.include_router(nadia.router, prefix=f"{settings.API_V1_STR}/nadia")

@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0", "framework": "fastapi"}

if __name__ == "__main__":
    logger.info(f"Starting server on port {settings.PORT}...")
    uvicorn.run(app, host="0.0.0.0", port=settings.PORT)
