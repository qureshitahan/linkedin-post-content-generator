import { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import type { LinkedInDraft } from '../types';

interface Props {
  draft: LinkedInDraft;
  topicName: string;
  objectiveId: number;
  topicId: number;
  imageGenerationReady: boolean;
  autoGenerateVersion?: number;
}

interface ImageState {
  url: string;
  promptUsed: string;
}

export default function DraftImagePanel({
  draft,
  topicName,
  objectiveId,
  topicId,
  imageGenerationReady,
  autoGenerateVersion = 0,
}: Props) {
  const [image, setImage] = useState<ImageState | null>(null);
  const [promptHint, setPromptHint] = useState('');
  const [editInstruction, setEditInstruction] = useState('');
  const [generating, setGenerating] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [showPromptArea, setShowPromptArea] = useState(false);
  const lastAutoVersionRef = useRef(0);

  useEffect(() => {
    if (!generating) {
      setProgress(image && !imageLoaded ? 92 : 0);
      return;
    }

    setProgress(8);
    const startedAt = Date.now();
    const interval = window.setInterval(() => {
      const elapsedSeconds = (Date.now() - startedAt) / 1000;
      // Image generation time varies, so this is an estimate that slows near the end.
      const estimated = Math.min(88, 8 + Math.round(elapsedSeconds * 8));
      setProgress((current) => Math.max(current, estimated));
    }, 700);

    return () => window.clearInterval(interval);
  }, [generating, image, imageLoaded]);

  const generate = async (mode: 'new' | 'edit') => {
    if (!imageGenerationReady) {
      setError('Add OPENAI_API_KEY to .env to enable image generation.');
      return;
    }

    setGenerating(true);
    if (mode === 'new') setImage(null);
    setImageLoaded(false);
    setError(null);
    try {
      const result = await api.generateImage(objectiveId, topicId, {
        draft_text: draft.text,
        topic_name: topicName,
        draft_style: draft.style,
        draft_label: draft.label,
        mode,
        custom_prompt: mode === 'new' ? promptHint : '',
        previous_prompt: mode === 'edit' && image ? image.promptUsed : '',
        edit_instruction: mode === 'edit' ? editInstruction : '',
      });
      setImage({ url: result.image_url, promptUsed: result.prompt_used });
      setProgress(92);
      if (mode === 'edit') setEditInstruction('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Image generation failed');
      setProgress(0);
    } finally {
      setGenerating(false);
    }
  };

  useEffect(() => {
    if (autoGenerateVersion <= 0 || autoGenerateVersion === lastAutoVersionRef.current) return;
    lastAutoVersionRef.current = autoGenerateVersion;
    if (!imageGenerationReady || generating) return;
    void generate('new');
  }, [autoGenerateVersion, imageGenerationReady]);

  const loadingLabel = image && !imageLoaded ? 'Loading generated image…' : 'Creating image…';

  return (
    <div className="mt-4 border-t border-slate-100 pt-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h5 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Image for this draft
        </h5>
        {!image && (
          <button
            type="button"
            onClick={() => setShowPromptArea(!showPromptArea)}
            className="text-xs text-slate-500 hover:text-brand-600"
          >
            {showPromptArea ? 'Hide prompt options' : 'Customize prompt'}
          </button>
        )}
      </div>

      {!imageGenerationReady && (
        <p className="mb-3 text-xs text-amber-700">
          Generates a designed LinkedIn slide — headline text, stats, charts, or flat illustrations.
          Not AI photos.
        </p>
      )}

      {showPromptArea && !image && (
        <div className="mb-3">
          <label className="mb-1 block text-xs font-medium text-slate-600">
            Visual direction (optional)
          </label>
          <textarea
            value={promptHint}
            onChange={(e) => setPromptHint(e.target.value)}
            placeholder="e.g. bar chart of 8x vs 4x EBITDA, stat slide with 60-80%, headline only…"
            rows={2}
            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 placeholder:text-slate-400 focus:border-brand-400 focus:outline-none focus:ring-1 focus:ring-brand-400"
          />
          <p className="mt-1 text-xs text-slate-400">
            Creates a designed LinkedIn graphic tied to this post — chart, stat slide, headline, or
            flat illustration. Click again for a different format.
          </p>
        </div>
      )}

      {!image ? (
        generating ? (
          <div className="rounded-xl border border-brand-100 bg-brand-50/60 p-4">
            <div className="mb-2 flex items-center justify-between text-sm">
              <span className="font-semibold text-brand-900">{loadingLabel}</span>
              <span className="font-mono text-xs text-brand-700">{progress}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-white">
              <div
                className="h-full rounded-full bg-brand-600 transition-all duration-500"
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className="mt-2 text-xs text-brand-700">
              Usually takes 20-60 seconds. The image will appear here automatically.
            </p>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => generate('new')}
            disabled={generating || !imageGenerationReady}
            className="btn-primary text-sm disabled:cursor-not-allowed disabled:opacity-50"
          >
            Generate image from this draft
          </button>
        )
      ) : (
        <div className="space-y-4">
          <div className="relative overflow-hidden rounded-lg border border-slate-200 bg-slate-100">
            {!imageLoaded && (
              <div className="absolute inset-0 z-10 flex flex-col justify-center bg-white/90 p-4">
                <div className="mb-2 flex items-center justify-between text-sm">
                  <span className="font-semibold text-slate-800">{loadingLabel}</span>
                  <span className="font-mono text-xs text-slate-500">{progress}%</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-slate-200">
                  <div
                    className="h-full rounded-full bg-brand-600 transition-all duration-500"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>
            )}
            <img
              src={image.url}
              alt="Generated LinkedIn post visual"
              onLoad={() => {
                setImageLoaded(true);
                setProgress(100);
              }}
              onError={() => {
                setImageLoaded(true);
                setError('Image was generated, but the browser could not load it. Try Generate new image.');
              }}
              className={`w-full object-cover transition-opacity duration-300 ${
                imageLoaded ? 'opacity-100' : 'opacity-0'
              }`}
            />
          </div>

          <details className="text-xs text-slate-500">
            <summary className="cursor-pointer font-medium text-slate-600">Prompt used</summary>
            <p className="mt-2 whitespace-pre-wrap rounded bg-slate-50 p-3 text-slate-600">
              {image.promptUsed}
            </p>
          </details>

          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">
              Refine this image
            </label>
            <textarea
              value={editInstruction}
              onChange={(e) => setEditInstruction(e.target.value)}
              placeholder="e.g. bigger headline text, add a simple chart, more minimal flat style…"
              rows={2}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 placeholder:text-slate-400 focus:border-brand-400 focus:outline-none focus:ring-1 focus:ring-brand-400"
            />
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => generate('edit')}
              disabled={generating || !editInstruction.trim()}
              className="btn-secondary text-sm disabled:opacity-50"
            >
              {generating ? 'Refining…' : 'Apply changes'}
            </button>
            <button
              type="button"
              onClick={() => {
                setImage(null);
                setImageLoaded(false);
                setEditInstruction('');
                setShowPromptArea(true);
                void generate('new');
              }}
              disabled={generating}
              className="btn-secondary text-sm"
            >
              {generating ? 'Generating…' : 'Generate new image'}
            </button>
            <a
              href={image.url}
              download
              className="btn-secondary text-sm no-underline"
            >
              Download
            </a>
          </div>
        </div>
      )}

      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
    </div>
  );
}
