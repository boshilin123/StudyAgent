from celery import Celery

from study_agent.config import get_settings

settings = get_settings()
# Redis 负责传递任务和保存结果，实际解析、出题由独立 Worker 执行。
celery_app = Celery(
    "study_agent",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["study_agent.ingestion.tasks", "study_agent.question_generation.tasks"],
)
# 只接受 JSON 任务消息，并统一使用 UTC，避免机器时区影响任务时间。
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)
