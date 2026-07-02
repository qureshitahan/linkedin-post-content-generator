import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# New columns added after the initial schema. create_all() won't ALTER existing
# SQLite tables, so we patch them in for already-created databases.
_ADDED_COLUMNS = {
    "objectives": {"sources_used": "VARCHAR(255)", "run_settings": "TEXT", "principle_id": "INTEGER"},
    "topics": {
        "relevance_score": "FLOAT DEFAULT 0.0",
        "sources_summary": "VARCHAR(255)",
        "linkedin_drafts": "TEXT",
    },
    "search_queries": {"raw_post_count": "INTEGER"},
    "evidence_posts": {"source": "VARCHAR(30) DEFAULT 'x'", "content_type": "VARCHAR(30)"},
}


def _migrate_added_columns():
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {c["name"] for c in inspector.get_columns(table)}
            for col, ddl in columns.items():
                if col not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                    logger.info(f"Migrated: added {table}.{col}")


def init_db():
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_added_columns()
