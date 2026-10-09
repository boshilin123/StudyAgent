from uuid import UUID

from celery import chain

from study_agent.config import get_settings
from study_agent.ingestion.tasks import finish_ingestion, index_material, parse_material


# 把资料处理步骤串成 Celery 任务链，让上传接口不用等待解析完成。
class CeleryIngestionDispatcher:
    def dispatch(self, *, job_id: UUID, material_id: UUID) -> None:
        workflow = chain(
            parse_material.s(str(job_id), str(material_id)),
            index_material.s(),
            finish_ingestion.s(),
        )
        if get_settings().ingestion_eager:
            workflow.apply()
        else:
            workflow.apply_async()
