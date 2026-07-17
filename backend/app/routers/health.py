from fastapi import APIRouter

from app.config import settings
from app.schemas import HealthOut
from app.services.image_service import image_service
from app.services.video_service import video_service
from app.services.sources import source_aggregator
from app.services.sources.arxiv_source import arxiv_source
from app.services.sources.devto_source import devto_source
from app.services.sources.preprint_source import preprint_source
from app.services.sources.pubmed_source import pubmed_source
from app.services.sources.reddit_source import reddit_source
from app.services.sources.x_research_source import x_research_source

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthOut)
def health_check():
    return HealthOut(
        status="ok",
        x_api_configured=bool(
            settings.x_bearer_token and settings.x_bearer_token != "your_x_bearer_token_here"
        ),
        anthropic_configured=bool(
            settings.anthropic_api_key and settings.anthropic_api_key != "your_anthropic_api_key_here"
        ),
        openai_configured=image_service.is_configured,
        openai_key_last4=image_service.key_last4 if image_service.is_configured else "",
        image_generation_ready=image_service.is_configured and image_service.prompt_engine_available,
        video_configured=video_service.is_configured,
        video_key_last4=video_service.key_last4 if video_service.is_configured else "",
        video_generation_ready=video_service.is_configured,
        reddit_configured=reddit_source.is_configured,
        arxiv_configured=arxiv_source.is_configured,
        pubmed_configured=pubmed_source.is_configured,
        preprint_configured=preprint_source.is_configured,
        devto_configured=devto_source.is_configured,
        x_research_configured=x_research_source.is_configured,
        hackernews_configured=True,
        news_configured=True,
        industry_configured=True,
        active_sources=source_aggregator.active_sources(),
    )
