from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from study_agent.domain.errors import DomainError
from study_agent.domain.models import KnowledgeBase
from study_agent.domain.ports import UnitOfWork


class KnowledgeBaseService:
    async def create(
        self,
        uow: UnitOfWork,
        *,
        name: str,
        description: str | None,
        language: str,
    ) -> KnowledgeBase:
        now = datetime.now(UTC)
        knowledge_base = KnowledgeBase(
            id=uuid4(),
            name=name.strip(),
            description=description.strip() if description else None,
            language=language,
            status="active",
            created_at=now,
            updated_at=now,
        )
        created = await uow.knowledge_bases.add(knowledge_base)
        await uow.commit()
        return created

    async def get(self, uow: UnitOfWork, knowledge_base_id: UUID) -> KnowledgeBase:
        knowledge_base = await uow.knowledge_bases.get(knowledge_base_id)
        if knowledge_base is None or knowledge_base.status == "deleted":
            raise DomainError("KNOWLEDGE_BASE_NOT_FOUND", "知识库不存在", status_code=404)
        return knowledge_base

    async def list(
        self,
        uow: UnitOfWork,
        *,
        page: int,
        page_size: int,
        status: str | None,
        keyword: str | None,
    ) -> tuple[list[KnowledgeBase], int]:
        items, total = await uow.knowledge_bases.list(
            page=page,
            page_size=page_size,
            status=status,
            keyword=keyword.strip() if keyword else None,
        )
        return list(items), total

    async def delete(self, uow: UnitOfWork, knowledge_base_id: UUID) -> None:
        await uow.lock(knowledge_base_id)
        current = await uow.knowledge_bases.get(knowledge_base_id)
        if current is None or current.status == "deleted":
            return
        await uow.knowledge_bases.update(
            replace(current, status="deleted", updated_at=datetime.now(UTC))
        )
        await uow.commit()

    async def update(
        self,
        uow: UnitOfWork,
        knowledge_base_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        language: str | None = None,
        status: str | None = None,
        description_is_set: bool = False,
    ) -> KnowledgeBase:
        await uow.lock(knowledge_base_id)
        current = await self.get(uow, knowledge_base_id)
        updated = replace(
            current,
            name=name.strip() if name is not None else current.name,
            description=(description.strip() if description else None)
            if description_is_set
            else current.description,
            language=language if language is not None else current.language,
            status=status if status is not None else current.status,
            updated_at=datetime.now(UTC),
        )
        result = await uow.knowledge_bases.update(updated)
        await uow.commit()
        return result
