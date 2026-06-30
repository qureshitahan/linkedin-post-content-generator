"""Normalized post shape and the Source protocol.

Every source converts its platform-specific payload into a NormalizedPost
dict. We keep the original X-style keys (likes/retweets/replies/impressions)
so existing scoring code keeps working, and add `source` + `comments` so the
pipeline can treat Reddit/HN/X uniformly.
"""

from typing import List, Optional, Protocol, TypedDict, runtime_checkable


class NormalizedPost(TypedDict, total=False):
    id: str
    source: str  # "x" | "reddit" | "hackernews" | "arxiv" | "pubmed" | ...
    content_type: Optional[str]  # research_paper | research_buzz | news | social
    text: str
    title: Optional[str]
    created_at: Optional[str]  # ISO8601 UTC
    author_name: str
    author_handle: str
    post_url: str
    # Engagement (mapped per platform so legacy scoring keeps working):
    likes: int  # X likes / Reddit upvotes / HN points
    retweets: int  # X reposts (0 for Reddit/HN)
    replies: int  # X replies / Reddit+HN comment count
    comments: int  # explicit comment count (== replies for Reddit/HN)
    impressions: Optional[int]


@runtime_checkable
class Source(Protocol):
    name: str

    @property
    def is_configured(self) -> bool:
        ...

    async def search(self, query: str, max_results: int = 20) -> List[NormalizedPost]:
        ...
