from typing import Annotated, Any

from langchain.agents import AgentState


def merge_evidence(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {**left, **right}


def merge_flags(left: list[str], right: list[str]) -> list[str]:
    return sorted(set(left) | set(right))


class TutorState(AgentState):
    turn_id: str
    evidence: Annotated[dict[str, Any], merge_evidence]
    evidence_flags: Annotated[list[str], merge_flags]
