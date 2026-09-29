from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from study_agent.api.dependencies import (
    get_ingestion_dispatcher,
    get_object_storage,
    get_uow,
    get_vector_index,
)
from study_agent.main import app
from tests.fakes import (
    FakeDocumentIndex,
    FakeIngestionDispatcher,
    FakeObjectStorage,
    FakeUnitOfWork,
)


@pytest.fixture
def api_context() -> Iterator[tuple[TestClient, FakeUnitOfWork, FakeObjectStorage]]:
    uow = FakeUnitOfWork()
    storage = FakeObjectStorage()
    dispatcher = FakeIngestionDispatcher()
    document_index = FakeDocumentIndex()

    async def override_uow():  # type: ignore[no-untyped-def]
        yield uow

    def override_storage() -> FakeObjectStorage:
        return storage

    app.dependency_overrides[get_uow] = override_uow
    app.dependency_overrides[get_object_storage] = override_storage
    app.dependency_overrides[get_ingestion_dispatcher] = lambda: dispatcher
    app.dependency_overrides[get_vector_index] = lambda: document_index
    with TestClient(app) as client:
        yield client, uow, storage
    app.dependency_overrides.clear()


def test_knowledge_base_crud(
    api_context: tuple[TestClient, FakeUnitOfWork, FakeObjectStorage],
) -> None:
    client, _, _ = api_context
    create_response = client.post(
        "/api/knowledge-bases",
        json={"name": "系统架构设计师", "description": "备考资料", "language": "zh-CN"},
    )
    assert create_response.status_code == 201
    knowledge_base_id = create_response.json()["id"]

    list_response = client.get("/api/knowledge-bases", params={"keyword": "架构"})
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    detail_response = client.get(f"/api/knowledge-bases/{knowledge_base_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["name"] == "系统架构设计师"

    update_response = client.patch(
        f"/api/knowledge-bases/{knowledge_base_id}",
        json={"description": None, "status": "archived"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["description"] is None
    assert update_response.json()["status"] == "archived"


def test_knowledge_base_chinese_text_round_trip(
    api_context: tuple[TestClient, FakeUnitOfWork, FakeObjectStorage],
) -> None:
    client, _, _ = api_context
    name = "个人学习资料库"
    description = "Markdown 资料解析、向量检索与题库生成"
    response = client.post(
        "/api/knowledge-bases",
        json={"name": name, "description": description, "language": "zh-CN"},
    )
    assert response.status_code == 201
    assert response.json()["name"] == name
    assert response.json()["description"] == description
    assert b"?" not in response.content


def test_material_upload_duplicate_query_and_delete(
    api_context: tuple[TestClient, FakeUnitOfWork, FakeObjectStorage],
) -> None:
    client, _, storage = api_context
    knowledge_base = client.post(
        "/api/knowledge-bases", json={"name": "计算机网络"}
    ).json()
    knowledge_base_id = knowledge_base["id"]
    files = {"file": ("notes.md", b"# TCP\nThree-way handshake", "text/markdown")}

    upload_response = client.post(
        f"/api/knowledge-bases/{knowledge_base_id}/materials",
        files=files,
        data={"title": "TCP 笔记"},
    )
    assert upload_response.status_code == 202
    body = upload_response.json()
    material_id = body["material"]["id"]
    job_id = body["job"]["id"]
    assert body["material"]["parse_status"] == "pending"
    assert len(storage.objects) == 1

    duplicate_response = client.post(
        f"/api/knowledge-bases/{knowledge_base_id}/materials", files=files
    )
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["error"]["code"] == "DUPLICATE_MATERIAL"

    list_response = client.get(f"/api/knowledge-bases/{knowledge_base_id}/materials")
    assert list_response.json()["total"] == 1
    assert client.get(f"/api/materials/{material_id}").status_code == 200
    assert client.get(f"/api/ingestion-jobs/{job_id}").status_code == 200

    delete_response = client.delete(f"/api/materials/{material_id}")
    assert delete_response.status_code == 204
    assert storage.objects == {}


def test_material_can_be_reprocessed(
    api_context: tuple[TestClient, FakeUnitOfWork, FakeObjectStorage],
) -> None:
    client, _, _ = api_context
    knowledge_base_id = client.post(
        "/api/knowledge-bases", json={"name": "重新索引测试"}
    ).json()["id"]
    upload = client.post(
        f"/api/knowledge-bases/{knowledge_base_id}/materials",
        files={"file": ("notes.md", b"# TCP\nThree-way handshake", "text/markdown")},
    ).json()

    response = client.post(f"/api/materials/{upload['material']['id']}/reprocess")

    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert response.json()["stage"] == "reprocessing"
    assert response.json()["generation_config"] == {"reason": "manual_reprocess"}


def test_upload_rejects_unsupported_file(
    api_context: tuple[TestClient, FakeUnitOfWork, FakeObjectStorage],
) -> None:
    client, _, _ = api_context
    knowledge_base_id = client.post(
        "/api/knowledge-bases", json={"name": "测试"}
    ).json()["id"]
    response = client.post(
        f"/api/knowledge-bases/{knowledge_base_id}/materials",
        files={"file": ("malware.exe", b"invalid", "application/octet-stream")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert response.headers["X-Request-ID"]


def test_upload_rejects_mismatched_media_type(
    api_context: tuple[TestClient, FakeUnitOfWork, FakeObjectStorage],
) -> None:
    client, _, _ = api_context
    knowledge_base_id = client.post(
        "/api/knowledge-bases", json={"name": "MIME 校验"}
    ).json()["id"]
    response = client.post(
        f"/api/knowledge-bases/{knowledge_base_id}/materials",
        files={"file": ("notes.pdf", b"not a real pdf", "text/plain")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_MEDIA_TYPE"
