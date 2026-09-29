from fastapi.testclient import TestClient

from study_agent.main import app


def test_live() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health/ready")
    assert response.status_code == 200
    assert response.json()["dependencies"]["application"] == "up"
