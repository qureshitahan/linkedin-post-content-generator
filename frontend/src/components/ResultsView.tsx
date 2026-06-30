import type { Objective } from '../types';
import { DEFAULT_RUN_SETTINGS } from './DiscoverRunSettings';
import SearchQueriesPanel from './SearchQueriesPanel';
import TopicCard from './TopicCard';

interface Props {
  objective: Objective;
  imageGenerationReady?: boolean;
}

const STATUS_LABELS: Record<string, string> = {
  pending: 'Ready to analyze',
  expanding_queries: 'Expanding search queries...',
  checking_counts: 'Checking post counts...',
  fetching_posts: 'Gathering news, research papers, X buzz & community posts...',
  selecting_topics: 'Filtering to on-topic posts & clustering themes...',
  analyzing_trends: 'Analyzing themes & generating content...',
  completed: 'Analysis complete',
  failed: 'Analysis failed',
};

const SOURCE_NAMES: Record<string, string> = {
  news: 'News',
  industry: 'Industry',
  reddit: 'Reddit',
  arxiv: 'arXiv',
  pubmed: 'PubMed',
  preprint: 'Preprint',
  devto: 'Dev.to',
  x_research: 'X Research Buzz',
  hackernews: 'Hacker News',
  x: 'X',
};

export default function ResultsView({ objective, imageGenerationReady = false }: Props) {
  const sortedTopics = [...objective.topics].sort((a, b) => b.score - a.score);
  const sources = (objective.sources_used || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => SOURCE_NAMES[s] || s);

  const draftStyles =
    objective.run_settings?.draft_styles ?? DEFAULT_RUN_SETTINGS.draft_styles;

  return (
    <div className="space-y-6">
      <div className="card bg-gradient-to-r from-brand-50 to-white">
        <p className="text-sm text-slate-500">Your objective</p>
        <p className="mt-1 text-lg font-medium text-slate-900">{objective.text}</p>
        <p className="mt-2 text-xs text-slate-400">
          Status: {STATUS_LABELS[objective.status] || objective.status}
          {sources.length > 0 && <> · Sources: {sources.join(', ')}</>}
        </p>
      </div>

      <SearchQueriesPanel queries={objective.search_queries} status={objective.status} />

      {sortedTopics.length > 0 && (
        <div>
          <h2 className="mb-4 text-lg font-semibold text-slate-900">
            Trending Topics ({sortedTopics.length})
          </h2>
          <p className="mb-6 text-sm text-slate-500">
            Relevance-first ranking. Evidence is shown first. Drafts and images are generated only when
            you request them on a topic you care about.
          </p>
          <div className="space-y-6">
            {sortedTopics.map((topic, i) => (
              <TopicCard
                key={topic.id}
                topic={topic}
                rank={i + 1}
                objectiveId={objective.id}
                imageGenerationReady={imageGenerationReady}
                defaultDraftStyles={draftStyles}
              />
            ))}
          </div>
        </div>
      )}

      {objective.status === 'completed' && sortedTopics.length === 0 && (
        <div className="card text-center text-slate-500">
          <p className="font-medium text-slate-700">No on-topic conversations found this week.</p>
          <p className="mt-2 text-sm">
            We searched {sources.length > 0 ? sources.join(', ') : 'the configured sources'} and didn't find
            enough relevant, recent discussion to build a grounded post. This is honest signal — not every
            niche trends every week. Try broadening the goal, adding Reddit credentials for better niche
            coverage, or running again in a few days.
          </p>
        </div>
      )}
    </div>
  );
}
