import { MAX_OBJECTIVE_LENGTH } from '../api/client';
import type { Principle, RunSettings } from '../types';
import DiscoverRunSettings from './DiscoverRunSettings';

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  loading: boolean;
  runSettings: RunSettings;
  onRunSettingsChange: (settings: RunSettings) => void;
  principles: Principle[];
  selectedPrincipleId: number | null;
  onPrincipleChange: (id: number | null) => void;
}

const GOAL_EXAMPLES = [
  'Goal: LinkedIn posts about AI in healthcare — what’s trending and worth commenting on.',
  'Goal: posts on enterprise data engineering trends and what practitioners are debating.',
  'Goal: LinkedIn posts about climate tech fundraising and founder lessons this week.',
];

const BACKGROUND_EXAMPLES = [
  'I want LinkedIn posts on what’s trending in my field — here’s my background: [paste resume]. Goal: posts that show expertise in media measurement.',
  'Goal: posts on AI agents in enterprise workflow automation. Background: product manager at a B2B SaaS company.',
];

function totalIndexedChars(principle: Principle): number {
  return principle.documents.reduce((sum, d) => sum + (d.char_count || 0), 0);
}

export default function ObjectiveForm({
  value,
  onChange,
  onSubmit,
  loading,
  runSettings,
  onRunSettingsChange,
  principles,
  selectedPrincipleId,
  onPrincipleChange,
}: Props) {
  const length = value.length;
  const tooLong = length > MAX_OBJECTIVE_LENGTH;
  const tooShort = value.trim().length < 10;
  const selectedPrinciple = principles.find((p) => p.id === selectedPrincipleId) ?? null;
  const examples = selectedPrinciple ? GOAL_EXAMPLES : BACKGROUND_EXAMPLES;

  return (
    <div className="card">
      <h2 className="mb-1 text-lg font-semibold text-slate-900">Content Objective</h2>
      <p className="mb-5 text-sm text-slate-500">
        Choose who you&apos;re writing as, set your goal, then discover trending topics.
      </p>

      {/* Principle selection */}
      <section className="mb-5 rounded-xl border border-slate-200 bg-slate-50/60 p-4">
        <label htmlFor="principle-select" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">
          Principle — who is this post for?
        </label>
        <select
          id="principle-select"
          value={selectedPrincipleId ?? ''}
          onChange={(e) => onPrincipleChange(e.target.value ? Number(e.target.value) : null)}
          className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm font-medium text-slate-800 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
        >
          <option value="">None — I&apos;ll paste my background in the goal below</option>
          {principles.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
              {p.documents.length > 0
                ? ` (${p.documents.length} file${p.documents.length === 1 ? '' : 's'} indexed)`
                : ' (no files yet)'}
            </option>
          ))}
        </select>

        {selectedPrinciple ? (
          <div className="mt-3 rounded-lg border border-brand-200 bg-brand-50 px-3 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center rounded-full bg-brand-600 px-2.5 py-0.5 text-xs font-medium text-white">
                Active principle
              </span>
              <span className="text-sm font-semibold text-slate-900">{selectedPrinciple.name}</span>
            </div>
            <p className="mt-2 text-xs text-slate-600">
              {selectedPrinciple.documents.length === 0 ? (
                <>
                  <span className="font-medium text-amber-700">No files indexed yet.</span> Add
                  resume, achievements, or screenshots in the Principles panel on the right.
                </>
              ) : (
                <>
                  <span className="font-medium text-slate-800">
                    {selectedPrinciple.documents.length} file
                    {selectedPrinciple.documents.length === 1 ? '' : 's'} indexed
                  </span>
                  {' · '}
                  {totalIndexedChars(selectedPrinciple).toLocaleString()} characters searchable
                  {' · '}
                  parsed from resumes, Word docs, PDFs, and images
                </>
              )}
            </p>
          </div>
        ) : (
          <p className="mt-2 text-xs text-slate-500">
            No principle selected. Paste your background directly in the goal field, or create one
            in the Principles panel and upload your files.
          </p>
        )}

        <details className="mt-3 group">
          <summary className="cursor-pointer text-xs font-medium text-brand-700 hover:text-brand-800">
            How does the principle get used?
          </summary>
          <ol className="mt-2 space-y-2 border-t border-slate-200/80 pt-3 text-xs leading-relaxed text-slate-600">
            <li>
              <span className="font-medium text-slate-800">1. Index</span> — Your uploaded files
              are parsed into text and split into searchable snippets (skills, companies, projects,
              achievements).
            </li>
            <li>
              <span className="font-medium text-slate-800">2. Goal</span> — You write what you want
              to post about below (e.g. &quot;AI in healthcare&quot;). No need to repeat your resume.
            </li>
            <li>
              <span className="font-medium text-slate-800">3. Discover</span> — The system reads
              your goal, pulls the most relevant experience from your indexed files, and uses both
              to search news, research, and social sources for on-topic trends.
            </li>
            <li>
              <span className="font-medium text-slate-800">4. Draft</span> — When you generate a
              LinkedIn draft, it links the trending topic to your real background when it fits
              naturally (e.g. a post about hallucinations → your RAG project), without inventing
              experience.
            </li>
          </ol>
        </details>
      </section>

      {/* Goal input */}
      <label htmlFor="objective-goal" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">
        Your goal
      </label>
      <p className="mb-2 text-sm text-slate-500">
        {selectedPrinciple
          ? `What do you want to post about? ${selectedPrinciple.name}'s background comes from your indexed files.`
          : `State your goal and optional background. Up to ${MAX_OBJECTIVE_LENGTH.toLocaleString()} characters.`}
      </p>

      <textarea
        id="objective-goal"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={
          selectedPrinciple
            ? "Goal: I want LinkedIn posts about what's trending in AI and healthcare..."
            : "Optional background, then your goal — e.g. 'Goal: LinkedIn posts about what's trending in [your topic].'"
        }
        rows={4}
        maxLength={MAX_OBJECTIVE_LENGTH}
        className={`max-h-40 w-full resize-y overflow-y-auto rounded-lg border px-4 py-3 text-sm focus:outline-none focus:ring-2 ${
          tooLong
            ? 'border-red-300 focus:border-red-500 focus:ring-red-500/20'
            : 'border-slate-300 focus:border-brand-500 focus:ring-brand-500/20'
        }`}
      />

      <div className="mt-2 flex items-center justify-between text-xs">
        <span className={tooLong ? 'text-red-600' : 'text-slate-400'}>
          {length.toLocaleString()} / {MAX_OBJECTIVE_LENGTH} characters
          {tooLong && ' — too long, please shorten'}
        </span>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {examples.map((example) => (
          <button
            key={example}
            type="button"
            onClick={() => onChange(example)}
            className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600 transition hover:bg-slate-200"
          >
            {example.slice(0, 52)}...
          </button>
        ))}
      </div>

      <DiscoverRunSettings settings={runSettings} onChange={onRunSettingsChange} />

      <div className="mt-5 flex justify-end">
        <button
          onClick={onSubmit}
          disabled={loading || tooShort || tooLong}
          className="btn-primary"
        >
          {loading ? 'Discovering topics…' : 'Discover Trending Topics'}
        </button>
      </div>
    </div>
  );
}
