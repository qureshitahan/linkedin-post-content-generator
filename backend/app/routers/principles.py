import logging
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Principle, PrincipleDocument
from app.schemas import (
    PrincipleCreate,
    PrincipleDocumentOut,
    PrincipleOut,
    PrincipleUpdate,
)
from app.services.principle_retrieval import (
    extract_text_from_bytes,
    principle_retrieval_service,
)

router = APIRouter(prefix="/api/principles", tags=["principles"])
logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB


def _principle_out(principle: Principle) -> PrincipleOut:
    return PrincipleOut(
        id=principle.id,
        name=principle.name,
        description=principle.description,
        created_at=principle.created_at,
        updated_at=principle.updated_at,
        documents=[
            PrincipleDocumentOut(
                id=d.id,
                filename=d.filename,
                created_at=d.created_at,
                char_count=len(d.content_text or ""),
            )
            for d in principle.documents
        ],
    )


@router.get("", response_model=List[PrincipleOut])
def list_principles(db: Session = Depends(get_db)):
    principles = (
        db.query(Principle)
        .order_by(Principle.updated_at.desc())
        .all()
    )
    return [_principle_out(p) for p in principles]


@router.post("", response_model=PrincipleOut, status_code=201)
def create_principle(payload: PrincipleCreate, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Principle name is required")
    principle = Principle(name=name, description=(payload.description or "").strip() or None)
    db.add(principle)
    db.commit()
    db.refresh(principle)
    return _principle_out(principle)


@router.get("/{principle_id}", response_model=PrincipleOut)
def get_principle(principle_id: int, db: Session = Depends(get_db)):
    principle = db.query(Principle).filter(Principle.id == principle_id).first()
    if not principle:
        raise HTTPException(status_code=404, detail="Principle not found")
    return _principle_out(principle)


@router.patch("/{principle_id}", response_model=PrincipleOut)
def update_principle(
    principle_id: int,
    payload: PrincipleUpdate,
    db: Session = Depends(get_db),
):
    principle = db.query(Principle).filter(Principle.id == principle_id).first()
    if not principle:
        raise HTTPException(status_code=404, detail="Principle not found")
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Principle name cannot be empty")
        principle.name = name
    if payload.description is not None:
        principle.description = payload.description.strip() or None
    db.commit()
    db.refresh(principle)
    return _principle_out(principle)


@router.delete("/{principle_id}")
def delete_principle(principle_id: int, db: Session = Depends(get_db)):
    principle = db.query(Principle).filter(Principle.id == principle_id).first()
    if not principle:
        raise HTTPException(status_code=404, detail="Principle not found")
    for doc in principle.documents:
        principle_retrieval_service.delete_file(doc.stored_path)
    db.delete(principle)
    db.commit()
    return {"deleted": principle_id}


@router.post("/{principle_id}/documents", response_model=PrincipleDocumentOut, status_code=201)
async def upload_document(
    principle_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    principle = db.query(Principle).filter(Principle.id == principle_id).first()
    if not principle:
        raise HTTPException(status_code=404, detail="Principle not found")

    filename = file.filename or "document.txt"
    content = await file.read()
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 5 MB)")
    if not content:
        raise HTTPException(status_code=400, detail="File is empty")

    try:
        text = extract_text_from_bytes(filename, content)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not text.strip():
        raise HTTPException(status_code=400, detail="No readable text found in file")

    stored_path = principle_retrieval_service.save_uploaded_file(principle_id, filename, content)
    doc = PrincipleDocument(
        principle_id=principle_id,
        filename=filename,
        content_text=text,
        stored_path=str(stored_path),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return PrincipleDocumentOut(
        id=doc.id,
        filename=doc.filename,
        created_at=doc.created_at,
        char_count=len(doc.content_text),
    )


@router.delete("/{principle_id}/documents/{document_id}")
def delete_document(
    principle_id: int,
    document_id: int,
    db: Session = Depends(get_db),
):
    doc = (
        db.query(PrincipleDocument)
        .filter(
            PrincipleDocument.id == document_id,
            PrincipleDocument.principle_id == principle_id,
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    principle_retrieval_service.delete_file(doc.stored_path)
    db.delete(doc)
    db.commit()
    return {"deleted": document_id}
