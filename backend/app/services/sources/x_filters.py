"""Shared X engagement thresholds for discovery."""

from typing import Optional


def passes_viral_threshold(
    post: dict,
    *,
    min_likes: int = 0,
    min_impressions: int = 0,
) -> bool:
    """Keep posts that meet either the like floor or impression floor."""
    if min_likes <= 0 and min_impressions <= 0:
        return True

    likes = post.get("likes", 0) or 0
    impressions = post.get("impressions") or 0

    if min_likes > 0 and likes >= min_likes:
        return True
    if min_impressions > 0 and impressions >= min_impressions:
        return True
    return False


def filter_viral_posts(
    posts: list[dict],
    *,
    min_likes: int = 0,
    min_impressions: int = 0,
) -> list[dict]:
    if min_likes <= 0 and min_impressions <= 0:
        return posts
    return [
        p
        for p in posts
        if passes_viral_threshold(p, min_likes=min_likes, min_impressions=min_impressions)
    ]
