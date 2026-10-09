import json
from typing import Any, cast

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from study_agent.config import Settings
from study_agent.llm.models import get_chat_model
from study_agent.question_generation.schemas import KnowledgePointBatch, QuestionBatch

# 工作流记录此版本号，区分旧的模型引文出题和新的后端来源绑定。
PROMPT_VERSION = "p3-v2-backend-context"


# 从本组参考原文提取知识点；模型输出内容，来源由后端绑定。
def create_knowledge_point_chain(
    settings: Settings,
) -> Runnable[dict[str, Any], KnowledgePointBatch]:
    parser = PydanticOutputParser(pydantic_object=KnowledgePointBatch)
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "你是职业学习资料分析器。只根据提供的原文片段提取可考查知识点。"
                "canonical_key 应稳定、简短、可用于去重。来源由系统绑定，不要输出片段 ID 或引文。",
            ),
            (
                "human",
                "语言：{language}\n本组出题参考原文：\n{context}\n\n"
                "输出要求：\n{format_instructions}",
            ),
        ]
    ).partial(format_instructions=parser.get_format_instructions())
    model = get_chat_model(settings, purpose="question_generation")
    if settings.llm_structured_output_method == "parser":
        chain = prompt | model | parser
    else:
        chain = prompt | model.with_structured_output(
            KnowledgePointBatch, method=settings.llm_structured_output_method
        )
    return cast(Runnable[dict[str, Any], KnowledgePointBatch], chain)


# 组装提示词、模型和结构化解析器，生成题目而不让模型填写引文或片段 ID。
def create_question_generation_chain(settings: Settings) -> Runnable[dict[str, Any], QuestionBatch]:
    parser = PydanticOutputParser(pydantic_object=QuestionBatch)
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "你是严谨的题库生成器。只能根据给定原文和知识点生成题目。"
                "题型仅允许 single_choice、fill_blank、true_false。"
                "单选题必须有 A-D 四个互异选项；判断题答案只能是‘正确’或‘错误’；"
                "填空题可给多个可接受答案。每道题必须关联给定知识点的 canonical_key。"
                "来源由系统绑定，不要输出片段 ID 或引文；解析应说明答案依据。"
                "材料不足时允许少出题，不要编造或重复题目。",
            ),
            (
                "human",
                "目标题数：{target_count}\n允许题型：{allowed_types}\n"
                "难度：{difficulty_min}-{difficulty_max}\n语言：{language}\n"
                "知识点：{knowledge_points}\n本组出题参考原文：\n{context}\n"
                "已有题干（不要重复）：{existing_stems}\n\n"
                "输出要求：\n{format_instructions}",
            ),
        ]
    ).partial(format_instructions=parser.get_format_instructions(), existing_stems="[]")
    model = get_chat_model(settings, purpose="question_generation")
    if settings.llm_structured_output_method == "parser":
        chain = prompt | model | parser
    else:
        chain = prompt | model.with_structured_output(
            QuestionBatch, method=settings.llm_structured_output_method
        )
    return cast(Runnable[dict[str, Any], QuestionBatch], chain)


# 将本组知识点转换成模型可读的 JSON，限定题目能关联的知识点。
def serialize_knowledge_points(batch: KnowledgePointBatch) -> str:
    return json.dumps([item.model_dump(mode="json") for item in batch.items], ensure_ascii=False)


# Temporary source compatibility during the v1 naming transition.
build_knowledge_point_chain = create_knowledge_point_chain
build_question_chain = create_question_generation_chain
