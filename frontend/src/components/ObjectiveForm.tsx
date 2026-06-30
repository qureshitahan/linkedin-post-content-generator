import { MAX_OBJECTIVE_LENGTH } from '../api/client';
import type { RunSettings } from '../types';
import DiscoverRunSettings from './DiscoverRunSettings';

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  loading: boolean;
  runSettings: RunSettings;
  onRunSettingsChange: (settings: RunSettings) => void;
}

const EXAMPLES = [
  'I want LinkedIn posts on what’s trending in my field — here’s my background: [paste resume]. Goal: posts that show expertise in media measurement and AI reporting automation.',
  'Goal: LinkedIn posts about climate tech fundraising and what founders are debating on X this week.',
  'Goal: posts on AI agents in enterprise workflow automation. Background: product manager at a B2B SaaS company.',
];

export default function ObjectiveForm({
  value,
  onChange,
  onSubmit,
  loading,
  runSettings,
  onRunSettingsChange,
}: Props) {
  const length = value.length;
  const tooLong = length > MAX_OBJECTIVE_LENGTH;
  const tooShort = value.trim().length < 10;

  return (
    <div className="card">
      <h2 className="mb-1 text-lg font-semibold text-slate-900">Content Objective</h2>
      <p className="mb-4 text-sm text-slate-500">
        Optional: paste background (resume, skills). Then state your goal — what kind of LinkedIn posts you
        want and what’s trending in that space. Works for any field. Up to{' '}
        {MAX_OBJECTIVE_LENGTH.toLocaleString()} characters.
      </p>

      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Optional background above, then your goal — e.g. 'Goal: LinkedIn posts about what's trending in [your topic] and how it connects to my work.'"
        rows={8}
        maxLength={MAX_OBJECTIVE_LENGTH}
        className={`w-full rounded-lg border px-4 py-3 text-sm focus:outline-none focus:ring-2 ${
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
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            onClick={() => onChange(example)}
            className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600 transition hover:bg-slate-200"
          >
            {example.slice(0, 50)}...
          </button>
        ))}
      </div>

      <DiscoverRunSettings settings={runSettings} onChange={onRunSettingsChange} />

      <div className="mt-5 flex justify-end">
        <button
          onClick={onSubmit}
          disabled={loading || tooShort || tooLong || runSettings.draft_styles.length === 0}
          className="btn-primary"
        >
          {loading ? 'Discovering topics…' : 'Discover Trending Topics'}
        </button>
      </div>
    </div>
  );
}
