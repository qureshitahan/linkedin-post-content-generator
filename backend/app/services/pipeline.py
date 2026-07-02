import json
import logging
from collections import Counter
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import EvidencePost, Objective, SearchQuery, Topic
from app.services.objective_parser import score_post_relevance
from app.services.principle_context import build_parsed_objective
from app.services.query_expansion import query_expansion_service
from app.services.sources import source_aggregator
from app.services.topic_clustering import topic_clustering_service
from app.services.topic_scoring import (
    compute_engagement_score,
    compute_freshness_score,
    compute_relevance_score,
    compute_topic_score,
    compute_volume_score,
)
from app.services.trend_analysis import trend_analysis_service
from app.services.x_api import x_api_service
from app.run_settings import RunSettings, apply_run_settings
from app.services.url_utils import resolve_post_urls

logger = logging.getLogger(__name__)


def _is_dead_x_post(post: dict) -> bool:
    """An X post with no traction from a small account = not worth citing."""
    if post.get("source") != "x":
        return False
    likes = post.get("likes", 0) or 0
    retweets = post.get("retweets", 0) or 0
    replies = post.get("replies", 0) or 0
    impressions = post.get("impressions") or 0
    followers = post.get("author_followers", 0) or 0
    verified = post.get("author_verified", False)
    engaged = likes > 0 or retweets > 0 or replies > 1 or impressions >= 500
    notable_author = verified or followers >= 2000
    return not engaged and not notable_author


