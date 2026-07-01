from datetime import datetime
import json
from typing import Any, List, Literal, Optional

from app.config import settings
from app.run_settings import DRAFT_STYLE_OPTIONS, RunSettings
from pydantic import BaseModel, Field, field_validator, model_validator


class ObjectiveCreate(BaseModel):
    text: str = Field(..., min_length=10, max_length=settings.max_objective_length)
    principle_id: Optional[int] = None


class SearchQueryOut(BaseModel):
    id: int
    query_text: str
    post_count: Optional[int]
    count_checked_at: Optional[datetime]

    model_config = {"from_attributes": True}


class EvidencePostOut(BaseModel):
    id: int
    source: str = "x"
    content_type: Optional[str] = None
    post_text: str
    author_name: str
    author_handle: str
    post_url: str
    posted_at: Optional[datetime]
    likes: int
    retweets: int
    replies: int
    impressions: Optional[int]

    model_config = {"from_attributes": True}


class LinkedInDraftOut(BaseModel):
    label: str
    style: str = "general"
    text: str


class TopicOut(BaseModel):
    id: int
    name: str
    query_used: str
    score: float
    relevance_score: float = 0.0
    volume_score: float
    freshness_score: float
    engagement_score: float
    post_count: int
    sources_summary: Optional[str] = None
    why_trending: Optional[str]
    specific_event: Optional[str]
    why_matters: Optional[str]
    linkedin_angle: Optional[str]
    linkedin_draft: Optional[str]
    linkedin_drafts: List[LinkedInDraftOut] = Field(default_factory=list)
    evidence_posts: List[EvidencePostOut] = []

    model_config = {"from_attributes": True}

    @field_validator("linkedin_drafts", mode="before")
    @classmethod
    def parse_drafts(cls, v: Any) -> list:
        if not v:
            return []
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                return parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                return []
        return v

    @model_validator(mode="after")
    def fill_drafts_from_primary(self) -> "TopicOut":
        if not self.linkedin_drafts and self.linkedin_draft:
            self.linkedin_drafts = [
                LinkedInDraftOut(label="Default", style="general", text=self.linkedin_draft)
            ]
        return self


class RunSettingsIn(BaseModel):
    enabled_sources: List[str] = Field(
        default_factory=lambda: [
            "news", "industry", "hackernews", "arxiv", "pubmed", "preprint", "devto"
        ]
    )
    max_queries_per_source: int = Field(default=5, ge=1, le=15)
    posts_per_query: int = Field(default=15, ge=5, le=50)
    max_topics_to_analyze: int = Field(default=3, ge=1, le=8)
    max_search_queries: int = Field(default=6, ge=3, le=12)
    x_posts_per_query: int = Field(default=10, ge=0, le=30)
    x_research_min_likes: int = Field(default=30, ge=0, le=500)
    x_research_max_queries: int = Field(default=2, ge=0, le=8)
    draft_styles: List[str] = Field(
        default_factory=lambda: [s[0] for s in DRAFT_STYLE_OPTIONS]
    )

    def to_run_settings(self) -> RunSettings:
        return RunSettings.from_dict(self.model_dump())


class AnalyzeRequest(BaseModel):
    run_settings: Optional[RunSettingsIn] = None


class GenerateDraftsRequest(BaseModel):
    styles: List[str] = Field(
        default_factory=lambda: [s[0] for s in DRAFT_STYLE_OPTIONS],
        min_length=1,
        max_length=5,
    )


class ObjectiveOut(BaseModel):
    id: int
    text: str
    status: str
    principle_id: Optional[int] = None
    sources_used: Optional[str] = None
    run_settings: Optional[RunSettingsIn] = None
    created_at: datetime
    updated_at: datetime
    search_queries: List[SearchQueryOut] = []
    topics: List[TopicOut] = []

    model_config = {"from_attributes": True}

    @field_validator("run_settings", mode="before")
    @classmethod
    def parse_run_settings(cls, v: Any):
        if v is None or isinstance(v, RunSettingsIn):
            return v
        if isinstance(v, str):
            try:
                return RunSettingsIn.model_validate(json.loads(v))
            except (json.JSONDecodeError, ValueError):
                return None
        if isinstance(v, dict):
            return RunSettingsIn.model_validate(v)
        return None


class AnalyzeResponse(BaseModel):
    objective: ObjectiveOut
    message: str


class TrendItemOut(BaseModel):
    name: str
    tweet_volume: Optional[int] = None
    url: Optional[str] = None


class HealthOut(BaseModel):
    status: str
    x_api_configured: bool
    anthropic_configured: bool
    openai_configured: bool = False
    openai_key_last4: str = ""
    image_generation_ready: bool = False
    reddit_configured: bool = False
    arxiv_configured: bool = True
    pubmed_configured: bool = True
    preprint_configured: bool = True
    devto_configured: bool = True
    x_research_configured: bool = False
    hackernews_configured: bool = True
    news_configured: bool = True
    industry_configured: bool = True
    active_sources: List[str] = []


class GenerateImageRequest(BaseModel):
    draft_text: str = Field(..., min_length=20, max_length=8000)
    topic_name: str = ""
    draft_style: str = ""
    draft_label: str = ""
    mode: Literal["new", "edit"] = "new"
    custom_prompt: str = ""
    previous_prompt: str = ""
    edit_instruction: str = ""


class GenerateImageResponse(BaseModel):
    image_url: str
    prompt_used: str
    filename: str


class PrincipleDocumentOut(BaseModel):
    id: int
    filename: str
    created_at: datetime
    char_count: int = 0

    model_config = {"from_attributes": True}


class PrincipleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)


class PrincipleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)


class PrincipleOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    documents: List[PrincipleDocumentOut] = []

    model_config = {"from_attributes": True}
