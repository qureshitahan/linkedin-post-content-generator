"""LinkedIn post video generation — text-to-video from the draft with OpenAI Sora.

Like image generation, the video is produced from the DRAFT TEXT: Claude writes a
professional text-to-video prompt from the post, Sora renders it, and (optionally) an
AI voice-over narration — script written from the same draft — is mixed onto it.
On demand only (costs Sora credits) — never runs during discovery.

A single Sora clip maxes at 12s. For longer targets (e.g. 20s) we generate a second clip
seeded from the LAST FRAME of the first (so the scene continues seamlessly) and concatenate
them with ffmpeg. Uses only the proven create() call — no reliance on the extend() endpoint.

Uses the SAME OPENAI_API_KEY as image generation — just ensure the account has Sora access.
"""

import asyncio
import logging
import os
import re
import shutil
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import Optional

from app.config import settings
from app.services.claude import claude_service
from app.services.image_service import is_valid_openai_api_key, resolve_openai_api_key

logger = logging.getLogger(__name__)

# Reuse the same data-volume convention as images (Azure persistent disk vs local).
AZURE_VIDEOS_DIR = Path("/home/site/data/generated_videos")
LOCAL_VIDEOS_DIR = Path(__file__).resolve().parent.parent.parent / "generated_videos"
VIDEOS_DIR = AZURE_VIDEOS_DIR if Path("/home/site/data").is_dir() else LOCAL_VIDEOS_DIR
VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

# Sora's allowed create() durations (strings, per the API).
CREATE_ALLOWED = (4, 8, 12)
# Two create() clips → cap the total at 24s (12 + 12).
MAX_TOTAL_SECONDS = 24
VALID_SIZES = frozenset({"720x1280", "1280x720", "1024x1792", "1792x1024"})
DEFAULT_SIZE = "1280x720"

VIDEO_SCENE_SYSTEM = """You are a creative director writing text-to-video prompts for a PREMIUM, professional LinkedIn video that brings a post's message to life.
Output ONLY the video prompt text — no preamble, no markdown, no quotes.

Goal: a polished, cinematic cover video that visually tells the post's story — like a high-end brand film or a sleek explainer. Vivid and engaging, NOT a static slide or a plain abstract loop.

Build the scene with (whatever fits the topic):
- A clear main SUBJECT or CHARACTER relevant to the post — a professional at work, a team collaborating, a customer, a doctor, an engineer — shown realistically and tastefully
- Relevant OBJECTS and a real ENVIRONMENT that ground the story (devices, screens with abstract UI, product, workspace, city, lab)
- Purposeful ANIMATION and camera work: smooth dolly / slow orbit / push-in, elements assembling, holographic UI or data coming to life around the subject, depth of field, volumetric light
- Cohesive, professional color grading and lighting; a modern, premium aesthetic

Keep it credible and on-brand for B2B:
- Realistic, professional people and settings — natural faces and motion, no cartoonish, uncanny, or caricatured characters
- Tell the story through VISUALS — do NOT rely on readable on-screen text, numbers, or charts (the model renders text as gibberish); keep any UI/signage abstract
- No logos, brand names, watermarks, or captions
- Cinematic, landscape 16:9
- Write 3-5 vivid sentences describing the subject, the environment, and the motion."""


def _draft_hook(draft_text: str) -> str:
    for line in draft_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("http"):
            return stripped[:160]
    return draft_text[:160]


def _snap(value: int, allowed) -> int:
    """Snap a requested second-count to the nearest allowed Sora value."""
    return min(allowed, key=lambda a: (abs(a - value), a))


def _plan_segments(target_seconds: int) -> tuple[int, Optional[int]]:
    """Return (first_clip_seconds, second_clip_seconds_or_None) summing to ~target.

    Both clips are produced with create() (max 12s each), so the total caps at 24s.
    """
    target = max(4, min(int(target_seconds or 12), MAX_TOTAL_SECONDS))
    if target <= 12:
        return _snap(target, CREATE_ALLOWED), None
    first = 12
    second = _snap(target - first, CREATE_ALLOWED)
    return first, second


def _ffbin(name: str) -> Optional[str]:
    """Locate an ffmpeg/ffprobe binary.

    Prefer one on PATH (local dev, or a system install); otherwise fall back to the
    static ffmpeg binary bundled in the `imageio-ffmpeg` pip wheel. That fallback is
    what makes video stitching / voice-over work on Azure App Service without Docker
    or apt — no system ffmpeg is present there. Only `ffmpeg` is bundled (not
    `ffprobe`), which is fine: this module never invokes `ffprobe`.
    """
    found = shutil.which(name)
    if found:
        return found
    if name == "ffmpeg":
        try:
            import imageio_ffmpeg

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"imageio-ffmpeg unavailable, no ffmpeg found: {e}")
    return None