class AnalysisPipeline:
    """
    Relevance-first, multi-source workflow:

    Objective → parse (goal + communities) → expand queries →
    gather posts from Reddit / Hacker News / X → keep only ON-TOPIC posts →
    cluster into themes → score (relevance-first) → analyze → LinkedIn draft.
    """

    async def run(self, db: Session, objective: Objective, run_settings: Optional[RunSettings] = None) -> Objective:
        rs = run_settings or RunSettings.from_json(objective.run_settings)
        objective.run_settings = rs.to_json()
        db.commit()

        with apply_run_settings(rs):
            return await self._run_pipeline(db, objective, rs)

    async def _run_pipeline(self, db: Session, objective: Objective, rs: RunSettings) -> Objective:
        objective.status = "expanding_queries"
        db.commit()

        # Optional broad X trend hints (only if X is configured)
        trend_hints = []
        if x_api_service.is_configured:
            try:
                trends = await x_api_service.get_trends_by_location()
                trend_hints = [t["name"] for t in trends if t.get("name")]
            except Exception as e:
                logger.warning(f"Trends by location skipped: {e}")

        # Step 1: Parse goal + principle documents into structured writer context
        parsed = await build_parsed_objective(db, objective)

        # Step 2: Expand objective into search queries
        queries = await query_expansion_service.expand_objective(parsed, trend_hints)

        db.query(SearchQuery).filter(SearchQuery.objective_id == objective.id).delete()
        for q in queries:
            db.add(SearchQuery(objective_id=objective.id, query_text=q))
        db.commit()

        # Step 3: Gather posts across all enabled + configured sources
        objective.status = "fetching_posts"
        db.commit()

        gathered = await source_aggregator.gather(
            queries=queries,
            subreddits=parsed.subreddits,
            per_query=rs.posts_per_query,
        )
        pool = gathered["posts"]
        raw_by_query = gathered.get("by_query", {})
        active_sources = gathered["active_sources"]
        await resolve_post_urls(pool)
        objective.sources_used = ",".join(active_sources)
        db.commit()

        # Step 4: Relevance gate — keep only on-topic posts (the key fix)
        objective.status = "selecting_topics"
        db.commit()

        for p in pool:
            p["_relevance"] = score_post_relevance(
                p.get("text", ""),
                parsed,
                p.get("_query", ""),
            )

        relevant = [p for p in pool if p["_relevance"] > 0]
        if len(relevant) < settings.target_min_topics:
            soft = sorted(
                [p for p in pool if p["_relevance"] >= 0],
                key=lambda p: p["_relevance"],
                reverse=True,
            )
            if len(soft) > len(relevant):
                relevant = soft[: max(25, settings.target_min_topics * 8)]

        # Drop dead X posts (no traction) when we still have enough real signal,
        # so we stop citing 2-impression tweets from no-name accounts.
        if settings.drop_dead_x_posts:
            alive = [p for p in relevant if not _is_dead_x_post(p)]
            if len(alive) >= settings.min_relevant_posts_per_topic:
                relevant = alive

        relevant.sort(key=lambda p: p["_relevance"], reverse=True)

        # Record gathered vs on-topic counts per query
        relevant_by_query: Counter = Counter(p.get("_query", "") for p in relevant)
        search_queries = (
            db.query(SearchQuery).filter(SearchQuery.objective_id == objective.id).all()
        )
        for sq in search_queries:
            sq.raw_post_count = raw_by_query.get(sq.query_text, 0)
            sq.post_count = relevant_by_query.get(sq.query_text, 0)
            sq.count_checked_at = datetime.utcnow()
        db.commit()

        # Clear previous topics
        db.query(Topic).filter(Topic.objective_id == objective.id).delete()
        db.commit()

        if not relevant:
            objective.status = "completed"
            db.commit()
            db.refresh(objective)
            return objective

        # Step 5: Cluster on-topic posts into specific themes
        themes = await topic_clustering_service.cluster(relevant, parsed)

        # Step 6: Score every theme (relevance-first)
        theme_sizes = [len(t["post_indices"]) for t in themes] or [1]
        candidates = []
        for theme in themes:
            posts = [relevant[i] for i in theme["post_indices"]]
            if not posts:
                continue

            relevances = [p.get("_relevance", 0.0) for p in posts]
            rel_score = compute_relevance_score(relevances)
            eng_score = compute_engagement_score(posts)
            fresh_score = compute_freshness_score(posts)
            vol_score = compute_volume_score(len(posts), theme_sizes)
            total = compute_topic_score(
                rel_score,
                eng_score,
                fresh_score,
                vol_score,
                settings.weight_relevance,
                settings.weight_engagement,
                settings.weight_freshness,
                settings.weight_volume,
            )
            candidates.append(
                {
                    "name": theme["name"],
                    "posts": posts,
                    "relevance_score": rel_score,
                    "engagement_score": eng_score,
                    "freshness_score": fresh_score,
                    "volume_score": vol_score,
                    "score": total,
                }
            )

        candidates.sort(key=lambda c: c["score"], reverse=True)
        candidates = candidates[: rs.max_topics_to_analyze]

        # Step 7: Analyze each theme (discovery only — drafts generated on demand)
        objective.status = "analyzing_trends"
        db.commit()

        for cand in candidates:
            posts = cand["posts"]
            analysis = await trend_analysis_service.analyze_topic_discovery(
                topic_name=cand["name"],
                query_used=cand["name"],
                posts=posts,
                parsed=parsed,
            )

            source_counts = Counter(p.get("source", "?") for p in posts)
            sources_summary = ", ".join(
                f"{src}:{n}" for src, n in source_counts.most_common()
            )

            topic = Topic(
                objective_id=objective.id,
                name=cand["name"],
                query_used=cand["name"],
                score=cand["score"],
                relevance_score=cand["relevance_score"],
                volume_score=cand["volume_score"],
                freshness_score=cand["freshness_score"],
                engagement_score=cand["engagement_score"],
                post_count=len(posts),
                sources_summary=sources_summary,
                why_trending=analysis["why_trending"],
                specific_event=analysis["specific_event"],
                why_matters=analysis["why_matters"],
                linkedin_angle=analysis["linkedin_angle"],
                linkedin_draft=analysis.get("linkedin_draft"),
                linkedin_drafts=json.dumps(analysis.get("linkedin_drafts") or []),
            )
            db.add(topic)
            db.flush()

            # Evidence: most on-topic first, then most engaged
            sorted_posts = sorted(
                posts,
                key=lambda p: (
                    p.get("_relevance", 0.0),
                    p.get("likes", 0) + p.get("comments", p.get("replies", 0)) * 2,
                ),
                reverse=True,
            )
            for post in sorted_posts[:5]:
                posted_at = self._parse_dt(post.get("created_at"))
                db.add(
                    EvidencePost(
                        topic_id=topic.id,
                        source=post.get("source", "x"),
                        content_type=post.get("content_type"),
                        post_text=post.get("text", ""),
                        author_name=post.get("author_name", "Unknown"),
                        author_handle=post.get("author_handle", "unknown"),
                        post_url=post.get("post_url", ""),
                        posted_at=posted_at,
                        likes=post.get("likes", 0),
                        retweets=post.get("retweets", 0),
                        replies=post.get("replies", post.get("comments", 0)),
                        impressions=post.get("impressions"),
                    )
                )

        objective.status = "completed"
        db.commit()
        db.refresh(objective)
        return objective

    @staticmethod
    def _parse_dt(value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None


analysis_pipeline = AnalysisPipeline()
