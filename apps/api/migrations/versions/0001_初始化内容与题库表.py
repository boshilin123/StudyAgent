"""初始化内容与题库表

Revision ID: 0001
Revises:
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("language", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status in ('active', 'archived')", name="ck_kb_status"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_type", sa.String(30), nullable=False),
        sa.Column("subject_type", sa.String(30), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("prompt_version", sa.String(50), nullable=True),
        sa.Column("input_summary", sa.JSON(), nullable=False),
        sa.Column("output_summary", sa.JSON(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "materials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("language", sa.String(20), nullable=False),
        sa.Column("parse_status", sa.String(20), nullable=False),
        sa.Column("parser_version", sa.String(50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_material_size_positive"),
        sa.CheckConstraint(
            "parse_status in ('pending', 'parsing', 'ready', 'partial', 'failed')",
            name="ck_material_parse_status",
        ),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("knowledge_base_id", "sha256", name="uq_material_kb_sha256"),
    )
    op.create_index(
        "ix_materials_knowledge_base_created",
        "materials",
        ["knowledge_base_id", "created_at"],
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("material_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("heading_path", sa.JSON(), nullable=False),
        sa.Column("parent_chunk_id", sa.Uuid(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("vector_id", sa.String(100), nullable=True),
        sa.Column("embedding_model", sa.String(100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["material_id"], ["materials.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_chunk_id"], ["document_chunks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("material_id", "chunk_index", name="uq_chunk_material_index"),
    )
    op.create_index("ix_document_chunks_material_id", "document_chunks", ["material_id"])
    op.create_index("ix_chunks_content_hash", "document_chunks", ["content_hash"])
    op.create_index("ix_chunks_vector_id", "document_chunks", ["vector_id"])

    op.create_table(
        "knowledge_points",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("canonical_key", sa.String(300), nullable=False),
        sa.Column("importance", sa.Numeric(4, 3), nullable=False),
        sa.Column("difficulty", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("importance >= 0 and importance <= 1", name="ck_kp_importance"),
        sa.CheckConstraint("difficulty >= 1 and difficulty <= 5", name="ck_kp_difficulty"),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("knowledge_base_id", "canonical_key", name="uq_kp_kb_canonical"),
    )
    op.create_index(
        "ix_knowledge_points_knowledge_base_id", "knowledge_points", ["knowledge_base_id"]
    )

    op.create_table(
        "knowledge_point_sources",
        sa.Column("knowledge_point_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("relevance", sa.Numeric(4, 3), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["knowledge_point_id"], ["knowledge_points.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("knowledge_point_id", "chunk_id"),
    )

    op.create_table(
        "questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_point_id", sa.Uuid(), nullable=False),
        sa.Column("question_type", sa.String(30), nullable=False),
        sa.Column("stem", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=True),
        sa.Column("correct_answer", sa.JSON(), nullable=False),
        sa.Column("scoring_points", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.Integer(), nullable=False),
        sa.Column("max_score", sa.Numeric(6, 2), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("generation_run_id", sa.Uuid(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("vector_id", sa.String(100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "question_type in ('single_choice', 'fill_blank', 'short_answer')",
            name="ck_question_type",
        ),
        sa.CheckConstraint("difficulty >= 1 and difficulty <= 5", name="ck_question_difficulty"),
        sa.CheckConstraint("max_score > 0", name="ck_question_max_score"),
        sa.CheckConstraint(
            "status in ('draft', 'active', 'disabled', 'rejected')",
            name="ck_question_status",
        ),
        sa.ForeignKeyConstraint(["generation_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["knowledge_point_id"], ["knowledge_points.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("knowledge_base_id", "content_hash", name="uq_question_kb_hash"),
    )
    op.create_index(
        "ix_questions_kb_kp_status_difficulty",
        "questions",
        ["knowledge_base_id", "knowledge_point_id", "status", "difficulty"],
    )

    op.create_table(
        "question_sources",
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("question_id", "chunk_id"),
    )

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("material_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(30), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("generation_config", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("progress >= 0 and progress <= 100", name="ck_job_progress"),
        sa.ForeignKeyConstraint(["material_id"], ["materials.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_material_created", "ingestion_jobs", ["material_id", "created_at"])

    op.create_table(
        "agent_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("node_name", sa.String(100), nullable=False),
        sa.Column("tool_name", sa.String(100), nullable=True),
        sa.Column("input_summary", sa.JSON(), nullable=False),
        sa.Column("output_summary", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_step_sequence"),
    )


def downgrade() -> None:
    op.drop_table("agent_steps")
    op.drop_index("ix_jobs_material_created", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    op.drop_table("question_sources")
    op.drop_index("ix_questions_kb_kp_status_difficulty", table_name="questions")
    op.drop_table("questions")
    op.drop_table("knowledge_point_sources")
    op.drop_index("ix_knowledge_points_knowledge_base_id", table_name="knowledge_points")
    op.drop_table("knowledge_points")
    op.drop_index("ix_chunks_vector_id", table_name="document_chunks")
    op.drop_index("ix_chunks_content_hash", table_name="document_chunks")
    op.drop_index("ix_document_chunks_material_id", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("ix_materials_knowledge_base_created", table_name="materials")
    op.drop_table("materials")
    op.drop_table("agent_runs")
    op.drop_table("knowledge_bases")
