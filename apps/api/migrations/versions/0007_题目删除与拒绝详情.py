"""Retain rejected candidates and hide deleted questions without removing history."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "question_generation_jobs",
        sa.Column("rejected_candidates", sa.JSON(), server_default="[]", nullable=False),
    )
    op.drop_constraint("ck_question_status", "questions", type_="check")
    op.create_check_constraint(
        "ck_question_status",
        "questions",
        "status in ('draft', 'active', 'disabled', 'rejected', 'deleted')",
    )


def downgrade():
    op.execute("UPDATE questions SET status = 'disabled' WHERE status = 'deleted'")
    op.drop_constraint("ck_question_status", "questions", type_="check")
    op.create_check_constraint(
        "ck_question_status",
        "questions",
        "status in ('draft', 'active', 'disabled', 'rejected')",
    )
    op.drop_column("question_generation_jobs", "rejected_candidates")
