from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.services.image_service import IMAGES_DIR

router = APIRouter(tags=["images"])


@router.get("/api/images/{filename}")
def get_image(filename: str):
    """Serve a generated LinkedIn post image."""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    path = IMAGES_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(path, media_type="image/png")
