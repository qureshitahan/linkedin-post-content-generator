from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- X / Twitter (optional, demoted signal) ---
    x_bearer_token: str = ""
    x_api_key: str = ""
    x_api_secret: str = ""
    x_trends_woeid: int = 23424977

    # --- Reddit (free tier, OAuth) ---
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_username: str = ""
    reddit_password: str = ""
    reddit_user_agent: str = "LinkedInContentIntelligence/1.0 (by /u/your_username)"
    reddit_max_subreddits: int = 6

    # --- Content sources ---
    # Comma-separated, in priority order. A source only runs if also configured.
    # news + industry + hackernews + arxiv + pubmed + preprint + devto need no keys;
    # x_research needs X API; reddit needs OAuth; x optional.
    enabled_sources: str = "news,industry,hackernews,arxiv,pubmed,preprint,devto,x_research,x"
    # Cap queries fanned out to each source (controls API cost / rate limits)
    max_queries_per_source: int = 8
    # Posts pulled per (query, source) before relevance filtering
    posts_per_query: int = 30
    # How far back to consider news articles "trending"
    news_days_window: int = 14
    # How far back to consider industry RSS articles "trending"
    rss_days_window: int = 14
    # Industry / domain RSS feeds (comma-separated). Defaults cover healthcare,
    # AI/ML, data analytics, and general tech. Off-domain items are filtered out
    # by the relevance gate, so a broad list is safe.
    rss_feeds: str = (
        # Healthcare
        "https://www.statnews.com/feed/,"
        "https://www.fiercehealthcare.com/rss/xml,"
        "https://www.beckershospitalreview.com/feed/,"
        "https://medicalxpress.com/rss-feed/,"
        "https://www.nature.com/nm.rss,"
        "https://www.healthaffairs.org/action/showFeed?type=etoc&feed=rss&jc=hlthaff,"
        "https://www.who.int/rss-feeds/news-english.xml,"
        "https://www.sciencedaily.com/rss/health_medicine.xml,"
        "https://healthtechmagazine.net/rss.xml,"
        # AI / ML
        "https://venturebeat.com/category/ai/feed/,"
        "https://www.technologyreview.com/topic/artificial-intelligence/feed,"
        "https://techcrunch.com/category/artificial-intelligence/feed/,"
        "https://news.mit.edu/rss/topic/artificial-intelligence2,"
        "https://openai.com/blog/rss.xml,"
        "https://blog.google/technology/ai/rss/,"
        "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss,"
        # Data science / analytics
        "https://www.kdnuggets.com/feed,"
        "https://www.analyticsvidhya.com/feed/,"
        "https://towardsdatascience.com/feed,"
        "https://www.zdnet.com/topic/big-data/rss.xml,"
        # General tech
        "https://feeds.arstechnica.com/arstechnica/technology-lab,"
        "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"
    )
    # arXiv categories to search (cs.AI, cs.LG, stat.ML, q-bio.QM = quant bio)
    arxiv_categories: str = "cs.AI,cs.LG,stat.ML,q-bio.QM"
    arxiv_days_window: int = 30
    # Dev.to tags for practitioner articles
    devto_tags: str = "machinelearning,datascience,healthcare,ai,devops"
    devto_days_window: int = 7
    # bioRxiv / medRxiv preprint servers and lookback
    preprint_servers: str = "biorxiv,medrxiv"
    preprint_days_window: int = 30
    # PubMed peer-reviewed literature lookback
    pubmed_days_window: int = 90
    # X research buzz: hunt high-traction paper announcements on X
    x_research_buzz_enabled: bool = True
    x_research_min_likes: int = 20
    x_research_max_queries: int = 4
    # Drop X posts with no traction (0 likes/reposts, <=1 reply) when better
    # posts exist, so we stop citing dead tweets.
    drop_dead_x_posts: bool = True

    # --- LLM ---
    anthropic_api_key: str = ""
    # Haiku for cheap structured tasks (query expansion, parsing, clustering)
    anthropic_model_fast: str = "claude-haiku-4-5"
    # Sonnet for analysis and LinkedIn drafts (better quality, still reasonable cost)
    anthropic_model: str = "claude-sonnet-4-5"

    database_url: str = "sqlite:///./content_intelligence.db"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Topic scoring weights (must sum to 1.0).
    # Relevance dominates so off-topic noise can never win on raw volume.
    weight_relevance: float = 0.45
    weight_engagement: float = 0.30
    weight_freshness: float = 0.15
    weight_volume: float = 0.10

    # Minimum on-topic posts a theme needs to be surfaced as a topic.
    # 1 = surface more candidate topics to choose from when data is thin.
    min_relevant_posts_per_topic: int = 1

    # Always try to present at least this many topics if enough on-topic posts exist
    target_min_topics: int = 3

    # Max topics to analyze deeply
    max_topics_to_analyze: int = 5

    # Max characters for content objective (supports resume/skills context + goal)
    max_objective_length: int = 15000

    # Max search queries to generate
    max_search_queries: int = 10

    # --- Image generation (OpenAI GPT Image — on demand only, user-triggered) ---
    openai_api_key: str = ""
    openai_image_model: str = "gpt-image-1"
    openai_image_size: str = "1536x1024"  # landscape, close to LinkedIn 1200x627
    openai_image_quality: str = "medium"  # low | medium | high | auto
    linkedin_drafts_count: int = 5

    # --- Video generation (OpenAI Sora — image-to-video, on demand) ---
    # Uses the SAME OPENAI_API_KEY as image generation. Just make sure your OpenAI
    # account has Sora/video access enabled — no separate key needed.
    # Model: sora-2 (fast/cheaper) or sora-2-pro (higher quality).
    openai_video_model: str = "sora-2"
    # Output resolution. Must be one of Sora's allowed sizes:
    # 720x1280, 1280x720 (landscape 16:9), 1024x1792, 1792x1024.
    openai_video_size: str = "1280x720"
    # Target total length in seconds. A single Sora clip maxes at 12s, so longer
    # targets are produced with one native extend() (e.g. 20 = 12 + 8).
    openai_video_seconds: int = 20
    # Max seconds to wait for a Sora job before giving up.
    video_poll_timeout_seconds: int = 600
    video_poll_interval_seconds: int = 5

    # --- Voice-over (OpenAI TTS — Claude writes the script, aligned to the post) ---
    # Adds a spoken narration track to the video. Uses the same OPENAI_API_KEY.
    video_voiceover_default: bool = True
    openai_tts_model: str = "gpt-4o-mini-tts"  # supports tone `instructions`
    openai_tts_voice: str = "alloy"  # alloy|echo|fable|onyx|nova|shimmer|...
    openai_tts_format: str = "mp3"

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def enabled_source_list(self) -> List[str]:
        return [s.strip().lower() for s in self.enabled_sources.split(",") if s.strip()]

    @property
    def rss_feed_list(self) -> List[str]:
        return [u.strip() for u in self.rss_feeds.split(",") if u.strip()]

    @property
    def arxiv_category_list(self) -> List[str]:
        return [c.strip() for c in self.arxiv_categories.split(",") if c.strip()]

    @property
    def devto_tag_list(self) -> List[str]:
        return [t.strip() for t in self.devto_tags.split(",") if t.strip()]

    @property
    def preprint_server_list(self) -> List[str]:
        return [s.strip() for s in self.preprint_servers.split(",") if s.strip()]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
