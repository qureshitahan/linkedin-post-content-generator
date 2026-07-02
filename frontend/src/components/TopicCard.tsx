import { useMemo, useState } from 'react';
import { api } from '../api/client';
import type { LinkedInDraft, Topic } from '../types';
import DraftImagePanel from './DraftImagePanel';
import { DRAFT_STYLE_OPTIONS } from './DiscoverRunSettings';
import EvidencePosts from './EvidencePosts';
import { ToggleRow } from './ToggleSwitch';

interface Props {
  topic: Topic;
  rank: number;
  objectiveId: number;
  imageGenerationReady: boolean;
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

function draftHook(text: string): string {
  const line = text.split('\n').map((l) => l.trim()).find(Boolean);
  return line ?? text.slice(0, 120);
}

export default function TopicCard({
  topic,
  rank,
  objectiveId,
  imageGenerationReady,
}: Props) {
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [drafts, setDrafts] = useState<LinkedInDraft[]>(() => draftsFromTopic(topic));
  const [regeneratingIndex, setRegeneratingIndex] = useState<number | null>(null);
  const [generatingDrafts, setGeneratingDrafts] = useState(false);
  const [autoImageVersions, setAutoImageVersions] = useState<Record<number, number>>({});
  const [regenError, setRegenError] = useState<string | null>(null);
  const [selectedStyles, setSelectedStyles] = useState<string[]>(() =>
    DRAFT_STYLE_OPTIONS.map((s) => s.id),
  );

  const hasDrafts = drafts.length > 0;

  const generateDrafts = async () => {
    if (selectedStyles.length === 0) return;
    setGeneratingDrafts(true);
    setRegenError(null);
    try {
      const updated = await api.generateDrafts(objectiveId, topic.id, selectedStyles);
      const next = updated.linkedin_drafts?.length ? updated.linkedin_drafts : draftsFromTopic(updated);
      setDrafts(next);
      if (imageGenerationReady) {
        const version = Date.now();
        setAutoImageVersions(
          next.reduce<Record<number, number>>((acc, _draft, index) => {
            acc[index] = version + index;
            return acc;
          }, {}),
        );
      }
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

  const regenerate = async (index: number) => {
    setRegeneratingIndex(index);
    setRegenError(null);
    try {
      const updated = await api.regenerateDraft(objectiveId, topic.id, index);
      const nextDrafts = updated.linkedin_drafts?.length
        ? updated.linkedin_drafts
        : draftsFromTopic(updated);
      setDrafts(nextDrafts);
      if (imageGenerationReady) {
        setAutoImageVersions((prev) => ({ ...prev, [index]: Date.now() }));
      }
    } catch (err) {
      setRegenError(err instanceof Error ? err.message : 'Could not regenerate draft');
    } finally {
      setRegeneratingIndex(null);
    }
  };

  const draftCountLabel = useMemo(
    () => `${drafts.length} draft${drafts.length === 1 ? '' : 's'}`,
    [drafts.length],
  );

  return (
    <div className="card overflow-hidden">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="badge bg-brand-100 text-brand-700">Topic #{rank}</span>
            {hasDrafts && (
              <span className="badge bg-green-100 text-green-800">
                {draftCountLabel} ready
              </span>
            )}
          </div>
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
              <h4 className="text-sm font-semibold text-slate-800">Write LinkedIn drafts</h4>
              <p className="mb-3 mt-1 text-sm text-slate-600">
                Choose draft styles, then generate posts for this topic. Images will start
                automatically for each generated post.
              </p>
              <div className="mb-2 flex items-center justify-between gap-2">
                <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  Draft styles for this topic
                </p>
                <span className="text-xs text-slate-400">
                  {selectedStyles.length} of {DRAFT_STYLE_OPTIONS.length} on
                </span>
              </div>
              <div className="mb-3 space-y-2">
                {DRAFT_STYLE_OPTIONS.map((style) => (
                  <ToggleRow
                    key={style.id}
                    checked={selectedStyles.includes(style.id)}
                    onChange={(on) =>
                      setSelectedStyles((prev) =>
                        on
                          ? prev.includes(style.id)
                            ? prev
                            : [...prev, style.id]
                          : prev.filter((s) => s !== style.id),
                      )
                    }
                    label={style.label}
                    description={style.desc}
                  />
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
                  : `Generate ${selectedStyles.length} LinkedIn post${selectedStyles.length === 1 ? '' : 's'} + images`}
              </button>
              {regenError && <p className="mt-2 text-xs text-red-600">{regenError}</p>}
            </div>
          ) : (
            <div className="rounded-xl border-2 border-brand-200 bg-gradient-to-b from-brand-50/80 to-white p-4 sm:p-5">
              <div className="mb-4">
                <div className="flex flex-wrap items-center gap-2">
                  <h4 className="text-base font-bold text-slate-900">LinkedIn drafts</h4>
                  <span className="rounded-full bg-brand-600 px-2.5 py-0.5 text-xs font-semibold text-white">
                    {drafts.length} {drafts.length === 1 ? 'option' : 'options'}
                  </span>
                </div>
                <p className="mt-1 text-sm text-slate-600">
                  Each card below is a full post in a different style. Scroll to compare — no need
                  to click tabs.
                </p>
              </div>

              {regenError && <p className="mb-3 text-xs text-red-600">{regenError}</p>}

              <div className="space-y-4">
                {drafts.map((draft, index) => {
                  const isRegenerating = regeneratingIndex === index;
                  return (
                    <article
                      key={`${draft.label}-${index}`}
                      className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 bg-slate-50 px-4 py-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-600 text-xs font-bold text-white">
                            {index + 1}
                          </span>
                          <div>
                            <p className="text-sm font-semibold text-slate-900">{draft.label}</p>
                            <p className="text-xs capitalize text-slate-500">{draft.style} style</p>
                          </div>
                        </div>
                        <div className="flex items-center gap-3">
                          <button
                            type="button"
                            onClick={() => regenerate(index)}
                            disabled={isRegenerating || regeneratingIndex !== null}
                            className="text-xs font-medium text-brand-600 hover:underline disabled:opacity-50"
                          >
                            {isRegenerating ? 'Regenerating…' : '↻ Regenerate'}
                          </button>
                          <button
                            type="button"
                            onClick={() => copyDraft(index)}
                            className="rounded-md bg-brand-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-700"
                          >
                            {copiedIndex === index ? 'Copied!' : 'Copy'}
                          </button>
                        </div>
                      </div>

                      <div className="border-b border-slate-100 bg-white px-4 py-3">
                        <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
                          Opening hook
                        </p>
                        <p className="mt-1 text-sm font-semibold leading-snug text-slate-800">
                          {draftHook(draft.text)}
                        </p>
                      </div>

                      <div className="px-4 py-4">
                        <p
                          className={`whitespace-pre-wrap text-sm leading-relaxed text-slate-700 ${
                            isRegenerating ? 'opacity-50' : ''
                          }`}
                        >
                          {draft.text}
                        </p>
                      </div>

                      <div className="border-t border-slate-100 px-4 py-3">
                        <DraftImagePanel
                          draft={draft}
                          topicName={topic.name}
                          objectiveId={objectiveId}
                          topicId={topic.id}
                          imageGenerationReady={imageGenerationReady}
                          autoGenerateVersion={autoImageVersions[index] ?? 0}
                        />
                      </div>
                    </article>
                  );
                })}
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
