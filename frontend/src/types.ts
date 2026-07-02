export interface EvidencePost {
  id: number;
  source: string;
  content_type: string | null;
  post_text: string;
  author_name: string;
  author_handle: string;
  post_url: string;
  posted_at: string | null;
  likes: number;
  retweets: number;
  replies: number;
  impressions: number | null;
}

export interface RunSettings {
  enabled_sources: string[];
  max_queries_per_source: number;
  posts_per_query: number;
  max_topics_to_analyze: number;
  max_search_queries: number;
  x_posts_per_query: number;
  x_research_min_likes: number;
  x_research_max_queries: number;
  draft_styles: string[];
}

export interface LinkedInDraft {
  label: string;
  style: string;
  text: string;
}

export interface Topic {
  id: number;
  name: string;
  query_used: string;
  score: number;
  relevance_score: number;
  volume_score: number;
  freshness_score: number;
  engagement_score: number;
  post_count: number;
  sources_summary: string | null;
  why_trending: string | null;
  specific_event: string | null;
  why_matters: string | null;
  linkedin_angle: string | null;
  linkedin_draft: string | null;
  linkedin_drafts: LinkedInDraft[];
  evidence_posts: EvidencePost[];
}

export interface SearchQuery {
  id: number;
  query_text: string;
  post_count: number | null;
  raw_post_count: number | null;
  count_checked_at: string | null;
}

export interface PrincipleDocument {
  id: number;
  filename: string;
  created_at: string;
  char_count: number;
}

export interface Principle {
  id: number;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
  documents: PrincipleDocument[];
}

export interface Objective {
  id: number;
  text: string;
  status: string;
  principle_id: number | null;
  sources_used: string | null;
  run_settings: RunSettings | null;
  created_at: string;
  updated_at: string;
  search_queries: SearchQuery[];
  topics: Topic[];
}

export interface HealthStatus {
  status: string;
  x_api_configured: boolean;
  anthropic_configured: boolean;
  openai_configured: boolean;
  image_generation_ready: boolean;
  reddit_configured: boolean;
  arxiv_configured: boolean;
  pubmed_configured: boolean;
  preprint_configured: boolean;
  devto_configured: boolean;
  x_research_configured: boolean;
  hackernews_configured: boolean;
  news_configured: boolean;
  industry_configured: boolean;
  active_sources: string[];
}
