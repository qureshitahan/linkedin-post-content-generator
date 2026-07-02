"""Cluster a pool of on-topic posts into coherent themes (topics).

Replaces the old "one search query = one topic" logic. Because clustering runs
*after* relevance filtering, every resulting theme is grounded in posts that
actually match the user's goal — across X, Reddit, and Hacker News.
"""

import json
import logging
import re
from collections import defaultdict
from typing import Dict, List

from app.config import settings
from app.services.claude import claude_service
from app.services.objective_parser import ParsedObjective, score_post_relevance

logger = logging.getLogger(__name__)


class TopicClusteringService:
    @property
    def is_configured(self) -> bool:
        return claude_service.is_configured

    def _format_posts(self, posts: List[Dict]) -> str:
        lines = []
        for i, p in enumerate(posts):
            snippet = re.sub(r"\s+", " ", p.get("text", ""))[:240]
            lines.append(
                f"[{i}] ({p.get('source', '?')}) "
                f"{p.get('likes', 0)}↑ {p.get('comments', p.get('replies', 0))}💬 :: {snippet}"
            )
        return "\n".join(lines)

    def _min_posts_for_theme(self, total_posts: int) -> int:
        if total_posts <= 3:
            return 1
        return settings.min_relevant_posts_per_topic

    def _query_cluster(self, posts: List[Dict]) -> List[Dict]:
        """When data is thin, group by search query so multiple angles still surface."""
        buckets: Dict[str, List[int]] = defaultdict(list)
        for i, p in enumerate(posts):
            q = (p.get("_query") or "").strip()
            if q:
                buckets[q].append(i)

        themes = []
        for query, idxs in sorted(buckets.items(), key=lambda item: len(item[1]), reverse=True):
            label = query if len(query) <= 60 else f"{query[:57]}..."
            themes.append({"name": label, "post_indices": idxs})

        return themes[: settings.max_topics_to_analyze]

    async def cluster(
        self, posts: List[Dict], parsed: ParsedObjective
    ) -> List[Dict]:
        """Return [{name, post_indices: [..]}], best themes first."""
        if not posts:
            return []

        min_posts = self._min_posts_for_theme(len(posts))

        if len(posts) <= settings.target_min_topics * 2:
            query_themes = self._query_cluster(posts)
            if len(query_themes) >= 2:
                return query_themes

        if not self.is_configured or len(posts) < min_posts:
            return self._fallback_cluster(posts, parsed, min_posts)

        max_topics = settings.max_topics_to_analyze
        posts_block = self._format_posts(posts[:60])

        prompt = f"""You group social posts into specific, post-worthy THEMES for a LinkedIn writer.

{parsed.prompt_block()}

On-topic posts (already filtered to match the goal), indexed:
{posts_block}

TASK:
Group these posts into {max_topics} or fewer SPECIFIC themes that this writer could post about.
- Each theme must be a concrete sub-topic, debate, tool, or shift — not a broad category.
- Only include a theme if at least {min_posts} post(s) support it.
- A post can belong to at most one theme. Skip posts that don't fit a strong theme.
- Order themes from most to least post-worthy for THIS writer.

Return ONLY JSON:
{{"themes": [{{"name": "specific theme name (<=8 words)", "post_indices": [0, 3, 7]}}]}}"""

        try:
            content = claude_service.complete(
                prompt=prompt,
                system="You cluster posts into specific themes. Output only valid JSON.",
                model=settings.anthropic_model_fast,
                max_tokens=1024,
                temperature=0.3,
            )
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\n?", "", content)
                content = re.sub(r"\n?```$", "", content)

            data = json.loads(content)
            themes = []
            for t in data.get("themes", []):
                name = str(t.get("name", "")).strip()
                idxs = [
                    i
                    for i in t.get("post_indices", [])
                    if isinstance(i, int) and 0 <= i < len(posts)
                ]
                if name and len(idxs) >= min_posts:
                    themes.append({"name": name, "post_indices": idxs})

            if themes:
                return themes[:max_topics]
        except Exception as e:
            logger.error(f"Theme clustering failed: {e}")

        query_themes = self._query_cluster(posts)
        if query_themes:
            return query_themes

        return self._fallback_cluster(posts, parsed, min_posts)

    def _fallback_cluster(
        self, posts: List[Dict], parsed: ParsedObjective, min_posts: int
    ) -> List[Dict]:
        """Group posts by the focus domain / keyword they match most strongly."""
        anchors = (parsed.focus_domains or []) + (parsed.relevance_keywords or [])
        anchors = [a for a in anchors if a][:8]

        catch_all_name = (
            parsed.focus_domains[0]
            if parsed.focus_domains
            else (parsed.relevance_keywords[0] if parsed.relevance_keywords else "Relevant discussion")
        )

        if not anchors:
            return [
                {
                    "name": catch_all_name,
                    "post_indices": list(range(len(posts))),
                }
            ]

        buckets: Dict[str, List[int]] = {a: [] for a in anchors}
        for i, p in enumerate(posts):
            text = p.get("text", "").lower()
            best = None
            for a in anchors:
                if a.lower() in text:
                    best = a
                    break
            if best is not None:
                buckets[best].append(i)

        themes = [
            {"name": name, "post_indices": idxs}
            for name, idxs in buckets.items()
            if len(idxs) >= min_posts
        ]
        themes.sort(
            key=lambda t: sum(
                score_post_relevance(posts[i].get("text", ""), parsed, posts[i].get("_query", ""))
                for i in t["post_indices"]
            ),
            reverse=True,
        )

        if not themes:
            query_themes = self._query_cluster(posts)
            if query_themes:
                return query_themes
            themes = [
                {
                    "name": catch_all_name,
                    "post_indices": list(range(min(len(posts), 10))),
                }
            ]
        return themes[: settings.max_topics_to_analyze]


topic_clustering_service = TopicClusteringService()
