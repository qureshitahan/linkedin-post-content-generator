import { useCallback, useEffect, useRef, useState } from 'react';
import { api, MAX_OBJECTIVE_LENGTH } from './api/client';
import ObjectiveForm from './components/ObjectiveForm';
import { DEFAULT_RUN_SETTINGS } from './components/DiscoverRunSettings';
import PrinciplePanel from './components/PrinciplePanel';
import ResultsView from './components/ResultsView';
import Header from './components/Header';
import type { HealthStatus, Objective, Principle, RunSettings } from './types';

export default function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [objectiveText, setObjectiveText] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [objective, setObjective] = useState<Objective | null>(null);
  const [runSettings, setRunSettings] = useState<RunSettings>(DEFAULT_RUN_SETTINGS);
  const [history, setHistory] = useState<Objective[]>([]);
  const [principles, setPrinciples] = useState<Principle[]>([]);
  const [selectedPrincipleId, setSelectedPrincipleId] = useState<number | null>(null);
  const [clearingHistory, setClearingHistory] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const resultsRef = useRef<HTMLDivElement>(null);

  const loadPrinciples = useCallback(() => {
    api.listPrinciples().then(setPrinciples).catch(() => null);
  }, []);

  useEffect(() => {
    api.health().then(setHealth).catch(() => null);
    api.listObjectives().then(setHistory).catch(() => null);
    loadPrinciples();
  }, [loadPrinciples]);

  useEffect(() => {
    if (objective && !loading) {
      resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [objective?.id, loading]);

  const handleAnalyze = useCallback(async () => {
    setError(null);
    setLoading(true);
    setObjective(null);

    const text = objectiveText.trim();
    if (text.length > MAX_OBJECTIVE_LENGTH) {
      setError(
        `Objective is too long (max ${MAX_OBJECTIVE_LENGTH.toLocaleString()} characters). Please shorten your text.`
      );
      setLoading(false);
      return;
    }

    try {
      const created = await api.createObjective(objectiveText.trim(), selectedPrincipleId);
      const result = await api.analyzeObjective(created.id, runSettings);
      setObjective(result.objective);
      setHistory((prev) => [result.objective, ...prev.filter((o) => o.id !== result.objective.id)]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong');
    } finally {
      setLoading(false);
    }
  }, [objectiveText, runSettings, selectedPrincipleId]);

  const handleClearHistory = async () => {
    if (
      !window.confirm(
        'Delete all previous analyses? This permanently removes every saved objective and cannot be undone.',
      )
    ) {
      return;
    }

    setError(null);
    setClearingHistory(true);
    try {
      await api.clearObjectives();
      setHistory([]);
      setObjective(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to clear history');
    } finally {
      setClearingHistory(false);
    }
  };

  const handleDeleteObjective = async (id: number) => {
    if (!window.confirm('Delete this analysis? This cannot be undone.')) {
      return;
    }

    setError(null);
    setDeletingId(id);
    try {
      await api.deleteObjective(id);
      setHistory((prev) => prev.filter((o) => o.id !== id));
      if (objective?.id === id) {
        setObjective(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete objective');
    } finally {
      setDeletingId(null);
    }
  };

  const loadObjective = async (id: number) => {
    setError(null);
    try {
      const obj = await api.getObjective(id);
      setObjective(obj);
      setObjectiveText(obj.text);
      if (obj.principle_id) setSelectedPrincipleId(obj.principle_id);
      if (obj.run_settings) setRunSettings(obj.run_settings);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load objective');
    }
  };

  return (
    <div className="min-h-screen">
      <Header health={health} />

      <main className="mx-auto max-w-6xl px-4 py-8">
        <div className="grid gap-8 lg:grid-cols-3">
          <div className="lg:col-span-2 space-y-6">
            <ObjectiveForm
              value={objectiveText}
              onChange={setObjectiveText}
              onSubmit={handleAnalyze}
              loading={loading}
              runSettings={runSettings}
              onRunSettingsChange={setRunSettings}
              principles={principles}
              selectedPrincipleId={selectedPrincipleId}
              onPrincipleChange={setSelectedPrincipleId}
            />

            {error && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {error}
              </div>
            )}

            {loading && (
              <div className="card text-center">
                <div className="mx-auto mb-4 h-8 w-8 animate-spin rounded-full border-4 border-brand-200 border-t-brand-600" />
                <p className="font-medium text-slate-700">Running intelligence pipeline...</p>
                <p className="mt-1 text-sm text-slate-500">
                  Gathering sources → Filtering on-topic → Clustering themes (no drafts yet)
                </p>
              </div>
            )}

            {objective && !loading && (
              <div ref={resultsRef} className="scroll-mt-6">
                <ResultsView
                  objective={objective}
                  imageGenerationReady={health?.image_generation_ready ?? false}
                />
              </div>
            )}
          </div>

          <aside className="space-y-4">
            <div className="sticky top-4 space-y-4">
              <PrinciplePanel
                principles={principles}
                selectedId={selectedPrincipleId}
                onChange={loadPrinciples}
              />

            <div className="card">
              <div className="mb-3 flex items-center justify-between gap-2">
                <h3 className="font-semibold text-slate-900">Recent Objectives</h3>
                {history.length > 0 && (
                  <button
                    type="button"
                    onClick={handleClearHistory}
                    disabled={clearingHistory}
                    className="shrink-0 text-xs font-medium text-red-600 transition hover:text-red-700 disabled:opacity-50"
                  >
                    {clearingHistory ? 'Clearing…' : 'Clear all'}
                  </button>
                )}
              </div>
              {history.length === 0 ? (
                <p className="text-sm text-slate-400">No previous analyses yet.</p>
              ) : (
                <ul className="space-y-2">
                  {history.slice(0, 10).map((obj) => (
                    <li key={obj.id} className="group flex items-start gap-1 rounded-lg hover:bg-slate-50">
                      <button
                        type="button"
                        onClick={() => loadObjective(obj.id)}
                        className="min-w-0 flex-1 rounded-lg px-3 py-2 text-left text-sm transition"
                      >
                        <p className="line-clamp-2 font-medium text-slate-700">{obj.text}</p>
                        <p className="mt-0.5 text-xs text-slate-400">
                          {new Date(obj.created_at).toLocaleDateString()} · {obj.topics.length} topics
                        </p>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDeleteObjective(obj.id)}
                        disabled={deletingId === obj.id}
                        aria-label="Delete objective"
                        className="mt-1 shrink-0 rounded px-2 py-1 text-xs font-medium text-slate-400 opacity-0 transition hover:bg-red-50 hover:text-red-600 group-hover:opacity-100 disabled:opacity-50"
                      >
                        {deletingId === obj.id ? '…' : 'Delete'}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            </div>
          </aside>
        </div>
      </main>
    </div>
  );
}
