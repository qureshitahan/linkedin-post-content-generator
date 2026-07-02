import { useState } from 'react';
import { api } from '../api/client';
import type { LinkedInDraft } from '../types';

interface Props {
  draft: LinkedInDraft;
  topicName: string;
  objectiveId: number;
  topicId: number;
  imageGenerationReady: boolean;
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
}: Props) {
  const [image, setImage] = useState<ImageState | null>(null);
  const [promptHint, setPromptHint] = useState('');
  const [editInstruction, setEditInstruction] = useState('');
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPromptArea, setShowPromptArea] = useState(false);

  const generate = async (mode: 'new' | 'edit') => {
    if (!imageGenerationReady) {
      setError('Add OPENAI_API_KEY to .env to enable image generation.');
      return;
    }

    setGenerating(true);
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
      if (mode === 'edit') setEditInstruction('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Image generation failed');
    } finally {
      setGenerating(false);
    }
  };

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
        <button
          type="button"
          onClick={() => generate('new')}
          disabled={generating || !imageGenerationReady}
          className="btn-primary text-sm disabled:cursor-not-allowed disabled:opacity-50"
        >
          {generating ? 'Generating image…' : 'Generate image from this draft'}
        </button>
      ) : (
        <div className="space-y-4">
          <div className="overflow-hidden rounded-lg border border-slate-200 bg-slate-100">
            <img
              src={image.url}
              alt="Generated LinkedIn post visual"
              className="w-full object-cover"
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
                setEditInstruction('');
                setShowPromptArea(true);
              }}
              disabled={generating}
              className="btn-secondary text-sm"
            >
              Generate new image
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
