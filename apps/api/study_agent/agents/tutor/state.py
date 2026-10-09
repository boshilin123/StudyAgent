from typing import Annotated, Any

from langchain.agents import AgentState


# 合并工具收集的原文证据，让多次工具调用的来源可以一起保留。
def merge_evidence(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {**left, **right}


def merge_flags(left: list[str], right: list[str]) -> list[str]:
    return sorted(set(left) | set(right))


# 保存辅导执行中的消息、证据和读取标记，供图节点及检查点使用。
class TutorState(AgentState):
    turn_id: str
    evidence: Annotated[dict[str, Any], merge_evidence]
    evidence_flags: Annotated[list[str], merge_flags]
