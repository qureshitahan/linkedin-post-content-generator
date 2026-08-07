import { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import type { LinkedInDraft } from '../types';

interface Props {
  draft: LinkedInDraft;
  topicName: string;
  objectiveId: number;
  topicId: number;
  imageGenerationReady: boolean;
  videoGenerationReady?: boolean;
  autoGenerateVersion?: number;
}

interface ImageState {
  url: string;
  promptUsed: string;
  filename: string;
}

interface VideoState {
  url: string;
  promptUsed: string;
  script: string;
  filename: string;
}

export default function DraftImagePanel({
  draft,
  topicName,
  objectiveId,
  topicId,
  imageGenerationReady,
  videoGenerationReady = false,
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

  // --- Video (text-to-video via OpenAI Sora, generated from the draft) ---
  const [video, setVideo] = useState<VideoState | null>(null);
  const [videoGenerating, setVideoGenerating] = useState(false);
  const [videoProgress, setVideoProgress] = useState(0);
  const [videoError, setVideoError] = useState<string | null>(null);
  const [videoHint, setVideoHint] = useState('');
  const [voiceover, setVoiceover] = useState(true);

  // --- LinkedIn publishing (post caption + image/video to Dalbir's profile) ---
  const [linkedInReady, setLinkedInReady] = useState(false);
  const [postingImage, setPostingImage] = useState(false);
  const [imagePostUrl, setImagePostUrl] = useState<string | null>(null);
  const [imagePostError, setImagePostError] = useState<string | null>(null);
  const [postingVideo, setPostingVideo] = useState(false);
  const [videoPostUrl, setVideoPostUrl] = useState<string | null>(null);
  const [videoPostError, setVideoPostError] = useState<string | null>(null);

  useEffect(() => {
    api
      .linkedInStatus()
      .then((s) => setLinkedInReady(s.configured))
      .catch(() => setLinkedInReady(false));
  }, []);

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
      setImage({ url: result.image_url, promptUsed: result.prompt_used, filename: result.filename });
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

  // Sora clips take minutes, so this bar creeps up slowly.
  useEffect(() => {
    if (!videoGenerating) return;
    setVideoProgress(4);
    const startedAt = Date.now();
    const interval = window.setInterval(() => {
      const elapsedSeconds = (Date.now() - startedAt) / 1000;
      const estimated = Math.min(92, 4 + Math.round(elapsedSeconds * 0.6));
      setVideoProgress((current) => Math.max(current, estimated));
    }, 1000);
    return () => window.clearInterval(interval);
  }, [videoGenerating]);

  const generateVideo = async () => {
    if (!videoGenerationReady) {
      setVideoError('Add OPENAI_API_KEY (with Sora access) to backend/.env to enable video generation.');
      return;
    }

    setVideoGenerating(true);
    setVideoError(null);
    setVideo(null);
    try {
      const result = await api.generateVideo(objectiveId, topicId, {
        draft_text: draft.text,
        topic_name: topicName,
        motion_hint: videoHint,
        voiceover,
      });
      setVideo({
        url: result.video_url,
        promptUsed: result.prompt_used,
        script: result.voiceover_script ?? '',
        filename: result.filename ?? '',
      });
      setVideoProgress(100);
    } catch (err) {
      setVideoError(err instanceof Error ? err.message : 'Video generation failed');
      setVideoProgress(0);
    } finally {
      setVideoGenerating(false);
    }
  };

  const postImageToLinkedIn = async () => {
    if (!image) return;
    setPostingImage(true);
    setImagePostError(null);
    setImagePostUrl(null);
    try {
      const res = await api.postToLinkedIn(objectiveId, topicId, {
        caption: draft.text,
        media_type: 'image',
        filename: image.filename,
      });
      setImagePostUrl(res.post_url);
    } catch (err) {
      setImagePostError(err instanceof Error ? err.message : 'Failed to post to LinkedIn');
    } finally {
      setPostingImage(false);
    }
  };

  const postVideoToLinkedIn = async () => {
    if (!video) return;
    setPostingVideo(true);
    setVideoPostError(null);
    setVideoPostUrl(null);
    try {
      const res = await api.postToLinkedIn(objectiveId, topicId, {
        caption: draft.text,
        media_type: 'video',
        filename: video.filename,
      });
      setVideoPostUrl(res.post_url);
    } catch (err) {
      setVideoPostError(err instanceof Error ? err.message : 'Failed to post to LinkedIn');
    } finally {
      setPostingVideo(false);
    }
  };

  const loadingLabel = image && !imageLoaded ? 'Loading generated image…' : 'Creating image…';

  return (
    <div className="mt-4 space-y-6">
      {/* ============================ IMAGE ============================ */}
      <div className="border-t border-slate-100 pt-4">
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
              <a href={image.url} download className="btn-secondary text-sm no-underline">
                Download
              </a>
              {linkedInReady && (
                <button
                  type="button"
                  onClick={postImageToLinkedIn}
                  disabled={postingImage || !imageLoaded}
                  className="btn-primary text-sm disabled:opacity-50"
                >
                  {postingImage ? 'Posting to LinkedIn…' : 'Post to LinkedIn'}
                </button>
              )}
            </div>

            {imagePostUrl && (
              <p className="text-xs text-green-700">
                Posted to LinkedIn.{' '}
                <a href={imagePostUrl} target="_blank" rel="noreferrer" className="font-medium underline">
                  View post
                </a>
              </p>
            )}
            {imagePostError && <p className="text-xs text-red-600">{imagePostError}</p>}
          </div>
        )}

        {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
      </div>

      {/* ============================ VIDEO (text-to-video) ============================ */}
      <div className="border-t border-slate-100 pt-4">
        <h5 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Video for this draft
        </h5>

        {!videoGenerationReady ? (
          <p className="text-xs text-amber-700">
            Add <span className="font-mono">OPENAI_API_KEY</span> (with Sora access) to backend/.env to
            generate a short LinkedIn video from this draft (OpenAI Sora).
          </p>
        ) : !video ? (
          videoGenerating ? (
            <div className="rounded-xl border border-brand-100 bg-brand-50/60 p-4">
              <div className="mb-2 flex items-center justify-between text-sm">
                <span className="font-semibold text-brand-900">Creating video…</span>
                <span className="font-mono text-xs text-brand-700">{videoProgress}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-white">
                <div
                  className="h-full rounded-full bg-brand-600 transition-all duration-500"
                  style={{ width: `${videoProgress}%` }}
                />
              </div>
              <p className="mt-2 text-xs text-brand-700">
                A 20s clip with voice-over takes ~2–5 minutes (two Sora clips + narration).
                The video will appear here automatically.
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-slate-400">
                Generates a ~20s video from this post's content (OpenAI Sora), with an optional
                AI voice-over scripted from the same draft.
              </p>
              <textarea
                value={videoHint}
                onChange={(e) => setVideoHint(e.target.value)}
                placeholder="Visual direction (optional) — e.g. clean motion graphics, office b-roll, data flowing…"
                rows={2}
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 placeholder:text-slate-400 focus:border-brand-400 focus:outline-none focus:ring-1 focus:ring-brand-400"
              />
              <label className="flex items-center gap-2 text-xs text-slate-600">
                <input
                  type="checkbox"
                  checked={voiceover}
                  onChange={(e) => setVoiceover(e.target.checked)}
                  className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-400"
                />
                Add AI voice-over (script written from this post)
              </label>
              <button
                type="button"
                onClick={generateVideo}
                disabled={videoGenerating}
                className="btn-primary text-sm disabled:cursor-not-allowed disabled:opacity-50"
              >
                Generate video from this draft
              </button>
            </div>
          )
        ) : (
          <div className="space-y-3">
            <video
              src={video.url}
              controls
              loop
              playsInline
              className="w-full rounded-lg border border-slate-200 bg-black"
            />
            {video.script && (
              <details className="text-xs text-slate-500" open>
                <summary className="cursor-pointer font-medium text-slate-600">Voice-over script</summary>
                <p className="mt-2 whitespace-pre-wrap rounded bg-slate-50 p-3 text-slate-600">
                  {video.script}
                </p>
              </details>
            )}
            <details className="text-xs text-slate-500">
              <summary className="cursor-pointer font-medium text-slate-600">Video prompt used</summary>
              <p className="mt-2 whitespace-pre-wrap rounded bg-slate-50 p-3 text-slate-600">
                {video.promptUsed}
              </p>
            </details>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={generateVideo}
                disabled={videoGenerating}
                className="btn-secondary text-sm disabled:opacity-50"
              >
                {videoGenerating ? 'Generating…' : 'Regenerate video'}
              </button>
              <a href={video.url} download className="btn-secondary text-sm no-underline">
                Download video
              </a>
              {linkedInReady && (
                <button
                  type="button"
                  onClick={postVideoToLinkedIn}
                  disabled={postingVideo}
                  className="btn-primary text-sm disabled:opacity-50"
                >
                  {postingVideo ? 'Posting to LinkedIn…' : 'Post to LinkedIn'}
                </button>
              )}
            </div>

            {postingVideo && (
              <p className="text-xs text-brand-700">
                Uploading to LinkedIn and publishing — this can take up to a minute for video.
              </p>
            )}
            {videoPostUrl && (
              <p className="text-xs text-green-700">
                Posted to LinkedIn.{' '}
                <a href={videoPostUrl} target="_blank" rel="noreferrer" className="font-medium underline">
                  View post
                </a>
              </p>
            )}
            {videoPostError && <p className="text-xs text-red-600">{videoPostError}</p>}
          </div>
        )}

        {videoError && <p className="mt-2 text-xs text-red-600">{videoError}</p>}
      </div>
    </div>
  );
}
