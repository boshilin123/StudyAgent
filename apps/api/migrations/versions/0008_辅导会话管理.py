"""Conversation titles and deletion tombstones preserve learning and audit records."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tutor_conversations", sa.Column("title", sa.String(100)))
    op.drop_constraint("ck_tutor_conversation_status", "tutor_conversations", type_="check")
    op.create_check_constraint(
        "ck_tutor_conversation_status",
        "tutor_conversations",
        "status in ('active', 'archived', 'deleted')",
    )


def downgrade():
    op.execute("UPDATE tutor_conversations SET status = 'archived' WHERE status = 'deleted'")
    op.drop_constraint("ck_tutor_conversation_status", "tutor_conversations", type_="check")
    op.create_check_constraint(
        "ck_tutor_conversation_status", "tutor_conversations", "status in ('active', 'archived')"
    )
    op.drop_column("tutor_conversations", "title")
