from fastapi.testclient import TestClient

from study_agent.infrastructure.readiness import get_readiness_probes
from study_agent.main import app


def test_live() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready() -> None:
    async def up() -> None:
        pass

    app.dependency_overrides[get_readiness_probes] = lambda: {"postgresql": up, "redis": up}
    try:
        with TestClient(app) as client:
            response = client.get("/api/health/ready")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["dependencies"] == {"postgresql": "up", "redis": "up"}


def test_ready_fails_closed_without_leaking_dependency_errors() -> None:
    async def down() -> None:
        raise RuntimeError("redis://secret:password@private")

    app.dependency_overrides[get_readiness_probes] = lambda: {"redis": down}
    try:
        with TestClient(app) as client:
            response = client.get("/api/health/ready")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "dependencies": {"redis": "down"}}
