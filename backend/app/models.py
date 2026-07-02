from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Objective(Base):
    __tablename__ = "objectives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    principle_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("principles.id"), nullable=True
    )
    sources_used: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    run_settings: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    search_queries: Mapped[List["SearchQuery"]] = relationship(
        back_populates="objective", cascade="all, delete-orphan"
    )
    topics: Mapped[List["Topic"]] = relationship(
        back_populates="objective", cascade="all, delete-orphan"
    )
    principle: Mapped[Optional["Principle"]] = relationship(back_populates="objectives")


class Principle(Base):
    __tablename__ = "principles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    documents: Mapped[List["PrincipleDocument"]] = relationship(
        back_populates="principle", cascade="all, delete-orphan"
    )
    objectives: Mapped[List["Objective"]] = relationship(back_populates="principle")


class PrincipleDocument(Base):
    __tablename__ = "principle_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    principle_id: Mapped[int] = mapped_column(ForeignKey("principles.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stored_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    principle: Mapped["Principle"] = relationship(back_populates="documents")


class SearchQuery(Base):
    __tablename__ = "search_queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    objective_id: Mapped[int] = mapped_column(ForeignKey("objectives.id"), nullable=False)
    query_text: Mapped[str] = mapped_column(String(500), nullable=False)
    post_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    raw_post_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    count_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    objective: Mapped["Objective"] = relationship(back_populates="search_queries")


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    objective_id: Mapped[int] = mapped_column(ForeignKey("objectives.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    query_used: Mapped[str] = mapped_column(String(500), nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    volume_score: Mapped[float] = mapped_column(Float, default=0.0)
    freshness_score: Mapped[float] = mapped_column(Float, default=0.0)
    engagement_score: Mapped[float] = mapped_column(Float, default=0.0)
    post_count: Mapped[int] = mapped_column(Integer, default=0)
    sources_summary: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    why_trending: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    specific_event: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    why_matters: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    linkedin_angle: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    linkedin_draft: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    linkedin_drafts: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    objective: Mapped["Objective"] = relationship(back_populates="topics")
    evidence_posts: Mapped[List["EvidencePost"]] = relationship(
        back_populates="topic", cascade="all, delete-orphan"
    )


class EvidencePost(Base):
    __tablename__ = "evidence_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(30), default="x")
    content_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    post_text: Mapped[str] = mapped_column(Text, nullable=False)
    author_name: Mapped[str] = mapped_column(String(255), default="Unknown")
    author_handle: Mapped[str] = mapped_column(String(255), default="unknown")
    post_url: Mapped[str] = mapped_column(String(500), default="")
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    retweets: Mapped[int] = mapped_column(Integer, default=0)
    replies: Mapped[int] = mapped_column(Integer, default=0)
    impressions: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    topic: Mapped["Topic"] = relationship(back_populates="evidence_posts")
