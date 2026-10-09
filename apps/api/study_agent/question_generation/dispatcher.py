from uuid import UUID

from study_agent.question_generation.tasks import generate_questions


# 提交后台出题任务，接口立即返回任务 ID 供前端查询进度。
class CeleryQuestionGenerationDispatcher:
    def dispatch(self, *, job_id: UUID, material_id: UUID) -> None:
        generate_questions.delay(str(job_id), str(material_id))
