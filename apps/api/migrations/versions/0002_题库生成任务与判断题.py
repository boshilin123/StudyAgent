"""题库生成任务与判断题

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_question_type", "questions", type_="check")
    op.create_check_constraint(
        "ck_question_type",
        "questions",
        "question_type in ('single_choice', 'fill_blank', 'true_false', 'short_answer')",
    )
    op.create_table(
        "question_generation_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("material_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("target_question_count", sa.Integer(), nullable=False),
        sa.Column("allowed_types", sa.JSON(), nullable=False),
        sa.Column("difficulty_min", sa.Integer(), nullable=False),
        sa.Column("difficulty_max", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(20), nullable=False),
        sa.Column("generated_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("progress >= 0 and progress <= 100", name="ck_question_job_progress"),
        sa.CheckConstraint("target_question_count > 0", name="ck_question_job_target_positive"),
        sa.ForeignKeyConstraint(["material_id"], ["materials.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_question_jobs_material_created",
        "question_generation_jobs",
        ["material_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_question_jobs_material_created", table_name="question_generation_jobs")
    op.drop_table("question_generation_jobs")
    op.drop_constraint("ck_question_type", "questions", type_="check")
    op.create_check_constraint(
        "ck_question_type",
        "questions",
        "question_type in ('single_choice', 'fill_blank', 'short_answer')",
    )
