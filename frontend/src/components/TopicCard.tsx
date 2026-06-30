import { useMemo, useState } from 'react';
import { api } from '../api/client';
import type { LinkedInDraft, Topic } from '../types';
import DraftImagePanel from './DraftImagePanel';
import { DRAFT_STYLE_OPTIONS } from './DiscoverRunSettings';
import EvidencePosts from './EvidencePosts';

interface Props {
  topic: Topic;
  rank: number;
  objectiveId: number;
  imageGenerationReady: boolean;
  defaultDraftStyles: string[];
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs text-slate-500">
        <span>{label}</span>
        <span>{pct}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-slate-200">
        <div
          className="h-full rounded-full bg-brand-500 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function draftsFromTopic(topic: Topic): LinkedInDraft[] {
  if (topic.linkedin_drafts?.length) return topic.linkedin_drafts;
  if (topic.linkedin_draft) {
    return [{ label: 'Default', style: 'general', text: topic.linkedin_draft }];
  }
  return [];
}

export default function TopicCard({
  topic,
  rank,
  objectiveId,
  imageGenerationReady,
  defaultDraftStyles,
}: Props) {
  const [showDrafts, setShowDrafts] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [drafts, setDrafts] = useState<LinkedInDraft[]>(() => draftsFromTopic(topic));
  const [activeIndex, setActiveIndex] = useState(0);
  const [regenerating, setRegenerating] = useState(false);
  const [generatingDrafts, setGeneratingDrafts] = useState(false);
  const [regenError, setRegenError] = useState<string | null>(null);
  const [selectedStyles, setSelectedStyles] = useState<string[]>(defaultDraftStyles);

  const hasDrafts = drafts.length > 0;
  const activeDraft = drafts[activeIndex] ?? drafts[0];

  const generateDrafts = async () => {
    if (selectedStyles.length === 0) return;
    setGeneratingDrafts(true);
    setRegenError(null);
    try {
      const updated = await api.generateDrafts(objectiveId, topic.id, selectedStyles);
      const next = updated.linkedin_drafts?.length ? updated.linkedin_drafts : draftsFromTopic(updated);
      setDrafts(next);
      setShowDrafts(true);
      setActiveIndex(0);
    } catch (err) {
      setRegenError(err instanceof Error ? err.message : 'Could not generate drafts');
    } finally {
      setGeneratingDrafts(false);
    }
  };

  const copyDraft = async (index: number) => {
    const text = drafts[index]?.text;
    if (text) {
      await navigator.clipboard.writeText(text);
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex(null), 2000);
    }
  };

  const regenerate = async () => {
    setRegenerating(true);
    setRegenError(null);
    try {
      const updated = await api.regenerateDraft(objectiveId, topic.id, activeIndex);
      const nextDrafts = updated.linkedin_drafts?.length
        ? updated.linkedin_drafts
        : draftsFromTopic(updated);
      setDrafts(nextDrafts);
    } catch (err) {
      setRegenError(err instanceof Error ? err.message : 'Could not regenerate draft');
    } finally {
      setRegenerating(false);
    }
  };

  const draftCountLabel = useMemo(
    () => `${drafts.length} draft option${drafts.length === 1 ? '' : 's'}`,
    [drafts.length],
  );

  return (
    <div className="card overflow-hidden">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <span className="badge mb-2 bg-brand-100 text-brand-700">Topic #{rank}</span>
          <h3 className="text-xl font-bold text-slate-900">{topic.name}</h3>
          <p className="mt-1 text-sm text-slate-500">
            {topic.post_count.toLocaleString()} on-topic posts · Score:{' '}
            {(topic.score * 100).toFixed(0)}%
          </p>
          {topic.sources_summary && (
            <p className="mt-0.5 text-xs text-slate-400">Sources: {topic.sources_summary}</p>
          )}
        </div>
        <div className="w-36 shrink-0 space-y-2">
          <ScoreBar label="Relevance" value={topic.relevance_score} />
          <ScoreBar label="Engagement" value={topic.engagement_score} />
          <ScoreBar label="Freshness" value={topic.freshness_score} />
          <ScoreBar label="Volume" value={topic.volume_score} />
        </div>
      </div>

      <div className="space-y-5 border-t border-slate-100 pt-5">
        <section>
          <h4 className="mb-2 text-sm font-semibold text-slate-800">Why it is trending</h4>
          <p className="text-sm leading-relaxed text-slate-600">{topic.why_trending}</p>
        </section>

        <section>
          <h4 className="mb-2 text-sm font-semibold text-slate-800">Specific event or debate</h4>
          <p className="text-sm leading-relaxed text-slate-600">{topic.specific_event}</p>
        </section>

        <EvidencePosts posts={topic.evidence_posts} />

        <section>
          <h4 className="mb-2 text-sm font-semibold text-slate-800">Why it matters</h4>
          <p className="text-sm leading-relaxed text-slate-600">{topic.why_matters}</p>
        </section>

        <section className="rounded-lg border border-brand-200 bg-brand-50 p-4">
          <h4 className="mb-2 text-sm font-semibold text-brand-900">LinkedIn angle</h4>
          <p className="text-sm font-medium leading-relaxed text-brand-800">{topic.linkedin_angle}</p>
        </section>

        <section>
          {!hasDrafts ? (
            <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4">
              <p className="mb-3 text-sm text-slate-600">
                Drafts are not generated during discovery. Choose styles and write posts for this topic only
                when you are ready (saves Claude API cost).
              </p>
              <div className="mb-3 flex flex-wrap gap-2">
                {DRAFT_STYLE_OPTIONS.map((style) => (
                  <label
                    key={style.id}
                    className={`cursor-pointer rounded-full px-3 py-1 text-xs font-medium ${
                      selectedStyles.includes(style.id)
                        ? 'bg-brand-600 text-white'
                        : 'bg-white text-slate-600 ring-1 ring-slate-200'
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="sr-only"
                      checked={selectedStyles.includes(style.id)}
                      onChange={() =>
                        setSelectedStyles((prev) =>
                          prev.includes(style.id)
                            ? prev.filter((s) => s !== style.id)
                            : [...prev, style.id],
                        )
                      }
                    />
                    {style.label}
                  </label>
                ))}
              </div>
              <button
                type="button"
                onClick={generateDrafts}
                disabled={generatingDrafts || selectedStyles.length === 0}
                className="btn-primary text-sm disabled:opacity-50"
              >
                {generatingDrafts
                  ? 'Writing drafts…'
                  : `Write ${selectedStyles.length} LinkedIn draft${selectedStyles.length === 1 ? '' : 's'}`}
              </button>
              {regenError && <p className="mt-2 text-xs text-red-600">{regenError}</p>}
            </div>
          ) : (
            <>
              <button
                onClick={() => setShowDrafts(!showDrafts)}
                className="btn-secondary w-full"
              >
                {showDrafts ? 'Hide LinkedIn drafts' : `Show LinkedIn drafts (${draftCountLabel})`}
              </button>

              {showDrafts && activeDraft && (
                <div className="mt-4 rounded-lg border border-slate-200 bg-white p-5">
                  <div className="mb-4 flex flex-wrap gap-2">
                    {drafts.map((d, i) => (
                      <button
                        key={`${d.label}-${i}`}
                        type="button"
                        onClick={() => setActiveIndex(i)}
                        className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                          i === activeIndex
                            ? 'bg-brand-600 text-white'
                            : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                        }`}
                      >
                        {d.label}
                      </button>
                    ))}
                  </div>

                  <div className="mb-3 flex items-center justify-between gap-3">
                    <div>
                      <h4 className="text-sm font-semibold text-slate-800">{activeDraft.label}</h4>
                      <p className="text-xs capitalize text-slate-400">{activeDraft.style} style</p>
                    </div>
                    <div className="flex items-center gap-3">
                      <button
                        onClick={regenerate}
                        disabled={regenerating}
                        className="text-xs font-medium text-brand-600 hover:underline disabled:opacity-50"
                      >
                        {regenerating ? 'Regenerating…' : '↻ Regenerate this option'}
                      </button>
                      <button
                        onClick={() => copyDraft(activeIndex)}
                        className="text-xs font-medium text-brand-600 hover:underline"
                      >
                        {copiedIndex === activeIndex ? 'Copied!' : 'Copy to clipboard'}
                      </button>
                    </div>
                  </div>

                  {regenError && <p className="mb-2 text-xs text-red-600">{regenError}</p>}

                  <p
                    className={`whitespace-pre-wrap text-sm leading-relaxed text-slate-700 transition-opacity ${
                      regenerating ? 'opacity-50' : ''
                    }`}
                  >
                    {activeDraft.text}
                  </p>

                  <DraftImagePanel
                    key={`${topic.id}-${activeIndex}-${activeDraft.text.slice(0, 40)}`}
                    draft={activeDraft}
                    topicName={topic.name}
                    objectiveId={objectiveId}
                    topicId={topic.id}
                    imageGenerationReady={imageGenerationReady}
                  />
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
