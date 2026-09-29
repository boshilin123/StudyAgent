from uuid import UUID

from study_agent.question_generation.tasks import generate_questions


class CeleryQuestionGenerationDispatcher:
    def dispatch(self, *, job_id: UUID, material_id: UUID) -> None:
        generate_questions.delay(str(job_id), str(material_id))
