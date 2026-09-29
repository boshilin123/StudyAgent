from celery import Celery

from study_agent.config import get_settings

settings = get_settings()
celery_app = Celery(
    "study_agent",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["study_agent.ingestion.tasks", "study_agent.question_generation.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)
