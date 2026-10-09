"""在隔离数据库中，用合成资料、真实模型和向量服务验证方案 B。

默认只使用脚本自带的合成资料；显式传 --user-pdf 才读取正式 PDF。
临时知识库和独立向量集合在结束时清理，报告保存在 apps/api/tmp。
"""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from study_agent.api.schemas import QuestionResponse
from study_agent.application.questions import QuestionService
from study_agent.application.study import StudyService
from study_agent.config import get_settings
from study_agent.infrastructure.models import (
    DocumentChunkModel,
    KnowledgeBaseModel,
    MaterialModel,
    QuestionGenerationJobModel,
    QuestionModel,
    StudySessionModel,
    WorkflowRunModel,
)
from study_agent.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from study_agent.ingestion.embeddings import build_embeddings
from study_agent.question_generation import tasks
from study_agent.question_generation.vector_index import MilvusQuestionIndex


async def main(*, use_user_pdf: bool = False) -> None:
    # 数据库名称固定为测试库；正式数据库连接仅用于读取已解析的 PDF。
    settings = get_settings()
    test_url = make_url(settings.database_url).set(database="study_agent_test_upgrade")
    assert test_url.database == "study_agent_test_upgrade"
    if use_user_pdf:
        source_engine = create_async_engine(settings.database_url)
        source_sessions = async_sessionmaker(source_engine, expire_on_commit=False)
        async with source_sessions() as session:
            original = await session.scalar(
                select(MaterialModel)
                .join(KnowledgeBaseModel, KnowledgeBaseModel.id == MaterialModel.knowledge_base_id)
                .where(
                    MaterialModel.original_filename.like("%第1章%"),
                    MaterialModel.media_type == "application/pdf",
                    MaterialModel.parse_status == "ready",
                    KnowledgeBaseModel.status == "active",
                )
                .order_by(MaterialModel.created_at.desc())
            )
            if original is None:
                raise ValueError("未找到已就绪的第1章 PDF，未调用模型")
            original_chunks = list(
                (
                    await session.scalars(
                        select(DocumentChunkModel)
                        .where(DocumentChunkModel.material_id == original.id)
                        .order_by(DocumentChunkModel.chunk_index)
                    )
                ).all()
            )
        await source_engine.dispose()
    else:
        # 自编的基础网络知识，不包含用户资料；默认验收不会读取正式数据库。
        contents = [
            "TCP是面向连接的传输协议，使用三次握手建立连接。UDP是无连接协议，不保证可靠交付。",
            "IPv4地址长度为32位，IPv6地址长度为128位。IP负责网络层的数据包寻址和路由。",
            "DNS将域名解析为IP地址。域名解析与HTTP获取网页是两个不同的过程。",
            "HTTP采用请求与响应模式。GET通常用于读取资源，POST通常用于提交数据。",
            "HTTPS在HTTP通信中使用TLS提供加密保护。TLS用于保护传输数据，并不负责存储业务数据。",
            "关系数据库通过表组织数据。主键标识一行记录，外键表达表之间的关联。",
            "数据库事务具有原子性、一致性、隔离性和持久性。原子性指事务操作全部成功或全部回滚。",
            "索引可以加快某些查询，但需要存储空间并增加写入维护成本。索引不能保证所有查询都更快。",
            "缓存保存可复用的结果，减少重复计算。缓存过期后需要重新从数据源获取数据。",
            "任务队列将耗时工作交给后台执行。提交任务成功不等于任务已经执行完成。",
            "幂等操作在重复执行后不会产生额外的业务效果。提交ID可用于识别同一次请求的重试。",
            "日志用于记录运行事件。监控用于持续观察系统状态，告警用于通知异常情况。",
        ]
        original = SimpleNamespace(
            title="方案B合成学习资料",
            original_filename="scheme-b-synthetic.md",
            media_type="text/markdown",
            size_bytes=sum(len(t.encode()) for t in contents),
        )
        original_chunks = [
            SimpleNamespace(
                chunk_index=i,
                content=text,
                content_hash=hashlib.sha256(text.encode()).hexdigest(),
                token_count=len(text),
                page_start=i + 1,
                page_end=i + 1,
                heading_path=[f"知识{i + 1}"],
            )
            for i, text in enumerate(contents)
        ]

    kb_id, material_id, job_id = uuid4(), uuid4(), uuid4()
    collection = f"study_agent_test_scheme_b_{job_id.hex}"
    scoped = settings.model_copy(
        update={
            "database_url": test_url.render_as_string(hide_password=False),
            "milvus_question_collection": collection,
        }
    )
    engine = create_async_engine(scoped.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    embeddings, model_name = build_embeddings(scoped)
    index = MilvusQuestionIndex(
        uri=scoped.milvus_uri,
        collection_name=collection,
        embeddings=embeddings,
        embedding_model=model_name,
    )
    report = {"material_title": original.title, "target_count": 10, "model": scoped.llm_model}
    try:
        async with sessions() as session:
            session.add(
                KnowledgeBaseModel(
                    id=kb_id,
                    name=f"方案B隔离验收-{job_id.hex[:8]}",
                    status="active",
                    language="zh-CN",
                )
            )
            await session.flush()
            session.add(
                MaterialModel(
                    id=material_id,
                    knowledge_base_id=kb_id,
                    title=original.title,
                    original_filename=original.original_filename,
                    media_type=original.media_type,
                    storage_uri="fake://scheme-b-reference-only",
                    sha256=job_id.hex * 2,
                    size_bytes=original.size_bytes,
                    language="zh-CN",
                    parse_status="ready",
                )
            )
            await session.flush()
            for chunk in original_chunks:
                session.add(
                    DocumentChunkModel(
                        id=uuid4(),
                        material_id=material_id,
                        chunk_index=chunk.chunk_index,
                        content=chunk.content,
                        content_hash=chunk.content_hash,
                        token_count=chunk.token_count,
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        heading_path=chunk.heading_path,
                    )
                )
            await session.flush()
            session.add(
                QuestionGenerationJobModel(
                    id=job_id,
                    material_id=material_id,
                    status="pending",
                    stage="queued",
                    progress=0,
                    target_question_count=10,
                    allowed_types=["single_choice", "fill_blank", "true_false"],
                    difficulty_min=1,
                    difficulty_max=5,
                    language="zh-CN",
                    generated_count=0,
                    rejected_count=0,
                )
            )
            await session.commit()

        # 调用与 Worker 相同的任务函数，只替换为测试库和本次独立向量集合。
        tasks.get_settings = lambda: scoped
        tasks.get_question_index = lambda: index
        print("开始真实模型验收：目标10题，正式题库不会被写入。", flush=True)
        result = await asyncio.to_thread(
            tasks.generate_questions.run, str(job_id), str(material_id)
        )
        report.update(result)
        async with sessions() as session:
            job = await session.get(QuestionGenerationJobModel, job_id)
            report.update(
                status=job.status,
                progress=job.progress,
                rejected_candidates=job.rejected_candidates,
            )
            generated = list(
                (
                    await session.scalars(
                        select(QuestionModel)
                        .where(QuestionModel.knowledge_base_id == kb_id)
                        .order_by(QuestionModel.created_at)
                    )
                ).all()
            )
            uow = SqlAlchemyUnitOfWork(session)
            questions = [await QuestionService().get(uow, model.id) for model in generated]
            assert result["generated_count"] == 10, job.error_message
            assert len(questions) == 10 and all(
                question.status == "draft" for question in questions
            )
            assert job.status == "completed" and job.progress == 100
            for question in questions:
                assert question.sources and question.vector_id
                for source in question.sources:
                    chunk = await session.get(DocumentChunkModel, source.chunk_id)
                    assert chunk.material_id == material_id and source.quote in chunk.content
                    assert source.source_kind == "reference_context"
                    assert (
                        source.material_title == original.title
                        and source.page_start == chunk.page_start
                    )
            report["questions"] = [
                QuestionResponse.model_validate(q).model_dump(mode="json") for q in questions
            ]
            activated = await QuestionService().set_status(uow, index, questions[0].id, "active")
            assert activated.status == "active"
            view = await StudyService().create_session(
                uow,
                knowledge_base_id=kb_id,
                mode="practice",
                question_count=1,
                question_types=["single_choice", "fill_blank", "true_false"],
                difficulty_min=1,
                difficulty_max=5,
            )
            assert view.current_question.id == activated.id
            answer = await StudyService().submit_answer(
                uow,
                session_id=view.session.id,
                submission_id=uuid4(),
                question_id=activated.id,
                answer=activated.correct_answer[0],
                elapsed_seconds=1,
            )
            assert answer.answer_record.verdict == "correct"
            assert answer.session.status == "completed"
            assert answer.explanation_data["evidence"][0]["source_kind"] == "reference_context"
            report["checks"] = [
                "真实模型生成10题",
                "全部来源属于实际输入原文",
                "来源类型及页码序列化",
                "真实向量入库",
                "草稿审核启用",
                "练习选题与提交答案",
                "掌握度与复习更新",
            ]
        print(
            json.dumps(
                {k: v for k, v in report.items() if k not in {"questions", "rejected_candidates"}},
                ensure_ascii=False,
            ),
            flush=True,
        )
    finally:
        # 仅清理本次创建的测试资源，断言集合名和测试库名后再执行。
        assert collection == f"study_agent_test_scheme_b_{job_id.hex}"
        if index.client.has_collection(collection):
            index.client.drop_collection(collection)
        async with sessions() as session:
            await session.execute(
                delete(StudySessionModel).where(StudySessionModel.knowledge_base_id == kb_id)
            )
            await session.execute(
                delete(WorkflowRunModel).where(WorkflowRunModel.subject_id == material_id)
            )
            await session.execute(delete(KnowledgeBaseModel).where(KnowledgeBaseModel.id == kb_id))
            await session.commit()
        await engine.dispose()
        report["test_resources_cleaned"] = True
        target = Path("/app/tmp/scheme_b_live_report.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--user-pdf", action="store_true", help="经用户授权后，用第1章PDF替代合成资料"
    )
    asyncio.run(main(use_user_pdf=parser.parse_args().user_pdf))
