"""自适应选题与检索讲解

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_study_mode", "study_sessions", type_="check")
    op.create_check_constraint(
        "ck_study_mode",
        "study_sessions",
        "mode in ('diagnostic', 'practice', 'review', 'mock_exam')",
    )
    op.add_column(
        "session_questions",
        sa.Column("selection_reason", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "session_questions",
        sa.Column("priority_score", sa.Numeric(7, 6), nullable=False, server_default="0"),
    )
    op.add_column(
        "answer_records", sa.Column("explanation_data", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("answer_records", "explanation_data")
    op.drop_column("session_questions", "priority_score")
    op.drop_column("session_questions", "selection_reason")
    op.drop_constraint("ck_study_mode", "study_sessions", type_="check")
    op.create_check_constraint(
        "ck_study_mode",
        "study_sessions",
        "mode in ('practice', 'review', 'mock_exam')",
    )
