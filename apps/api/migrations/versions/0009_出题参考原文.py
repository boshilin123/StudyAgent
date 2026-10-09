"""Distinguish backend-bound generation context from legacy exact quotations."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "question_sources",
        sa.Column("source_kind", sa.String(30), nullable=False, server_default="quote"),
    )
    op.create_check_constraint(
        "ck_question_source_kind",
        "question_sources",
        "source_kind in ('quote', 'reference_context')",
    )


def downgrade():
    op.drop_constraint("ck_question_source_kind", "question_sources", type_="check")
    op.drop_column("question_sources", "source_kind")
