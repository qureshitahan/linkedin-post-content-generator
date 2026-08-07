"""Publish a caption + image or video to a LinkedIn member profile.

Uses a member access token obtained via LinkedIn OAuth out-of-band (no in-app connect
flow, per requirement). Flow for both media types:
  1. Upload the media via the REST images/videos endpoints (chunked for video).
  2. Reference the returned media URN in a /rest/posts publish.

All calls use httpx. The individual API steps were verified against the live API
(image: initializeUpload -> PUT; video: initializeUpload -> PUT chunks + ETags ->
finalizeUpload) before wiring this in.
"""

import logging
import time
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_API = "https://api.linkedin.com"
_IMAGE_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


class LinkedInError(RuntimeError):
    """Raised when a LinkedIn publish step fails."""


def _post_url(post_urn: str) -> str:
    return (
        f"https://www.linkedin.com/feed/update/{post_urn}"
        if post_urn
        else "https://www.linkedin.com/feed/"
    )


class LinkedInService:
    """Post caption + media to a member profile using a pre-obtained access token."""

    @property
    def is_configured(self) -> bool:
        return bool(settings.linkedin_access_token and settings.linkedin_person_urn)

    def _headers(self, with_json: bool = True) -> dict:
        headers = {
            "Authorization": f"Bearer {settings.linkedin_access_token}",
            "LinkedIn-Version": settings.linkedin_api_version or "202606",
            "X-Restli-Protocol-Version": "2.0.0",
        }
        if with_json:
            headers["Content-Type"] = "application/json"
        return headers

    def _bearer(self) -> dict:
        return {"Authorization": f"Bearer {settings.linkedin_access_token}"}

    # ------------------------------ image ------------------------------
    def _upload_image(self, client: httpx.Client, image_path: Path) -> str:
        r = client.post(
            f"{_API}/rest/images?action=initializeUpload",
            headers=self._headers(),
            json={"initializeUploadRequest": {"owner": settings.linkedin_person_urn}},
        )
        if r.status_code != 200:
            raise LinkedInError(f"image initializeUpload failed ({r.status_code}): {r.text[:300]}")
        value = r.json()["value"]
        content_type = _IMAGE_CONTENT_TYPES.get(image_path.suffix.lower(), "application/octet-stream")
        up = client.put(
            value["uploadUrl"],
            content=image_path.read_bytes(),
            headers={**self._bearer(), "Content-Type": content_type},
        )
        if up.status_code not in (200, 201):
            raise LinkedInError(f"image binary upload failed ({up.status_code})")
        return value["image"]

    # ------------------------------ video ------------------------------
    def _upload_video(self, client: httpx.Client, video_path: Path) -> str:
        data = video_path.read_bytes()
        r = client.post(
            f"{_API}/rest/videos?action=initializeUpload",
            headers=self._headers(),
            json={
                "initializeUploadRequest": {
                    "owner": settings.linkedin_person_urn,
                    "fileSizeBytes": len(data),
                    "uploadCaptions": False,
                    "uploadThumbnail": False,
                }
            },
        )
        if r.status_code != 200:
            raise LinkedInError(f"video initializeUpload failed ({r.status_code}): {r.text[:300]}")
        value = r.json()["value"]
        video_urn = value["video"]
        part_ids: list[str] = []
        for ins in value["uploadInstructions"]:
            chunk = data[ins["firstByte"]: ins["lastByte"] + 1]
            up = client.put(
                ins["uploadUrl"],
                content=chunk,
                headers={**self._bearer(), "Content-Type": "application/octet-stream"},
            )
            if up.status_code not in (200, 201):
                raise LinkedInError(f"video chunk upload failed ({up.status_code})")
            etag = up.headers.get("ETag") or up.headers.get("etag")
            if not etag:
                raise LinkedInError("video chunk upload returned no ETag")
            part_ids.append(etag)
        fin = client.post(
            f"{_API}/rest/videos?action=finalizeUpload",
            headers=self._headers(),
            json={
                "finalizeUploadRequest": {
                    "video": video_urn,
                    "uploadToken": value["uploadToken"],
                    "uploadedPartIds": part_ids,
                }
            },
        )
        if fin.status_code not in (200, 201):
            raise LinkedInError(f"video finalizeUpload failed ({fin.status_code}): {fin.text[:300]}")
        self._await_video_ready(client, video_urn)
        return video_urn

    def _await_video_ready(self, client: httpx.Client, video_urn: str, timeout: float = 120.0) -> None:
        """Best-effort wait until LinkedIn finishes processing the video before posting."""
        encoded = video_urn.replace(":", "%3A")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                r = client.get(f"{_API}/rest/videos/{encoded}", headers=self._headers(with_json=False))
                if r.status_code == 200:
                    status = r.json().get("status")
                    if status == "AVAILABLE":
                        return
                    if status in ("PROCESSING_FAILED", "UPLOAD_FAILED"):
                        raise LinkedInError(f"video processing failed (status={status})")
            except LinkedInError:
                raise
            except Exception as e:  # noqa: BLE001 - tolerate transient status errors
                logger.warning(f"video status check error (continuing): {e}")
            time.sleep(3)
        logger.warning("video not confirmed AVAILABLE within %.0fs; attempting to post anyway", timeout)

    # ----------------------------- publish -----------------------------
    def _create_post(self, client: httpx.Client, caption: str, media_urn: str) -> dict:
        payload = {
            "author": settings.linkedin_person_urn,
            "commentary": caption,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "content": {"media": {"id": media_urn}},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        r = client.post(f"{_API}/rest/posts", headers=self._headers(), json=payload)
        if r.status_code not in (200, 201):
            raise LinkedInError(f"post publish failed ({r.status_code}): {r.text[:400]}")
        post_urn = r.headers.get("x-restli-id") or r.headers.get("x-linkedin-id") or ""
        return {"post_urn": post_urn, "post_url": _post_url(post_urn)}

    def post_image(self, caption: str, image_path: Path) -> dict:
        if not self.is_configured:
            raise LinkedInError("LinkedIn is not configured (missing token or person URN).")
        with httpx.Client(timeout=180.0) as client:
            media_urn = self._upload_image(client, image_path)
            return self._create_post(client, caption, media_urn)

    def post_video(self, caption: str, video_path: Path) -> dict:
        if not self.is_configured:
            raise LinkedInError("LinkedIn is not configured (missing token or person URN).")
        with httpx.Client(timeout=180.0) as client:
            media_urn = self._upload_video(client, video_path)
            return self._create_post(client, caption, media_urn)


linkedin_service = LinkedInService()
