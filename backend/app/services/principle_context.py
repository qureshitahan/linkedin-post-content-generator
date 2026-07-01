"""Build ParsedObjective with optional principle document retrieval."""

from sqlalchemy.orm import Session

from app.models import Objective
from app.services.objective_parser import ParsedObjective, objective_parser_service
from app.services.principle_retrieval import principle_retrieval_service


async def build_parsed_objective(
    db: Session,
    objective: Objective,
    *,
    topic_query: str = "",
) -> ParsedObjective:
    principle_name = ""
    principle_background = ""
    principle_id = objective.principle_id

    if principle_id:
        principle = principle_retrieval_service.get_principle(db, principle_id)
        if principle:
            principle_name = principle.name
            principle_background = principle_retrieval_service.principle_summary(db, principle_id)

    parsed = await objective_parser_service.parse(
        objective.text,
        principle_background=principle_background,
        principle_name=principle_name,
    )

    if principle_id:
        query = (topic_query or objective.text).strip()
        parsed.principle_snippets = principle_retrieval_service.retrieve(db, principle_id, query)
        parsed.principle_name = principle_name

    return parsed
