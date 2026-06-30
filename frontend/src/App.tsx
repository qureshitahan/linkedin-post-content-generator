import { useCallback, useEffect, useState } from 'react';
import { api, MAX_OBJECTIVE_LENGTH } from './api/client';
import ObjectiveForm from './components/ObjectiveForm';
import { DEFAULT_RUN_SETTINGS } from './components/DiscoverRunSettings';
import ResultsView from './components/ResultsView';
import Header from './components/Header';
import type { HealthStatus, Objective, RunSettings } from './types';

export default function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [objectiveText, setObjectiveText] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [objective, setObjective] = useState<Objective | null>(null);
  const [runSettings, setRunSettings] = useState<RunSettings>(DEFAULT_RUN_SETTINGS);
  const [history, setHistory] = useState<Objective[]>([]);

  useEffect(() => {
    api.health().then(setHealth).catch(() => null);
    api.listObjectives().then(setHistory).catch(() => null);
  }, []);

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
      const created = await api.createObjective(objectiveText.trim());
      const result = await api.analyzeObjective(created.id, runSettings);
      setObjective(result.objective);
      setHistory((prev) => [result.objective, ...prev.filter((o) => o.id !== result.objective.id)]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong');
    } finally {
      setLoading(false);
    }
  }, [objectiveText, runSettings]);

  const loadObjective = async (id: number) => {
    setError(null);
    try {
      const obj = await api.getObjective(id);
      setObjective(obj);
      setObjectiveText(obj.text);
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
              <ResultsView
                objective={objective}
                imageGenerationReady={health?.image_generation_ready ?? false}
              />
            )}
          </div>

          <aside>
            <div className="card sticky top-4">
              <h3 className="mb-3 font-semibold text-slate-900">Recent Objectives</h3>
              {history.length === 0 ? (
                <p className="text-sm text-slate-400">No previous analyses yet.</p>
              ) : (
                <ul className="space-y-2">
                  {history.slice(0, 10).map((obj) => (
                    <li key={obj.id}>
                      <button
                        onClick={() => loadObjective(obj.id)}
                        className="w-full rounded-lg px-3 py-2 text-left text-sm transition hover:bg-slate-50"
                      >
                        <p className="line-clamp-2 font-medium text-slate-700">{obj.text}</p>
                        <p className="mt-0.5 text-xs text-slate-400">
                          {new Date(obj.created_at).toLocaleDateString()} · {obj.topics.length} topics
                        </p>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </aside>
        </div>
      </main>
    </div>
  );
}
