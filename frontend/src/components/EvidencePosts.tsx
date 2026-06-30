import type { EvidencePost } from '../types';

interface Props {
  posts: EvidencePost[];
}

const SOURCE_META: Record<string, { label: string; link: string; cls: string }> = {
  news: { label: 'News', link: 'Read article →', cls: 'bg-emerald-100 text-emerald-700' },
  industry: { label: 'Industry', link: 'Read article →', cls: 'bg-teal-100 text-teal-700' },
  reddit: { label: 'Reddit', link: 'View on Reddit →', cls: 'bg-orange-100 text-orange-700' },
  arxiv: { label: 'arXiv', link: 'Read paper →', cls: 'bg-indigo-100 text-indigo-700' },
  pubmed: { label: 'PubMed', link: 'Read paper →', cls: 'bg-indigo-100 text-indigo-800' },
  preprint: { label: 'Preprint', link: 'Read preprint →', cls: 'bg-violet-100 text-violet-800' },
  x_research: { label: 'X Research Buzz', link: 'View on X →', cls: 'bg-purple-100 text-purple-800' },
  devto: { label: 'Dev.to', link: 'Read article →', cls: 'bg-sky-100 text-sky-700' },
  hackernews: { label: 'Hacker News', link: 'View on HN →', cls: 'bg-amber-100 text-amber-800' },
  x: { label: 'X', link: 'View on X →', cls: 'bg-slate-200 text-slate-700' },
};

const CONTENT_TYPE_LABELS: Record<string, { label: string; cls: string }> = {
  research_paper: { label: 'Research paper', cls: 'bg-indigo-50 text-indigo-800 border-indigo-200' },
  research_buzz: { label: 'Research buzz on X', cls: 'bg-purple-50 text-purple-800 border-purple-200' },
};

function sourceMeta(source: string) {
  return SOURCE_META[source] || { label: source, link: 'View source →', cls: 'bg-slate-200 text-slate-700' };
}

function formatDate(dateStr: string | null) {
  if (!dateStr) return 'Unknown date';
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

export default function EvidencePosts({ posts }: Props) {
  if (posts.length === 0) {
    return (
      <p className="text-sm italic text-slate-400">No evidence posts available for this topic.</p>
    );
  }

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Evidence</h4>
      {posts.map((post) => {
        const meta = sourceMeta(post.source);
        const typeMeta = post.content_type ? CONTENT_TYPE_LABELS[post.content_type] : null;
        const isReddit = post.source === 'reddit';
        const isHN = post.source === 'hackernews';
        const isResearchPaper = post.content_type === 'research_paper';
        const isResearchBuzz = post.content_type === 'research_buzz';
        const isCuratedArticle =
          post.source === 'news' || post.source === 'industry' || post.source === 'devto';
        const hideEngagement = isResearchPaper || isCuratedArticle;

        return (
          <div key={post.id} className="rounded-lg border border-slate-200 bg-slate-50 p-4">
            <div className="mb-2 flex items-start justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`badge ${meta.cls}`}>{meta.label}</span>
                {typeMeta && (
                  <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${typeMeta.cls}`}>
                    {typeMeta.label}
                  </span>
                )}
                <span className="font-semibold text-slate-800">{post.author_name}</span>
                {post.author_handle && !hideEngagement && !isCuratedArticle && (
                  <span className="text-slate-500">
                    {isReddit ? post.author_handle : `@${post.author_handle}`}
                  </span>
                )}
              </div>
              <span className="shrink-0 text-xs text-slate-400">{formatDate(post.posted_at)}</span>
            </div>
            <p className="mb-3 whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
              {post.post_text}
            </p>
            <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500">
              {hideEngagement ? (
                <span className="font-medium text-emerald-700">
                  {isResearchPaper
                    ? 'Peer-reviewed / preprint research'
                    : post.source === 'devto'
                      ? 'Practitioner article'
                      : 'Curated news article'}
                </span>
              ) : (
                <>
                  <span>
                    {post.likes.toLocaleString()} {isReddit || isHN ? 'upvotes' : 'likes'}
                  </span>
                  {!isReddit && !isHN && (
                    <span>{post.retweets.toLocaleString()} reposts</span>
                  )}
                  <span>{post.replies.toLocaleString()} comments</span>
                  {isResearchBuzz && post.likes >= 20 && (
                    <span className="font-medium text-purple-700">High traction</span>
                  )}
                  {post.impressions != null && (
                    <span>{post.impressions.toLocaleString()} impressions</span>
                  )}
                </>
              )}
              {post.post_url && (
                <a
                  href={post.post_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ml-auto font-medium text-brand-600 hover:underline"
                >
                  {meta.link}
                </a>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
