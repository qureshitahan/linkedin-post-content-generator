import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def normalize_score(value: float, min_val: float, max_val: float) -> float:
    """Normalize a value to 0-1 range."""
    if max_val <= min_val:
        return 0.5 if value > 0 else 0.0
    return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))


def compute_freshness_score(posts: list[dict]) -> float:
    """
    Score based on how recent the conversation is.
    Posts from the last 24h score highest; decay over 7 days.
    """
    if not posts:
        return 0.0

    now = datetime.now(timezone.utc)
    freshness_values = []

    for post in posts:
        created = post.get("created_at")
        if not created:
            continue
        if isinstance(created, str):
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        age_hours = (now - created).total_seconds() / 3600

        if age_hours <= 24:
            freshness_values.append(1.0)
        elif age_hours <= 72:
            freshness_values.append(0.7)
        elif age_hours <= 168:
            freshness_values.append(0.4)
        else:
            freshness_values.append(0.1)

    if not freshness_values:
        return 0.3

    return sum(freshness_values) / len(freshness_values)


def compute_engagement_score(posts: list[dict]) -> float:
    """
    Score based on engagement metrics from pulled posts.
    Uses weighted sum of likes, retweets, and replies with log scaling.
    """
    if not posts:
        return 0.0

    total_engagement = 0
    for post in posts:
        proxy = post.get("engagement_proxy")
        if proxy:
            # Sources without like/comment metrics (e.g. curated news) carry a
            # proxy representing editorial pickup.
            total_engagement += proxy
            continue
        likes = post.get("likes", 0) or 0
        retweets = post.get("retweets", 0) or 0
        replies = post.get("replies", 0) or 0
        comments = post.get("comments", 0) or 0
        # Weight reposts and discussion higher — they indicate real traction
        total_engagement += likes + (retweets * 3) + (max(replies, comments) * 2)

    avg_engagement = total_engagement / len(posts)

    # Log scale: 10 avg = ~0.3, 100 = ~0.6, 1000 = ~0.9
    import math

    if avg_engagement <= 0:
        return 0.0
    return min(1.0, math.log10(avg_engagement + 1) / 3)


def compute_volume_score(post_count: int, all_counts: list[int]) -> float:
    """Score based on relative *relevant* post volume compared to other topics."""
    if not all_counts or post_count <= 0:
        return 0.0

    min_count = min(all_counts)
    max_count = max(all_counts)
    return normalize_score(float(post_count), float(min_count), float(max_count))


# A post that hits a focus domain (+2) plus a couple of relevance keywords (+1
# each) lands around 4. Normalize against that ceiling.
RELEVANCE_CEILING = 4.0


def compute_relevance_score(post_relevances: list[float]) -> float:
    """Average on-topic strength of a cluster's posts, normalized to 0-1."""
    positives = [r for r in post_relevances if r > 0]
    if not positives:
        return 0.0
    avg = sum(positives) / len(positives)
    return max(0.0, min(1.0, avg / RELEVANCE_CEILING))


def compute_topic_score(
    relevance_score: float,
    engagement_score: float,
    freshness_score: float,
    volume_score: float,
    weight_relevance: float = 0.45,
    weight_engagement: float = 0.30,
    weight_freshness: float = 0.15,
    weight_volume: float = 0.10,
) -> float:
    """
    Combined topic score — relevance-first.

    Scoring rationale:
    - Relevance (45%): Is this conversation actually about the user's goal?
      (Stops high-volume off-topic noise from ever winning.)
    - Engagement (30%): Are people actively engaging, not just posting?
    - Freshness (15%): Is the conversation happening now?
    - Volume (10%): Is there enough *on-topic* conversation to matter?
    """
    return round(
        (relevance_score * weight_relevance)
        + (engagement_score * weight_engagement)
        + (freshness_score * weight_freshness)
        + (volume_score * weight_volume),
        4,
    )
