from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from study_agent.api.tutoring_dependencies import get_tutor_service
from study_agent.api.tutoring_schemas import (
    CreateTutorConversation,
    SubmitTutorMessage,
    TutorConversationResponse,
    TutorMessageResponse,
)
from study_agent.application.tutoring import TutorService

router = APIRouter(prefix="/tutor", tags=["tutor"])
TutorDependency = Annotated[TutorService, Depends(get_tutor_service)]


@router.post("/conversations", status_code=201, response_model=TutorConversationResponse)
async def create_conversation(
    payload: CreateTutorConversation, service: TutorDependency
) -> TutorConversationResponse:
    return TutorConversationResponse.model_validate(await service.create(payload))


@router.get("/conversations")
async def list_conversations(
    service: TutorDependency,
    knowledge_base_id: UUID | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> dict[str, Any]:
    items, total = await service.repository.list_conversations(knowledge_base_id, page, page_size)
    return {
        "items": [TutorConversationResponse.model_validate(item) for item in items],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/conversations/{conversation_id}")
async def conversation_detail(
    conversation_id: UUID,
    service: TutorDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    conversation, messages, total = await service.detail(conversation_id, page, page_size)
    return {
        "conversation": TutorConversationResponse.model_validate(conversation),
        "messages": [TutorMessageResponse.model_validate(message) for message in messages],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.post("/conversations/{conversation_id}/messages")
async def submit_message(
    conversation_id: UUID, payload: SubmitTutorMessage, service: TutorDependency, response: Response
) -> dict[str, Any]:
    result = await service.submit(conversation_id, payload)
    if result["status"] in {"pending", "running"}:
        response.status_code = 202
        response.headers["Location"] = (
            f"/api/tutor/conversations/{conversation_id}/turns/{result['turn_id']}"
        )
    return result


@router.get("/conversations/{conversation_id}/turns/{turn_id}")
async def turn_status(
    conversation_id: UUID, turn_id: UUID, service: TutorDependency
) -> dict[str, Any]:
    return await service.turn_status(conversation_id, turn_id)


@router.post("/conversations/{conversation_id}/archive", response_model=TutorConversationResponse)
async def archive_conversation(
    conversation_id: UUID, service: TutorDependency
) -> TutorConversationResponse:
    return TutorConversationResponse.model_validate(await service.archive(conversation_id))
