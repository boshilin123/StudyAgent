from fastapi import Request

from study_agent.application.learning_queries import LearningQueries
from study_agent.application.retrieval import LearningMaterialRetrieval
from study_agent.application.tutoring import TutorService
from study_agent.config import get_settings
from study_agent.infrastructure.database import engine, session_factory
from study_agent.infrastructure.tutoring import TutorRepository
from study_agent.ingestion.factory import get_document_index
from study_agent.llm.models import get_chat_model


def get_tutor_service(request: Request) -> TutorService:
    settings = get_settings()
    return TutorService(
        TutorRepository(
            session_factory, getattr(request.app.state, "tutor_lock_engine", None) or engine
        ),
        LearningQueries(session_factory),
        LearningMaterialRetrieval(session_factory, get_document_index),
        settings,
        getattr(request.app.state, "tutor_checkpointer", None),
        lambda: get_chat_model(settings, purpose="tutoring"),
    )
