"""Hide deleted libraries while retaining learning facts and tutor references."""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_kb_status", "knowledge_bases", type_="check")
    op.create_check_constraint(
        "ck_kb_status", "knowledge_bases", "status in ('active', 'archived', 'deleted')"
    )


def downgrade():
    op.execute("UPDATE knowledge_bases SET status = 'archived' WHERE status = 'deleted'")
    op.drop_constraint("ck_kb_status", "knowledge_bases", type_="check")
    op.create_check_constraint("ck_kb_status", "knowledge_bases", "status in ('active', 'archived')")
