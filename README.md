# LinkedIn Content Intelligence Engine

Discover **specific, on-topic** trending conversations across **Reddit, Hacker News, and X**, understand **why** they matter with evidence, and generate human-like LinkedIn post drafts.

> **Why multi-source + relevance-first?** Niche professional discourse (marketing measurement, analytics, ad tech, data engineering, etc.) barely trends on X — that corpus skews to crypto/politics/consumer. The engine now gathers from multiple platforms and **filters every post for relevance to your goal _before_ choosing topics**, so high-volume off-topic noise (e.g. "data validation" surfacing blockchain) can never win.

## Quick Start

### 1. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your X_BEARER_TOKEN and OPENAI_API_KEY
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

## API Keys & Sources

| Key | Source | Required? | Get it from |
|-----|--------|-----------|-------------|
| _none_ | **News** (Google News RSS) | Works out of the box | free, no auth — best "trending" signal |
| `RSS_FEEDS` (has defaults) | **Industry** (trade-pub RSS) | Works out of the box | free, no auth — AdExchanger, Digiday, MarTech, Marketing Dive, Adweek |
| _none_ | **Hacker News** (Algolia) | Works out of the box | free, no auth |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | **Reddit** | Recommended (best niche coverage) | [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) → "script" app (free tier) |
| `X_BEARER_TOKEN` (+ `X_API_KEY`/`SECRET`) | **X** | Optional, demoted | [X Developer Portal](https://developer.x.com/) (pay-per-use in 2026) |
| `ANTHROPIC_API_KEY` | Claude (LLM) | Required | [Anthropic Console](https://console.anthropic.com/) |

Control which sources run with `ENABLED_SOURCES` (default `news,reddit,hackernews,x`). A source only runs if it's enabled **and** configured; missing credentials are skipped gracefully. X recent-search is sorted by relevancy and dead/no-traction tweets are filtered out so you don't cite 2-impression posts.

## User Flow

```
Resume / background + content goal
    ↓
Parse goal + relevance keywords + relevant subreddits (LLM)
    ↓
Expand into specific search queries (LLM)
    ↓
Gather posts in parallel from News + Reddit + Hacker News + X
    ↓
RELEVANCE GATE: keep only posts that match the goal, drop noise
    ↓
Cluster on-topic posts into specific themes (LLM)
    ↓
Score themes — relevance-first
    ↓
Analyze: why it matters, specific debate, evidence FIRST
    ↓
LinkedIn angle + human-like draft (grounded in real posts)
```

## Architecture

```
┌─────────────┐    HTTP    ┌──────────────────┐   HTTPS   ┌──────────────┐
│   React     │ ─────────→ │  FastAPI Backend │ ────────→ │ Reddit API   │
│  Frontend   │            │  (our API only)  │ ────────→ │ Hacker News  │
└─────────────┘            │                  │ ────────→ │ X API (opt)  │
                           │                  │ ────────→ │ Anthropic    │
                           │      SQLite      │           └──────────────┘
                           └──────────────────┘
```

The frontend **never** calls any source directly. All credentials live in backend environment variables.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check + config status |
| POST | `/api/objectives` | Create content objective |
| GET | `/api/objectives` | List past objectives |
| GET | `/api/objectives/{id}` | Get objective with full results |
| POST | `/api/objectives/{id}/analyze` | Run full intelligence pipeline |
| POST | `/api/objectives/{id}/topics/{topic_id}/regenerate-draft` | Regenerate a fresh draft variation for one topic |
| GET | `/api/objectives/trends/location` | Optional broad X trends signal |

## Topic Scoring (relevance-first)

Each theme gets a combined score from four signals. Relevance dominates so off-topic noise can't win on volume:

| Signal | Weight | Source |
|--------|--------|--------|
| **Relevance** | 45% | How strongly the theme's posts match your goal (focus domains + keywords, minus avoid-topics) |
| **Engagement** | 30% | Upvotes/likes + comments across the theme's posts (log-scaled) |
| **Freshness** | 15% | Age of posts (24h = highest, decays over 7 days) |
| **On-topic volume** | 10% | Count of *relevant* posts in the theme (not raw keyword volume) |

If no source returns enough on-topic, recent discussion, the engine says so honestly instead of fabricating a topic.

## Database Schema

```
objectives
├── id, text, status, created_at, updated_at

search_queries
├── id, objective_id, query_text, post_count, count_checked_at

topics
├── id, objective_id, name, query_used
├── score, relevance_score, volume_score, freshness_score, engagement_score
├── post_count, sources_summary
├── why_trending, specific_event, why_matters
├── linkedin_angle, linkedin_draft

evidence_posts
├── id, topic_id, source, post_text, author_name, author_handle, post_url
├── posted_at, likes, retweets, replies, impressions
```

## Scope

**Included:**
- Multi-source gathering: Reddit, Hacker News, X (pluggable)
- Relevance-first filtering (off-topic noise dropped before topic selection)
- LLM theme clustering across all sources
- Resume/goal parsing + relevant-subreddit suggestion
- Evidence-first output with per-post source labels
- LinkedIn angle + draft generation

**Not included (future):**
- News / research-paper / LinkedIn-native sources
- LinkedIn auto-posting
- Scheduled recurring runs
- Multi-user auth

## Adding a new source

Implement the `Source` protocol (`search(query, max_results) -> list[NormalizedPost]`) in `backend/app/services/sources/`, register it in `aggregator.py`, and add it to `ENABLED_SOURCES`. The rest of the pipeline is source-agnostic.

## Project Structure

```
Trending_Posts_Content_Generation/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry point
│   │   ├── config.py            # Settings & scoring weights
│   │   ├── models.py            # SQLAlchemy models
│   │   ├── schemas.py           # Pydantic API schemas
│   │   ├── services/
│   │   │   ├── sources/         # Pluggable content sources
│   │   │   │   ├── base.py          # NormalizedPost + Source protocol
│   │   │   │   ├── news_source.py   # Google News RSS (free)
│   │   │   │   ├── rss_source.py    # Industry trade-pub RSS (free)
│   │   │   │   ├── reddit_source.py
│   │   │   │   ├── hackernews_source.py
│   │   │   │   ├── x_source.py
│   │   │   │   └── aggregator.py    # Runs all sources, dedupes
│   │   │   ├── x_api.py         # X API client (secure)
│   │   │   ├── objective_parser.py  # Resume/goal → writer context
│   │   │   ├── query_expansion.py
│   │   │   ├── topic_clustering.py  # On-topic posts → themes
│   │   │   ├── topic_scoring.py     # Relevance-first scoring
│   │   │   ├── trend_analysis.py
│   │   │   └── pipeline.py      # Full workflow orchestration
│   │   └── routers/
│   │       ├── health.py
│   │       └── objectives.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── src/
│       ├── App.tsx
│       ├── components/          # UI components
│       └── api/client.ts        # Backend API client only
└── docs/
    └── ARCHITECTURE.md
```

## License

Private — internal use.
