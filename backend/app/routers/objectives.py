import asyncio
import json
import logging
import time
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import EvidencePost, Objective, Topic
from app.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    GenerateDraftsRequest,
    GenerateImageRequest,
    GenerateImageResponse,
    GenerateVideoRequest,
    ObjectiveCreate,
    ObjectiveOut,
    TopicOut,
    TrendItemOut,
    VideoJobStart,
    VideoJobStatus,
)
from app.services.image_service import image_service
from app.services.video_service import video_service
from app.services.objective_parser import score_post_relevance
from app.services.principle_context import build_parsed_objective
from app.run_settings import RunSettings
from app.services.pipeline import analysis_pipeline
from app.services.trend_analysis import trend_analysis_service
from app.services.url_utils import resolve_post_urls
from app.services.x_api import XAPIError, x_api_service

router = APIRouter(prefix="/api/objectives", tags=["objectives"])
logger = logging.getLogger(__name__)

# In-memory store for async video jobs: job_id -> {status, ts, result fields | error}.
# Single-worker dev server; jobs are pruned after an hour.
_VIDEO_JOBS: dict = {}


def _evidence_to_posts(topic: Topic, parsed) -> list[dict]:
    posts = []
    for ev in topic.evidence_posts:
        post = {
            "id": str(ev.id),
            "source": ev.source or "x",
            "text": ev.post_text,
            "title": None,
            "created_at": ev.posted_at.isoformat() if ev.posted_at else None,
            "author_name": ev.author_name,
            "author_handle": ev.author_handle,
            "post_url": ev.post_url,
            "likes": ev.likes or 0,
            "retweets": ev.retweets or 0,
            "replies": ev.replies or 0,
            "comments": ev.replies or 0,
            "impressions": ev.impressions,
        }
        if ev.source == "news" or ev.source == "industry":
            post["engagement_proxy"] = 45
        post["_relevance"] = score_post_relevance(ev.post_text, parsed, "")
        posts.append(post)
    return posts


@router.post("", response_model=ObjectiveOut, status_code=201)
def create_objective(payload: ObjectiveCreate, db: Session = Depends(get_db)):
    objective = Objective(
        text=payload.text.strip(),
        status="pending",
        principle_id=payload.principle_id,
    )
    db.add(objective)
    db.commit()
    db.refresh(objective)
    return objective


@router.get("", response_model=List[ObjectiveOut])
def list_objectives(db: Session = Depends(get_db)):
    return (
        db.query(Objective)
        .options(
            joinedload(Objective.search_queries),
            joinedload(Objective.topics).joinedload(Topic.evidence_posts),
        )
        .order_by(Objective.created_at.desc())
        .limit(50)
        .all()
    )


@router.delete("")
def clear_objectives(db: Session = Depends(get_db)):
    """Permanently delete all objectives and related analysis data."""
    objectives = db.query(Objective).all()
    count = len(objectives)
    for objective in objectives:
        db.delete(objective)
    db.commit()
    return {"deleted": count}


@router.delete("/{objective_id}")
def delete_objective(objective_id: int, db: Session = Depends(get_db)):
    """Permanently delete one objective and related analysis data."""
    objective = db.query(Objective).filter(Objective.id == objective_id).first()
    if not objective:
        raise HTTPException(status_code=404, detail="Objective not found")
    db.delete(objective)
    db.commit()
    return {"deleted": objective_id}


@router.get("/{objective_id}", response_model=ObjectiveOut)
def get_objective(objective_id: int, db: Session = Depends(get_db)):
    objective = (
        db.query(Objective)
        .options(
            joinedload(Objective.search_queries),
            joinedload(Objective.topics).joinedload(Topic.evidence_posts),
        )
        .filter(Objective.id == objective_id)
        .first()
    )
    if not objective:
        raise HTTPException(status_code=404, detail="Objective not found")
    return objective


