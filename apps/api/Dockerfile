FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml requirements.lock ./
COPY study_agent ./study_agent
COPY migrations ./migrations
COPY alembic.ini ./

RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps .

EXPOSE 8000
CMD ["uvicorn", "study_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
