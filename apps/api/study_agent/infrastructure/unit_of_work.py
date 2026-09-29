from sqlalchemy.ext.asyncio import AsyncSession

from study_agent.domain.ports import (
    AnswerRecordRepository,
    DocumentChunkRepository,
    IngestionJobRepository,
    KnowledgeBaseRepository,
    MasteryRepository,
    MaterialRepository,
    QuestionGenerationJobRepository,
    QuestionRepository,
    ReviewTaskRepository,
    StudySessionRepository,
)
from study_agent.infrastructure.repositories import (
    SqlAlchemyAnswerRecordRepository,
    SqlAlchemyDocumentChunkRepository,
    SqlAlchemyIngestionJobRepository,
    SqlAlchemyKnowledgeBaseRepository,
    SqlAlchemyMasteryRepository,
    SqlAlchemyMaterialRepository,
    SqlAlchemyQuestionGenerationJobRepository,
    SqlAlchemyQuestionRepository,
    SqlAlchemyReviewTaskRepository,
    SqlAlchemyStudySessionRepository,
)


class SqlAlchemyUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.knowledge_bases: KnowledgeBaseRepository = SqlAlchemyKnowledgeBaseRepository(session)
        self.materials: MaterialRepository = SqlAlchemyMaterialRepository(session)
        self.ingestion_jobs: IngestionJobRepository = SqlAlchemyIngestionJobRepository(session)
        self.document_chunks: DocumentChunkRepository = SqlAlchemyDocumentChunkRepository(session)
        self.question_generation_jobs: QuestionGenerationJobRepository = (
            SqlAlchemyQuestionGenerationJobRepository(session)
        )
        self.questions: QuestionRepository = SqlAlchemyQuestionRepository(session)
        self.study_sessions: StudySessionRepository = SqlAlchemyStudySessionRepository(session)
        self.answer_records: AnswerRecordRepository = SqlAlchemyAnswerRecordRepository(session)
        self.mastery: MasteryRepository = SqlAlchemyMasteryRepository(session)
        self.review_tasks: ReviewTaskRepository = SqlAlchemyReviewTaskRepository(session)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