@router.post("/{objective_id}/analyze", response_model=AnalyzeResponse)
async def analyze_objective(
    objective_id: int,
    body: AnalyzeRequest = AnalyzeRequest(),
    db: Session = Depends(get_db),
):
    objective = db.query(Objective).filter(Objective.id == objective_id).first()
    if not objective:
        raise HTTPException(status_code=404, detail="Objective not found")

    if objective.status not in ("pending", "completed", "failed"):
        raise HTTPException(
            status_code=409,
            detail=f"Analysis already in progress (status: {objective.status})",
        )

    rs = body.run_settings.to_run_settings() if body.run_settings else RunSettings.from_env()

    try:
        result = await analysis_pipeline.run(db, objective, run_settings=rs)
        return AnalyzeResponse(
            objective=result,
            message="Analysis completed successfully",
        )
    except XAPIError as e:
        objective.status = "failed"
        db.commit()
        raise HTTPException(status_code=e.status_code or 502, detail=str(e))
    except Exception as e:
        objective.status = "failed"
        db.commit()
        logger.exception("Analysis failed for objective %s", objective_id)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.post(
    "/{objective_id}/topics/{topic_id}/regenerate-draft", response_model=TopicOut
)
async def regenerate_draft(
    objective_id: int,
    topic_id: int,
    draft_index: int = 0,
    db: Session = Depends(get_db),
):
    """Generate a fresh LinkedIn draft variation for a single topic."""
    topic = (
        db.query(Topic)
        .options(joinedload(Topic.evidence_posts))
        .filter(Topic.id == topic_id, Topic.objective_id == objective_id)
        .first()
    )
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    objective = db.query(Objective).filter(Objective.id == objective_id).first()
    if not objective:
        raise HTTPException(status_code=404, detail="Objective not found")

    try:
        topic_query = " ".join(
            filter(
                None,
                [topic.name, topic.why_trending or "", topic.specific_event or "", objective.text],
            )
        )
        parsed = await build_parsed_objective(db, objective, topic_query=topic_query)
        posts = _evidence_to_posts(topic, parsed)
        await resolve_post_urls(posts)
        new_draft = await trend_analysis_service.regenerate_draft(
            topic_name=topic.name,
            posts=posts,
            parsed=parsed,
            previous_draft=topic.linkedin_draft or "",
            why_trending=topic.why_trending or "",
            specific_event=topic.specific_event or "",
            linkedin_angle=topic.linkedin_angle or "",
        )

        drafts = []
        if topic.linkedin_drafts:
            try:
                drafts = json.loads(topic.linkedin_drafts)
            except json.JSONDecodeError:
                drafts = []

        if not drafts:
            drafts = [{"label": "Default", "style": "general", "text": topic.linkedin_draft or ""}]

        idx = max(0, min(draft_index, len(drafts) - 1))
        drafts[idx] = {
            **drafts[idx],
            "text": new_draft,
        }
        topic.linkedin_drafts = json.dumps(drafts)
        topic.linkedin_draft = drafts[0]["text"] if drafts else new_draft
        db.commit()
        db.refresh(topic)
        return topic
    except Exception as e:
        logger.exception("Draft regeneration failed for topic %s", topic_id)
        raise HTTPException(status_code=500, detail=f"Regeneration failed: {str(e)}")


@router.post(
    "/{objective_id}/topics/{topic_id}/generate-drafts", response_model=TopicOut
)
async def generate_drafts(
    objective_id: int,
    topic_id: int,
    body: GenerateDraftsRequest,
    db: Session = Depends(get_db),
):
    """Generate LinkedIn drafts on demand for selected styles (user-triggered, saves cost)."""
    topic = (
        db.query(Topic)
        .options(joinedload(Topic.evidence_posts))
        .filter(Topic.id == topic_id, Topic.objective_id == objective_id)
        .first()
    )
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    objective = db.query(Objective).filter(Objective.id == objective_id).first()
    if not objective:
        raise HTTPException(status_code=404, detail="Objective not found")

    try:
        topic_query = " ".join(
            filter(
                None,
                [topic.name, topic.why_trending or "", topic.specific_event or "", objective.text],
            )
        )
        parsed = await build_parsed_objective(db, objective, topic_query=topic_query)
        posts = _evidence_to_posts(topic, parsed)
        await resolve_post_urls(posts)
        result = await trend_analysis_service.generate_drafts(
            topic_name=topic.name,
            posts=posts,
            parsed=parsed,
            style_keys=body.styles,
        )
        topic.linkedin_drafts = json.dumps(result.get("linkedin_drafts") or [])
        topic.linkedin_draft = result.get("linkedin_draft")
        db.commit()
        db.refresh(topic)
        return topic
    except Exception as e:
        logger.exception("Draft generation failed for topic %s", topic_id)
        raise HTTPException(status_code=500, detail=f"Draft generation failed: {str(e)}")


