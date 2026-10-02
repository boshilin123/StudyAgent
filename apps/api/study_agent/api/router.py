from fastapi import APIRouter

from study_agent.api.routes import health, knowledge_bases, materials, questions, study, tutoring

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(knowledge_bases.router, prefix="/knowledge-bases", tags=["知识库"])
api_router.include_router(materials.knowledge_base_router, prefix="/knowledge-bases", tags=["资料"])
api_router.include_router(materials.material_router, prefix="/materials", tags=["资料"])
api_router.include_router(materials.job_router, prefix="/ingestion-jobs", tags=["资料处理任务"])
api_router.include_router(questions.material_router, prefix="/materials", tags=["题库生成"])
api_router.include_router(
    questions.job_router, prefix="/question-generation-jobs", tags=["题库生成"]
)
api_router.include_router(questions.router, prefix="/questions", tags=["题库"])
api_router.include_router(study.router, prefix="/study", tags=["学习"])
api_router.include_router(study.mastery_router, prefix="/mastery", tags=["掌握度"])
api_router.include_router(study.review_router, prefix="/reviews", tags=["复习"])
api_router.include_router(tutoring.router, tags=["学习辅导"])
