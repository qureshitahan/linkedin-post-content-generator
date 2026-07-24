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
import shutil
import subprocess
import uuid
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


def _extract_last_frame(video_path: Path, out_png: Path) -> bool:
    """Grab the final frame of a clip as a PNG (used to seed the continuation clip)."""
    ffmpeg = _ffbin("ffmpeg")
    if not ffmpeg:
        return False
    try:
        r = subprocess.run(
            [ffmpeg, "-y", "-sseof", "-0.2", "-i", str(video_path),
             "-frames:v", "1", "-q:v", "2", str(out_png)],
            capture_output=True, text=True, timeout=60,
        )
        return r.returncode == 0 and out_png.is_file()
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning(f"last-frame extraction failed: {e}")
        return False


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


def _mux_voiceover(video_path: Path, voice_path: Path, out_path: Path) -> bool:
    """Replace the video's audio with the voice-over, padded/capped to the video length."""
    ffmpeg = _ffbin("ffmpeg")
    if not ffmpeg:
        return False
    try:
        r = subprocess.run(
            [ffmpeg, "-y", "-i", str(video_path), "-i", str(voice_path),
             "-filter_complex", "[1:a]apad[a]",
             "-map", "0:v:0", "-map", "[a]",
             "-c:v", "copy", "-c:a", "aac", "-shortest", str(out_path)],
            capture_output=True, text=True, timeout=180,
        )
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
        """Text-to-speech via OpenAI. Returns True if the audio file was written."""
        if not script.strip():
            return False
        kwargs = dict(
            model=settings.openai_tts_model,
            voice=settings.openai_tts_voice,
            input=script,
            response_format=settings.openai_tts_format or "mp3",
        )
        if settings.openai_tts_model.startswith("gpt-4o"):
            kwargs["instructions"] = (
                "Speak in a confident, warm, professional LinkedIn thought-leader voice. "
                "Clear and measured pace, natural phrasing."
            )
        try:
            resp = client.audio.speech.create(**kwargs)
            resp.write_to_file(str(out_path))
            return out_path.is_file()
        except TypeError:
            kwargs.pop("instructions", None)
            try:
                resp = client.audio.speech.create(**kwargs)
                resp.write_to_file(str(out_path))
                return out_path.is_file()
            except Exception as e:
                logger.warning(f"TTS failed: {e}")
                return False
        except Exception as e:
            logger.warning(f"TTS failed: {e}")
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
        seg_a: Path, seg_b: Path, frame: Path, base_path: Path,
    ) -> None:
        """Produce the (Sora-audio) video into base_path — one clip, or two stitched."""
        first_seconds, second_seconds = _plan_segments(target_seconds)

        # 1. First clip: text-to-video from the draft-derived prompt.
        self._create_and_download(client, video_prompt, size, first_seconds, seg_a)

        # 2. Short target — no continuation needed.
        if not second_seconds:
            os.replace(seg_a, base_path)
            return

        # 3. Continue: seed a second clip from clip A's last frame (image-to-video) for continuity.
        try:
            if not _extract_last_frame(seg_a, frame):
                raise RuntimeError("ffmpeg could not extract the last frame")
            cont_prompt = (
                f"Continue this scene seamlessly with smooth, professional motion. {video_prompt}"
            )[:1200]
            self._create_and_download(
                client, cont_prompt, size, second_seconds, seg_b, image_bytes=frame.read_bytes()
            )
        except Exception as e:
            logger.warning(f"Second segment failed, using first clip only: {e}")
            os.replace(seg_a, base_path)
            return

        # 4. Stitch the two clips into one continuous video.
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
        frame = VIDEOS_DIR / f"{uid}_frame.png"
        base = VIDEOS_DIR / f"{uid}_base.mp4"
        voice = VIDEOS_DIR / f"{uid}_voice.{settings.openai_tts_format or 'mp3'}"
        final_name = f"{uid}.mp4"
        final_path = VIDEOS_DIR / final_name

        try:
            self._build_base_video(
                client, size, video_prompt, target_seconds, seg_a, seg_b, frame, base
            )

            # Voice-over: synthesize the script and replace the audio track.
            if voiceover_script.strip() and self._synthesize_voiceover(client, voiceover_script, voice):
                if _mux_voiceover(base, voice, final_path):
                    return final_name
                logger.warning("Voice-over mux failed; using video without narration.")

            os.replace(base, final_path)
            return final_name
        finally:
            self._cleanup(seg_a, seg_b, frame, base, voice)

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
