import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.routers import health, images, objectives

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="LinkedIn Content Intelligence Engine",
    description="Phase 1: X-powered trending topic discovery and LinkedIn post generation",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(objectives.router)
app.include_router(images.router)


@app.on_event("startup")
def on_startup():
    init_db()
    logger.info("Database initialized")
    logger.info(f"X API configured: {bool(settings.x_bearer_token)}")
    logger.info(f"Anthropic configured: {bool(settings.anthropic_api_key)}")