@router.post(
    "/{objective_id}/topics/{topic_id}/generate-image",
    response_model=GenerateImageResponse,
)
async def generate_topic_image(
    objective_id: int,
    topic_id: int,
    payload: GenerateImageRequest,
    db: Session = Depends(get_db),
):
    """On-demand LinkedIn post image generation (costs OpenAI credits — user-triggered only)."""
    topic = (
        db.query(Topic)
        .filter(Topic.id == topic_id, Topic.objective_id == objective_id)
        .first()
    )
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    if not image_service.is_configured:
        raise HTTPException(
            status_code=503,
            detail="Image generation not configured. Add OPENAI_API_KEY to .env (GPT Image).",
        )

    try:
        result = await image_service.generate(
            prompt=payload.custom_prompt,
            mode=payload.mode,
            previous_prompt=payload.previous_prompt,
            edit_instruction=payload.edit_instruction or payload.custom_prompt,
            draft_text=payload.draft_text,
            topic_name=payload.topic_name or topic.name,
            draft_style=payload.draft_style,
            draft_label=payload.draft_label,
            user_hint=payload.custom_prompt if payload.mode == "new" else "",
        )
        return GenerateImageResponse(**result)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.exception("Image generation failed for topic %s", topic_id)
        raise HTTPException(status_code=500, detail=f"Image generation failed: {str(e)}")


async def _run_video_job(job_id: str, draft_text: str, topic_name: str, hint: str, voiceover: bool):
    """Background worker: generates the video and records the result in _VIDEO_JOBS."""
    try:
        result = await video_service.generate_from_draft(
            draft_text=draft_text,
            topic_name=topic_name,
            hint=hint,
            voiceover=voiceover,
        )
        _VIDEO_JOBS[job_id] = {"status": "completed", "ts": time.time(), **result}
    except Exception as e:  # noqa: BLE001 - surface any failure to the poller
        logger.exception("Video job %s failed", job_id)
        _VIDEO_JOBS[job_id] = {"status": "failed", "ts": time.time(), "error": str(e)}


def _prune_video_jobs(max_age: float = 3600.0):
    """Drop finished jobs older than an hour so the in-memory store stays small."""
    now = time.time()
    stale = [
        jid for jid, job in _VIDEO_JOBS.items()
        if job.get("status") in ("completed", "failed") and now - job.get("ts", now) > max_age
    ]
    for jid in stale:
        _VIDEO_JOBS.pop(jid, None)


@router.post(
    "/{objective_id}/topics/{topic_id}/generate-video",
    response_model=VideoJobStart,
)
async def generate_topic_video(
    objective_id: int,
    topic_id: int,
    payload: GenerateVideoRequest,
    db: Session = Depends(get_db),
):
    """Start a text-to-video job (OpenAI Sora) from the draft content and return a job id.

    Generation takes minutes, so it runs in the background; poll the status endpoint for the
    result. Costs Sora credits — user-triggered only.
    """
    topic = (
        db.query(Topic)
        .filter(Topic.id == topic_id, Topic.objective_id == objective_id)
        .first()
    )
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    if not video_service.is_configured:
        raise HTTPException(
            status_code=503,
            detail="Video generation not configured. Add OPENAI_API_KEY to backend/.env (OpenAI Sora).",
        )

    _prune_video_jobs()
    job_id = uuid.uuid4().hex
    _VIDEO_JOBS[job_id] = {"status": "processing", "ts": time.time()}
    asyncio.create_task(
        _run_video_job(
            job_id,
            payload.draft_text,
            payload.topic_name or topic.name,
            payload.motion_hint,
            payload.voiceover,
        )
    )
    return VideoJobStart(job_id=job_id, status="processing")


@router.get(
    "/{objective_id}/topics/{topic_id}/generate-video/{job_id}",
    response_model=VideoJobStatus,
)
async def get_video_job(objective_id: int, topic_id: int, job_id: str):
    """Poll a video job started by generate-video."""
    job = _VIDEO_JOBS.get(job_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail="Video job not found (it may have expired or the server restarted).",
        )
    return VideoJobStatus(
        status=job.get("status", "processing"),
        video_url=job.get("video_url"),
        prompt_used=job.get("prompt_used"),
        filename=job.get("filename"),
        voiceover_script=job.get("voiceover_script"),
        error=job.get("error"),
    )


@router.get("/trends/location", response_model=List[TrendItemOut])
async def get_location_trends():
    """Optional broad signal — trends by location from X."""
    try:
        trends = await x_api_service.get_trends_by_location()
        return trends
    except XAPIError as e:
        raise HTTPException(status_code=e.status_code or 502, detail=str(e))
