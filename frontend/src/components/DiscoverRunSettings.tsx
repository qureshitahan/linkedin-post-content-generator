import type { RunSettings } from '../types';
import InfoTip from './InfoTip';
import { ToggleRow } from './ToggleSwitch';

export const SOURCE_OPTIONS: { id: string; label: string; paid?: boolean; help: string }[] = [
  {
    id: 'news',
    label: 'Google News',
    help: 'Headlines from Google News RSS. Free — best general “what’s trending” signal for almost any topic.',
  },
  {
    id: 'industry',
    label: 'Industry RSS',
    help: 'Trade publication feeds (healthcare, AI, marketing, data, etc.). Free — strong for professional niches.',
  },
  {
    id: 'hackernews',
    label: 'Hacker News',
    help: 'Tech community discussions via Hacker News search. Free — great for engineering, data, and startup discourse.',
  },
  {
    id: 'arxiv',
    label: 'arXiv papers',
    help: 'Recent AI/ML and quant-bio preprints on arXiv. Free — surfaces research before it hits mainstream news.',
  },
  {
    id: 'pubmed',
    label: 'PubMed',
    help: 'Peer-reviewed clinical and life-sciences literature. Free — use when your goal is healthcare or science.',
  },
  {
    id: 'preprint',
    label: 'bioRxiv / medRxiv',
    help: 'Early biology and medicine preprints. Free — catches emerging health research not yet in journals.',
  },
  {
    id: 'devto',
    label: 'Dev.to',
    help: 'Practitioner articles (ML, data, healthcare, DevOps tags). Free — how people in the field actually talk about topics.',
  },
  {
    id: 'x_research',
    label: 'X research buzz',
    paid: true,
    help: 'Finds high-traction posts on X announcing new papers. Uses paid X API — enable only when you want social buzz around research.',
  },
  {
    id: 'x',
    label: 'X / Twitter posts',
    paid: true,
    help: 'Recent tweets matching your search queries. Uses paid X API — niche professional topics often have weak X signal; other sources are usually better.',
  },
];

export const DRAFT_STYLE_OPTIONS: { id: string; label: string; desc: string }[] = [
  { id: 'provocative', label: 'Bold hook', desc: 'Sharp, scroll-stopping opener — contrarian or surprising.' },
  { id: 'analytical', label: 'Evidence-led', desc: 'Lead with a finding, stat, or concrete fact from the evidence.' },
  { id: 'story', label: 'Personal POV', desc: 'Practitioner voice — one real insight from experience.' },
  { id: 'curious', label: 'Question-led', desc: 'Open with a specific question your audience is debating.' },
  { id: 'actionable', label: 'Practical takeaway', desc: 'Focus on what to do differently — clear and useful.' },
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

function toggleList(list: string[], id: string, on: boolean): string[] {
  if (on) return list.includes(id) ? list : [...list, id];
  return list.filter((x) => x !== id);
}

function SettingLabel({ label, tip }: { label: string; tip: string }) {
  return (
    <span className="inline-flex items-center text-slate-600">
      {label}
      <InfoTip text={tip} />
    </span>
  );
}

export default function DiscoverRunSettings({ settings, onChange }: Props) {
  const xEnabled = settings.enabled_sources.some((s) => s === 'x' || s === 'x_research');
  const enabledSourceCount = settings.enabled_sources.length;

  return (
    <div className="mt-5 rounded-lg border border-slate-200 bg-slate-50 p-4">
      <h3 className="inline-flex items-center text-sm font-semibold text-slate-800">
        Discovery settings
        <InfoTip text="These controls apply only when you click Analyze — they decide where to look and how much to fetch. LinkedIn drafts and images are created later, only when you ask for them." />
      </h3>
      <p className="mt-1 text-xs text-slate-500">
        These settings only affect topic discovery. LinkedIn drafts and images are chosen and
        generated later on each topic card.
      </p>

      <div className="mt-4 space-y-5">
        <section>
          <div className="mb-2 flex items-center justify-between gap-2">
            <p className="inline-flex items-center text-xs font-medium uppercase tracking-wide text-slate-500">
              Sources
              <InfoTip text="Toggle which platforms to search. Only sources turned On will run. Paid ($) sources use the X API." />
            </p>
            <span className="text-xs text-slate-400">
              {enabledSourceCount} of {SOURCE_OPTIONS.length} on
            </span>
          </div>
          <div className="space-y-2">
            {SOURCE_OPTIONS.map((src) => {
              const selected = settings.enabled_sources.includes(src.id);
              return (
                <ToggleRow
                  key={src.id}
                  checked={selected}
                  onChange={(on) =>
                    onChange({
                      ...settings,
                      enabled_sources: toggleList(settings.enabled_sources, src.id, on),
                    })
                  }
                  label={src.label}
                  suffix={src.paid ? 'Paid' : undefined}
                  help={src.help}
                />
              );
            })}
          </div>
        </section>

        <section className="grid gap-4 sm:grid-cols-2">
          <label className="block text-sm">
            <SettingLabel
              label="Search queries to expand"
              tip="Claude turns your goal into this many search phrases (e.g. “marketing mix modeling 2025”). More queries = broader discovery but a longer, pricier run."
            />
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
            <SettingLabel
              label="Queries per source"
              tip="Each enabled source runs at most this many of those search phrases. Lower = fewer API calls and faster runs."
            />
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
            <SettingLabel
              label="Posts per query (free sources)"
              tip="How many posts or articles to fetch per search phrase on free sources (News, HN, arXiv, PubMed, etc.). Higher = more evidence to cluster but slower."
            />
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
            <SettingLabel
              label="Max topics to surface"
              tip="After filtering for relevance to your goal, how many topic clusters to rank, analyze deeply, and show you. The rest are dropped."
            />
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
            <p className="mb-2 inline-flex items-center text-xs font-semibold text-amber-900">
              X / Twitter (paid API)
              <InfoTip text="These settings only apply when X research buzz and/or X posts are enabled above. Each search uses your X API quota." />
            </p>
            <div className="grid gap-3 sm:grid-cols-3">
              <label className="block text-sm">
                <SettingLabel
                  label="X posts per query"
                  tip="Maximum tweets to pull per search phrase for X sources. Each fetch uses X API credits — keep low unless you need volume."
                />
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
                <SettingLabel
                  label="Research buzz min likes"
                  tip="For X research buzz only: ignore paper-announcement posts below this like count. Filters dead tweets so you only see posts that actually got traction."
                />
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
                <SettingLabel
                  label="Research buzz queries"
                  tip="How many of your expanded search phrases to send to X research buzz (separate from general X post search). Fewer = cheaper."
                />
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

      </div>
    </div>
  );
}
