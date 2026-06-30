# Architecture — Phase 1 MVP

## System Overview

The LinkedIn Content Intelligence Engine is a three-tier application designed to transform a high-level content objective into specific, evidence-backed LinkedIn post ideas sourced from X/Twitter conversations.

### Design Principles

1. **Specificity over breadth** — Never stop at "AI is trending." Always drill into the specific debate, product, or event.
2. **Evidence before generation** — Users see X posts and trend reasoning before any LinkedIn draft.
3. **Secure API boundary** — Frontend talks only to our backend; backend holds all third-party credentials.
4. **Cost-aware X usage** — Post counts are checked first to avoid expensive full searches on low-volume queries.

---

## Component Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND (React)                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ ObjectiveForm│  │ SearchQueries│  │ TopicCard            │  │
│  │              │  │ Panel        │  │  ├─ EvidencePosts    │  │
│  │              │  │              │  │  ├─ Trend Analysis   │  │
│  │              │  │              │  │  └─ LinkedIn Draft   │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│                          api/client.ts                          │
└─────────────────────────────┬───────────────────────────────────┘
                              │ REST /api/*
┌─────────────────────────────▼───────────────────────────────────┐
│                      BACKEND (FastAPI)                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                   AnalysisPipeline                       │   │
│  │  1. QueryExpansionService  → OpenAI                     │   │
│  │  2. XAPIService.get_recent_post_count  → X API          │   │
│  │  3. TopicScoring.rank + score                          │   │
│  │  4. XAPIService.search_recent_posts  → X API           │   │
│  │  5. TrendAnalysisService  → OpenAI                     │   │
│  │  6. Persist to SQLite                                   │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────┬───────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         ┌─────────┐    ┌──────────┐    ┌─────────┐
         │ X API   │    │ OpenAI   │    │ SQLite  │
         │ v2 + v1 │    │ GPT-4o   │    │         │
         └─────────┘    └──────────┘    └─────────┘
```

---

## X API Integration

### 1. Recent Post Counts (Primary Filter)

- **Endpoint:** `GET /2/tweets/counts/recent`
- **When:** After query expansion, before full search
- **Purpose:** Measure 7-day tweet volume per query
- **Cost:** Low — avoids pulling full tweet payloads for dead queries

### 2. Recent Search (Evidence Layer)

- **Endpoint:** `GET /2/tweets/search/recent`
- **When:** Only for top-scoring queries after count filter
- **Purpose:** Pull actual posts with text, author, metrics
- **Filters:** `-is:retweet lang:en`, last 7 days
- **Fields:** `tweet.fields=created_at,public_metrics`, `expansions=author_id`

### 3. Trends by Location (Optional Signal)

- **Endpoint:** `GET /1.1/trends/place.json`
- **When:** At pipeline start, passed as hints to query expansion
- **Purpose:** Broad discovery signal only — NOT the main intelligence layer
- **Default WOEID:** 23424977 (United States)

---

## Topic Scoring Algorithm

```python
volume_score   = normalize(post_count, min_counts, max_counts)     # 0-1
freshness_score = avg(recency_weight per post)                       # 0-1
engagement_score = log_scale(avg(likes + 3*RT + 2*replies))         # 0-1

topic_score = 0.35 * volume + 0.25 * freshness + 0.40 * engagement
```

### Freshness Weights

| Post Age | Score |
|----------|-------|
| ≤ 24 hours | 1.0 |
| ≤ 72 hours | 0.7 |
| ≤ 7 days | 0.4 |
| > 7 days | 0.1 |

### Selection Logic

1. Run counts for all expanded queries
2. Filter queries with `post_count >= threshold` (default 50)
3. If none qualify, take top 3 by count anyway
4. Deep-analyze top N topics (default 5)
5. Rank final topics by combined score

---

## LLM Prompt Strategy

### Query Expansion

Input: User objective + optional trend hints  
Output: 10 specific 2-6 word X search queries  
Constraint: No generic single-word queries

### Trend Analysis

Input: Topic name, search query, up to 8 evidence posts, user objective  
Output: JSON with `why_trending`, `specific_event`, `why_matters`, `linkedin_angle`, `linkedin_draft`  
Constraint: Analysis must be grounded in provided posts; no fabricated events

---

## Frontend Screens

### Screen 1: Home / Objective Entry
- Text area for content objective
- Example objective chips
- API status badges (X, OpenAI)
- "Discover Trending Topics" CTA

### Screen 2: Analysis Progress
- Loading state with pipeline step description
- Spinner during async analysis

### Screen 3: Results
- **Objective summary** — What was analyzed
- **Search queries table** — Query + 7-day post count
- **Topic cards** (ranked) — Each containing:
  1. Topic name + score breakdown (volume/freshness/engagement bars)
  2. Why it is trending
  3. Specific event or debate
  4. **Evidence posts** (text, author, link, date, metrics)
  5. Why it matters
  6. LinkedIn angle
  7. LinkedIn draft (hidden behind "Show draft" — evidence first)

### Sidebar: Recent Objectives
- History of past analyses
- Click to reload previous results

---

## Security Model

| Layer | Responsibility |
|-------|---------------|
| Frontend | No API keys; calls `/api/*` only |
| Backend | Holds `X_BEARER_TOKEN`, `OPENAI_API_KEY` in `.env` |
| CORS | Restricted to configured origins |
| Database | Local SQLite; no PII beyond public X post data |

---

## Future Phases (Out of Scope)

- **Phase 2:** Reddit + news sources
- **Phase 3:** Research paper integration
- **Phase 4:** LinkedIn scheduling/auto-post
- **Phase 5:** Every-other-day automated runs with email digest