def _concat(seg_a: Path, seg_b: Path, out: Path) -> bool:
    """Concatenate two Sora clips into one. Tries lossless copy, then re-encode."""
    ffmpeg = _ffbin("ffmpeg")
    if not ffmpeg:
        return False
    list_file = out.with_suffix(".txt")
    try:
        list_file.write_text(
            f"file '{seg_a.as_posix()}'\nfile '{seg_b.as_posix()}'\n", encoding="utf-8"
        )
        copy = subprocess.run(
            [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
             "-c", "copy", str(out)],
            capture_output=True, text=True, timeout=120,
        )
        if copy.returncode == 0 and out.is_file():
            return True
        reenc = subprocess.run(
            [ffmpeg, "-y", "-i", str(seg_a), "-i", str(seg_b),
             "-filter_complex",
             "[0:v:0][0:a:0][1:v:0][1:a:0]concat=n=2:v=1:a=1[v][a]",
             "-map", "[v]", "-map", "[a]", str(out)],
            capture_output=True, text=True, timeout=300,
        )
        if reenc.returncode == 0 and out.is_file():
            return True
        logger.warning("ffmpeg concat failed (copy + re-encode): %s", reenc.stderr[-500:])
        return False
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning(f"ffmpeg concat error: {e}")
        return False
    finally:
        try:
            list_file.unlink(missing_ok=True)
        except OSError:
            pass


def _media_duration(path: Path) -> Optional[float]:
    """Best-effort media duration (seconds), parsed from ffmpeg's own stderr banner.

    Avoids depending on ffprobe, which imageio-ffmpeg does NOT bundle (only ffmpeg).
    """
    ffmpeg = _ffbin("ffmpeg")
    if not ffmpeg:
        return None
    try:
        r = subprocess.run([ffmpeg, "-i", str(path)], capture_output=True, text=True, timeout=30)
    except (subprocess.SubprocessError, OSError):
        return None
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    if not m:
        return None
    h, mn, s = m.groups()
    return int(h) * 3600 + int(mn) * 60 + float(s)


def _mux_voiceover(video_path: Path, voice_path: Path, out_path: Path) -> bool:
    """Replace the video's (Sora-generated) audio with the voice-over narration.

    The voice is padded with trailing silence (apad) so shorter narration still spans
    the whole clip, and the output is HARD-CAPPED to the video's duration with `-t`.
    That cap is essential: `apad` emits an INFINITE audio stream, and combining it with
    `-shortest` fails to terminate on some ffmpeg builds — the process hangs until it is
    killed, after which the clip is left with Sora's own audio (so it won't match the
    on-screen script). Capping with `-t` sidesteps the hang entirely.
    """
    ffmpeg = _ffbin("ffmpeg")
    if not ffmpeg:
        return False
    duration = _media_duration(video_path)
    if duration and duration > 0:
        # Keep the full video length; pad the voice with silence to fill it.
        args = [ffmpeg, "-y", "-i", str(video_path), "-i", str(voice_path),
                "-filter_complex", "[1:a]apad[a]",
                "-map", "0:v:0", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-t", f"{duration:.3f}", str(out_path)]
    else:
        # Duration unknown: skip apad (no infinite stream) so it still can't hang.
        # May trim the video to the narration length, which is an acceptable fallback.
        args = [ffmpeg, "-y", "-i", str(video_path), "-i", str(voice_path),
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "copy", "-c:a", "aac", "-shortest", str(out_path)]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=180)
        if r.returncode == 0 and out_path.is_file():
            return True
        logger.warning("voiceover mux failed: %s", r.stderr[-500:])
        return False
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning(f"voiceover mux error: {e}")
        return False


VOICEOVER_SCRIPT_SYSTEM = """You write short spoken voice-over scripts for a LinkedIn video.
Output ONLY the words to be spoken — no stage directions, no markdown, no emojis, no hashtags, no speaker labels.

The narration plays over a professional video about a LinkedIn post. It must:
- Sound like a confident, warm LinkedIn thought-leader speaking naturally
- Match the post's core message and key point
- Open with a hook, deliver the key insight, and end on a crisp takeaway
- Be plain spoken sentences that read well aloud (no lists, no URLs)"""


