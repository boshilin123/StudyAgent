"""学习会话与复习闭环

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "study_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("planned_question_count", sa.Integer(), nullable=False),
        sa.Column("answered_question_count", sa.Integer(), nullable=False),
        sa.Column("correct_count", sa.Integer(), nullable=False),
        sa.Column("incorrect_count", sa.Integer(), nullable=False),
        sa.Column("total_score", sa.Numeric(8, 2), nullable=False),
        sa.Column("max_total_score", sa.Numeric(8, 2), nullable=False),
        sa.Column("question_types", sa.JSON(), nullable=False),
        sa.Column("difficulty_min", sa.Integer(), nullable=False),
        sa.Column("difficulty_max", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("mode in ('practice', 'review', 'mock_exam')", name="ck_study_mode"),
        sa.CheckConstraint(
            "status in ('active', 'completed', 'abandoned')", name="ck_study_status"
        ),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_study_sessions_kb_started", "study_sessions", ["knowledge_base_id", "started_at"]
    )
    op.create_table(
        "session_questions",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_id"], ["study_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id", "sequence"),
        sa.UniqueConstraint("session_id", "question_id", name="uq_session_question"),
    )
    op.create_table(
        "answer_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_point_id", sa.Uuid(), nullable=False),
        sa.Column("answer", sa.JSON(), nullable=False),
        sa.Column("score", sa.Numeric(6, 2), nullable=False),
        sa.Column("max_score", sa.Numeric(6, 2), nullable=False),
        sa.Column("verdict", sa.String(20), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=False),
        sa.Column("elapsed_seconds", sa.Integer(), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("verdict in ('correct', 'incorrect')", name="ck_answer_verdict"),
        sa.ForeignKeyConstraint(
            ["knowledge_point_id"], ["knowledge_points.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_id"], ["study_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_id", name="uq_answer_submission"),
        sa.UniqueConstraint("session_id", "question_id", name="uq_answer_session_question"),
    )
    op.create_index(
        "ix_answer_records_session_answered", "answer_records", ["session_id", "answered_at"]
    )
    op.create_table(
        "mastery_records",
        sa.Column("knowledge_point_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("mastery_score", sa.Numeric(5, 4), nullable=False),
        sa.Column("answered_count", sa.Integer(), nullable=False),
        sa.Column("correct_count", sa.Integer(), nullable=False),
        sa.Column("recent_accuracy", sa.Numeric(5, 4), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("confidence >= 0 and confidence <= 1", name="ck_mastery_confidence"),
        sa.CheckConstraint(
            "recent_accuracy >= 0 and recent_accuracy <= 1", name="ck_mastery_accuracy"
        ),
        sa.CheckConstraint("mastery_score >= 0 and mastery_score <= 1", name="ck_mastery_score"),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_point_id"], ["knowledge_points.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("knowledge_point_id"),
    )
    op.create_index("ix_mastery_records_kb", "mastery_records", ["knowledge_base_id"])
    op.create_table(
        "review_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_point_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_days", sa.Integer(), nullable=False),
        sa.Column("repetitions", sa.Integer(), nullable=False),
        sa.Column("ease_factor", sa.Numeric(4, 2), nullable=False),
        sa.Column("last_quality", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status in ('pending', 'completed')", name="ck_review_status"),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_point_id"], ["knowledge_points.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("knowledge_point_id", name="uq_review_knowledge_point"),
    )
    op.create_index("ix_review_tasks_due", "review_tasks", ["status", "due_at"])


def downgrade() -> None:
    op.drop_index("ix_review_tasks_due", table_name="review_tasks")
    op.drop_table("review_tasks")
    op.drop_index("ix_mastery_records_kb", table_name="mastery_records")
    op.drop_table("mastery_records")
    op.drop_index("ix_answer_records_session_answered", table_name="answer_records")
    op.drop_table("answer_records")
    op.drop_table("session_questions")
    op.drop_index("ix_study_sessions_kb_started", table_name="study_sessions")
    op.drop_table("study_sessions")
