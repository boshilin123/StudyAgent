"""Read-only tutoring conversations, idempotent turns and accepted responses."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tutor_conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("scope_key", sa.String(50), nullable=False),
        sa.Column(
            "knowledge_base_id",
            sa.Uuid(),
            sa.ForeignKey("knowledge_bases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "study_session_id", sa.Uuid(), sa.ForeignKey("study_sessions.id", ondelete="RESTRICT")
        ),
        sa.Column(
            "answered_question_id", sa.Uuid(), sa.ForeignKey("questions.id", ondelete="RESTRICT")
        ),
        sa.Column("graph_thread_id", sa.String(80), nullable=False, unique=True),
        sa.Column("last_committed_checkpoint_id", sa.String(100)),
        sa.Column("graph_version", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status in ('active','archived')", name="ck_tutor_conversation_status"),
    )
    op.create_table(
        "tutor_turns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("tutor_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_message_id", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("response", sa.JSON()),
        sa.Column("usage", sa.JSON()),
        sa.Column("trace", sa.JSON()),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_message", sa.Text()),
        sa.Column("model", sa.String(100)),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("conversation_id", "client_message_id", name="uq_tutor_client_message"),
        sa.CheckConstraint(
            "status in ('pending','running','completed','failed','cancelled')",
            name="ck_tutor_turn_status",
        ),
    )
    op.create_index("ix_tutor_turns_conversation_id", "tutor_turns", ["conversation_id"])
    op.create_table(
        "tutor_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("tutor_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "turn_id",
            sa.Uuid(),
            sa.ForeignKey("tutor_turns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("conversation_id", "sequence", name="uq_tutor_message_sequence"),
        sa.CheckConstraint("role in ('user','assistant')", name="ck_tutor_message_role"),
    )
    op.create_index("ix_tutor_messages_conversation_id", "tutor_messages", ["conversation_id"])


def downgrade():
    op.drop_table("tutor_messages")
    op.drop_table("tutor_turns")
    op.drop_table("tutor_conversations")