class VideoService:
    """Text-to-video via OpenAI Sora. Mirrors ImageService so it plugs into the same flow."""

    def __init__(self):
        self._client = None
        self._client_key: str = ""

    @property
    def is_configured(self) -> bool:
        return is_valid_openai_api_key(resolve_openai_api_key())

    @property
    def key_last4(self) -> str:
        key = resolve_openai_api_key()
        return key[-4:] if len(key) >= 4 else ""

    @property
    def prompt_engine_available(self) -> bool:
        return claude_service.is_configured

    def _get_client(self):
        key = resolve_openai_api_key()
        if not is_valid_openai_api_key(key):
            raise RuntimeError(
                "OpenAI API key is not configured. Add OPENAI_API_KEY to backend/.env "
                "for video generation (Sora)."
            )
        from openai import OpenAI  # imported lazily so the app boots regardless

        if self._client is None or self._client_key != key:
            self._client = OpenAI(api_key=key, timeout=float(settings.video_poll_timeout_seconds))
            self._client_key = key
        return self._client

    def _target_size(self) -> str:
        size = (settings.openai_video_size or DEFAULT_SIZE).strip()
        return size if size in VALID_SIZES else DEFAULT_SIZE

    def craft_video_prompt(
        self, draft_text: str = "", topic_name: str = "", hint: str = ""
    ) -> str:
        """Write a text-to-video scene prompt from the draft (like the image prompt)."""
        hook = _draft_hook(draft_text)
        fallback = (
            "Cinematic, professional scene: a focused professional in a sleek modern office at "
            "golden hour, working at a glowing screen as translucent holographic UI and data "
            "gently animate in the air around them. Slow cinematic push-in with shallow depth of "
            "field, warm volumetric light, premium color grading. "
            f"The scene conveys: {hook}."
        )
        if hint.strip():
            fallback = f"{fallback} {hint.strip()}"
        if not claude_service.is_configured:
            return fallback[:1200]

        topic_block = f"\nTopic: {topic_name}" if topic_name else ""
        hint_block = f"\nUser's visual preference: {hint}" if hint.strip() else ""
        prompt = f"""Design ONE vivid, premium, cinematic text-to-video scene that brings this LinkedIn post to life.
{topic_block}

POST:
{draft_text[:1800]}

Give it a relevant main subject or character, a real environment, meaningful objects, and clear cinematic
animation/camera motion — represent the post's message through what happens on screen. Keep it professional
and realistic. Do NOT put readable text, numbers, or charts in the video.{hint_block}"""
        try:
            result = claude_service.complete(
                prompt=prompt,
                system=VIDEO_SCENE_SYSTEM,
                model=settings.anthropic_model,
                max_tokens=400,
                temperature=0.7,
            ).strip()
            return (result or fallback)[:1200]
        except Exception as e:
            logger.warning(f"Claude video prompt failed, using fallback: {e}")
            return fallback[:1200]

    def craft_voiceover_script(
        self, draft_text: str = "", topic_name: str = "", seconds: int = 20
    ) -> str:
        """Write a spoken narration (~150 wpm) aligned to the post content."""
        words = max(18, int(seconds * 2.4))
        hook = _draft_hook(draft_text)
        fallback = hook[: words * 7].strip() or "Here's what's trending and why it matters."
        if not claude_service.is_configured:
            return fallback

        topic_block = f"\nTopic: {topic_name}" if topic_name else ""
        prompt = f"""Write a spoken voice-over script of about {words} words (must fit in ~{seconds} seconds when read aloud at a natural pace).
{topic_block}

Base it on this LinkedIn post so the narration matches the video and the message:
{draft_text[:1800]}

Return ONLY the spoken words."""
        try:
            result = claude_service.complete(
                prompt=prompt,
                system=VOICEOVER_SCRIPT_SYSTEM,
                model=settings.anthropic_model,
                max_tokens=320,
                temperature=0.6,
            ).strip()
            return result or fallback
        except Exception as e:
            logger.warning(f"Claude voice-over script failed, using fallback: {e}")
            return fallback

    def _synthesize_voiceover(self, client, script: str, out_path: Path) -> bool:
        """Synthesize the narration audio that gets muxed onto the video.

        Provider dispatch (PURELY ADDITIVE — existing behavior is preserved):
        - If an ElevenLabs key + voice id are configured, narrate in that CLONED voice
          (e.g. Dalbir). On ANY failure we fall back so narration still happens.
        - Otherwise (or on ElevenLabs failure) use the OpenAI TTS path exactly as before.
        """
        if not script.strip():
            return False
        if settings.elevenlabs_api_key and settings.elevenlabs_voice_id:
            if self._synthesize_voiceover_elevenlabs(script, out_path):
                return True
            logger.warning("ElevenLabs voice-over failed; falling back to OpenAI TTS.")
        return self._synthesize_voiceover_openai(client, script, out_path)

    def _synthesize_voiceover_elevenlabs(self, script: str, out_path: Path) -> bool:
        """Narrate `script` in the configured ElevenLabs (cloned) voice → out_path.

        Uses httpx (already a dependency) — no extra SDK. Returns True only if a
        non-empty audio file was written; the caller falls back to OpenAI TTS on False.
        """
        import httpx

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}"
        headers = {"xi-api-key": settings.elevenlabs_api_key, "accept": "audio/mpeg"}
        params = {"output_format": settings.elevenlabs_output_format or "mp3_44100_128"}
        payload = {
            "text": script,
            "model_id": settings.elevenlabs_model or "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.8},
        }
        try:
            with httpx.Client(timeout=float(settings.video_poll_timeout_seconds)) as hc:
                r = hc.post(url, params=params, json=payload, headers=headers)
            if r.status_code != 200:
                logger.warning("ElevenLabs TTS failed (%s): %s", r.status_code, r.text[:300])
                return False
            out_path.write_bytes(r.content)
            return out_path.is_file() and out_path.stat().st_size > 0
        except Exception as e:  # noqa: BLE001 - fall back to OpenAI TTS
            logger.warning("ElevenLabs TTS error: %s", e)
            return False

    def _synthesize_voiceover_openai(self, client, script: str, out_path: Path) -> bool:
        """Text-to-speech via OpenAI. Returns True if the audio file was written.

        This is what makes the video FOLLOW the on-screen voice-over script: the mux
        step replaces Sora's own generated audio with this narration. If it fails, the
        clip keeps Sora's invented audio (which won't match the script), so we try the
        configured model first and then broadly available fallbacks — `tts-1` works on
        virtually every account — and log loudly if none succeed.
        """
        if not script.strip():
            return False
        primary = settings.openai_tts_model or "gpt-4o-mini-tts"
        # Ordered, de-duplicated fallback chain.
        candidates = list(dict.fromkeys([primary, "gpt-4o-mini-tts", "tts-1"]))
        fmt = settings.openai_tts_format or "mp3"
        last_err: Optional[Exception] = None

        for model in candidates:
            kwargs = dict(
                model=model,
                voice=settings.openai_tts_voice,
                input=script,
                response_format=fmt,
            )
            if model.startswith("gpt-4o"):
                kwargs["instructions"] = (
                    "Speak in a confident, warm, professional LinkedIn thought-leader voice. "
                    "Clear and measured pace, natural phrasing."
                )
            for attempt in ("with_instructions", "without_instructions"):
                if attempt == "without_instructions":
                    if "instructions" not in kwargs:
                        break  # nothing to strip; the first attempt already covered it
                    kwargs.pop("instructions", None)  # older SDKs reject `instructions`
                try:
                    resp = client.audio.speech.create(**kwargs)
                    resp.write_to_file(str(out_path))
                    if out_path.is_file():
                        if model != primary:
                            logger.warning(
                                "TTS model %r unavailable; used fallback %r.", primary, model
                            )
                        return True
                    break
                except TypeError:
                    continue  # retry this model without `instructions`
                except Exception as e:  # noqa: BLE001 - try the next model
                    last_err = e
                    logger.warning("TTS model %r failed: %s", model, e)
                    break

        logger.error(
            "Voice-over synthesis failed for all TTS models %s — video will keep Sora's "
            "own audio and will not match the script. Last error: %s",
            candidates, last_err,
        )
        return False

    def _poll(self, client, video):
        """Block until a Sora job finishes; raise on failure/timeout."""
        import time

        deadline = time.monotonic() + settings.video_poll_timeout_seconds
        interval = max(2, settings.video_poll_interval_seconds)
        while getattr(video, "status", None) in ("queued", "in_progress", "processing", None):
            if time.monotonic() > deadline:
                raise RuntimeError("Sora video timed out. Try again or use a shorter duration.")
            time.sleep(interval)
            video = client.videos.retrieve(video.id)
        if getattr(video, "status", None) != "completed":
            err = getattr(video, "error", None)
            raise RuntimeError(f"Sora video did not complete ({getattr(video, 'status', '?')}: {err}).")
        return video

    def _create_and_download(
        self, client, prompt, size, seconds, out_path: Path, image_bytes: Optional[bytes] = None
    ):
        """Create one Sora clip (text-to-video, or image-to-video if image_bytes given)."""
        kwargs = dict(
            model=settings.openai_video_model,
            prompt=prompt,
            size=size,
            seconds=str(seconds),
        )
        if image_bytes:
            kwargs["input_reference"] = ("reference.png", BytesIO(image_bytes), "image/png")
        try:
            video = client.videos.create(**kwargs)
        except Exception as e:
            raise RuntimeError(f"Sora could not start video generation: {e}") from e
        video = self._poll(client, video)
        content = client.videos.download_content(video.id, variant="video")
        content.write_to_file(str(out_path))
        return video

    def _build_base_video(
        self, client, size: str, video_prompt: str, target_seconds: int,
        seg_a: Path, seg_b: Path, base_path: Path,
    ) -> None:
        """Produce the (Sora-audio) base video into base_path — one clip, or two stitched.

        For targets over 12s both Sora clips are rendered CONCURRENTLY (each an
        independent text-to-video from the same scene prompt) and then concatenated.
        Running them in parallel roughly halves wall-clock versus the old approach,
        where clip B (image-to-video, seeded from clip A's last frame) could only
        start after clip A had finished. The continuous voice-over ties the two
        clips together, so a plain cut between them reads fine.
        """
        first_seconds, second_seconds = _plan_segments(target_seconds)

        # Short target — a single clip, no stitching needed.
        if not second_seconds:
            self._create_and_download(client, video_prompt, size, first_seconds, seg_a)
            os.replace(seg_a, base_path)
            return

        cont_prompt = (
            f"Continue the same scene with fresh, smooth, professional motion. {video_prompt}"
        )[:1200]
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_a = pool.submit(
                self._create_and_download, client, video_prompt, size, first_seconds, seg_a
            )
            fut_b = pool.submit(
                self._create_and_download, client, cont_prompt, size, second_seconds, seg_b
            )
            fut_a.result()  # clip A is required — let its error propagate and fail the job
            try:
                fut_b.result()
            except Exception as e:
                logger.warning(f"Second segment failed, using first clip only: {e}")
                os.replace(seg_a, base_path)
                return

        # Stitch the two clips into one video.
        if _concat(seg_a, seg_b, base_path):
            return
        logger.warning("Concat failed; using first clip only.")
        os.replace(seg_a, base_path)

    def _generate_blocking(
        self, size: str, video_prompt: str, target_seconds: int, voiceover_script: str = "",
    ) -> str:
        client = self._get_client()
        uid = uuid.uuid4().hex
        seg_a = VIDEOS_DIR / f"{uid}_a.mp4"
        seg_b = VIDEOS_DIR / f"{uid}_b.mp4"
        base = VIDEOS_DIR / f"{uid}_base.mp4"
        voice = VIDEOS_DIR / f"{uid}_voice.{settings.openai_tts_format or 'mp3'}"
        final_name = f"{uid}.mp4"
        final_path = VIDEOS_DIR / final_name

        try:
            self._build_base_video(
                client, size, video_prompt, target_seconds, seg_a, seg_b, base
            )

            # Voice-over: synthesize the script and replace the audio track.
            if voiceover_script.strip() and self._synthesize_voiceover(client, voiceover_script, voice):
                if _mux_voiceover(base, voice, final_path):
                    return final_name
                logger.warning("Voice-over mux failed; using video without narration.")

            os.replace(base, final_path)
            return final_name
        finally:
            self._cleanup(seg_a, seg_b, base, voice)

    @staticmethod
    def _cleanup(*paths: Path) -> None:
        for p in paths:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass

    async def generate_from_draft(
        self,
        *,
        draft_text: str,
        topic_name: str = "",
        hint: str = "",
        voiceover: bool = True,
    ) -> dict:
        if not draft_text.strip():
            raise RuntimeError("Draft text is required to generate a video.")

        size = self._target_size()
        seconds = settings.openai_video_seconds
        video_prompt = self.craft_video_prompt(draft_text, topic_name, hint)
        voiceover_script = ""
        if voiceover:
            voiceover_script = self.craft_voiceover_script(draft_text, topic_name, seconds)

        filename = await asyncio.to_thread(
            self._generate_blocking, size, video_prompt, seconds, voiceover_script
        )

        return {
            "video_url": f"/api/videos/{filename}",
            "prompt_used": video_prompt,
            "filename": filename,
            "voiceover_script": voiceover_script,
        }


video_service = VideoService()
