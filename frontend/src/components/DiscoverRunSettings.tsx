import type { RunSettings } from '../types';

export const SOURCE_OPTIONS: { id: string; label: string; paid?: boolean }[] = [
  { id: 'news', label: 'Google News' },
  { id: 'industry', label: 'Industry RSS' },
  { id: 'hackernews', label: 'Hacker News' },
  { id: 'arxiv', label: 'arXiv papers' },
  { id: 'pubmed', label: 'PubMed' },
  { id: 'preprint', label: 'bioRxiv / medRxiv' },
  { id: 'devto', label: 'Dev.to' },
  { id: 'x_research', label: 'X research buzz', paid: true },
  { id: 'x', label: 'X / Twitter posts', paid: true },
];

export const DRAFT_STYLE_OPTIONS: { id: string; label: string; desc: string }[] = [
  { id: 'provocative', label: 'Bold hook', desc: 'Sharp, scroll-stopping opener' },
  { id: 'analytical', label: 'Evidence-led', desc: 'Lead with a finding or stat' },
  { id: 'story', label: 'Personal POV', desc: 'Practitioner voice & experience' },
  { id: 'curious', label: 'Question-led', desc: 'Open with a debate question' },
  { id: 'actionable', label: 'Practical takeaway', desc: 'What to do differently' },
];

export const DEFAULT_RUN_SETTINGS: RunSettings = {
  enabled_sources: ['news', 'industry', 'hackernews', 'arxiv', 'pubmed', 'preprint', 'devto'],
  max_queries_per_source: 5,
  posts_per_query: 15,
  max_topics_to_analyze: 3,
  max_search_queries: 6,
  x_posts_per_query: 10,
  x_research_min_likes: 30,
  x_research_max_queries: 2,
  draft_styles: DRAFT_STYLE_OPTIONS.map((s) => s.id),
};

interface Props {
  settings: RunSettings;
  onChange: (settings: RunSettings) => void;
}

function toggleList(list: string[], id: string): string[] {
  return list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
}

export default function DiscoverRunSettings({ settings, onChange }: Props) {
  const xEnabled = settings.enabled_sources.some((s) => s === 'x' || s === 'x_research');

  return (
    <div className="mt-5 rounded-lg border border-slate-200 bg-slate-50 p-4">
      <h3 className="text-sm font-semibold text-slate-800">Discovery settings</h3>
      <p className="mt-1 text-xs text-slate-500">
        Control cost before you run. Drafts and images are generated later, only when you ask.
      </p>

      <div className="mt-4 space-y-5">
        <section>
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">Sources</p>
          <div className="flex flex-wrap gap-2">
            {SOURCE_OPTIONS.map((src) => (
              <label
                key={src.id}
                className={`cursor-pointer rounded-full px-3 py-1 text-xs font-medium ${
                  settings.enabled_sources.includes(src.id)
                    ? 'bg-brand-600 text-white'
                    : 'bg-white text-slate-600 ring-1 ring-slate-200'
                }`}
              >
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={settings.enabled_sources.includes(src.id)}
                  onChange={() =>
                    onChange({
                      ...settings,
                      enabled_sources: toggleList(settings.enabled_sources, src.id),
                    })
                  }
                />
                {src.label}
                {src.paid && ' ($)'}
              </label>
            ))}
          </div>
        </section>

        <section className="grid gap-4 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="text-slate-600">Search queries to expand</span>
            <input
              type="number"
              min={3}
              max={12}
              value={settings.max_search_queries}
              onChange={(e) =>
                onChange({ ...settings, max_search_queries: Number(e.target.value) })
              }
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
            />
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">Queries per source</span>
            <input
              type="number"
              min={1}
              max={15}
              value={settings.max_queries_per_source}
              onChange={(e) =>
                onChange({ ...settings, max_queries_per_source: Number(e.target.value) })
              }
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
            />
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">Posts per query (free sources)</span>
            <input
              type="number"
              min={5}
              max={50}
              value={settings.posts_per_query}
              onChange={(e) =>
                onChange({ ...settings, posts_per_query: Number(e.target.value) })
              }
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
            />
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">Max topics to surface</span>
            <input
              type="number"
              min={1}
              max={8}
              value={settings.max_topics_to_analyze}
              onChange={(e) =>
                onChange({ ...settings, max_topics_to_analyze: Number(e.target.value) })
              }
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
            />
          </label>
        </section>

        {xEnabled && (
          <section className="rounded border border-amber-200 bg-amber-50/80 p-3">
            <p className="mb-2 text-xs font-semibold text-amber-900">X / Twitter (paid API)</p>
            <div className="grid gap-3 sm:grid-cols-3">
              <label className="block text-sm">
                <span className="text-slate-600">X posts per query</span>
                <input
                  type="number"
                  min={0}
                  max={30}
                  value={settings.x_posts_per_query}
                  onChange={(e) =>
                    onChange({ ...settings, x_posts_per_query: Number(e.target.value) })
                  }
                  className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
                />
              </label>
              <label className="block text-sm">
                <span className="text-slate-600">Research buzz min likes</span>
                <input
                  type="number"
                  min={0}
                  max={500}
                  value={settings.x_research_min_likes}
                  onChange={(e) =>
                    onChange({ ...settings, x_research_min_likes: Number(e.target.value) })
                  }
                  className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
                />
              </label>
              <label className="block text-sm">
                <span className="text-slate-600">Research buzz queries</span>
                <input
                  type="number"
                  min={0}
                  max={8}
                  value={settings.x_research_max_queries}
                  onChange={(e) =>
                    onChange({ ...settings, x_research_max_queries: Number(e.target.value) })
                  }
                  className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
                />
              </label>
            </div>
          </section>
        )}

        <section>
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">
            Draft styles (generated later, per topic you choose)
          </p>
          <p className="mb-2 text-xs text-slate-400">
            Pick which post styles to offer when you click &quot;Write drafts&quot; on a topic.
          </p>
          <div className="flex flex-wrap gap-2">
            {DRAFT_STYLE_OPTIONS.map((style) => (
              <label
                key={style.id}
                title={style.desc}
                className={`cursor-pointer rounded-full px-3 py-1 text-xs font-medium ${
                  settings.draft_styles.includes(style.id)
                    ? 'bg-slate-800 text-white'
                    : 'bg-white text-slate-600 ring-1 ring-slate-200'
                }`}
              >
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={settings.draft_styles.includes(style.id)}
                  onChange={() =>
                    onChange({
                      ...settings,
                      draft_styles: toggleList(settings.draft_styles, style.id),
                    })
                  }
                />
                {style.label}
              </label>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
