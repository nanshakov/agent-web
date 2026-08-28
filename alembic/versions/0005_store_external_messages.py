"""Persist messages discovered from native agent sessions."""

from alembic import op
import sqlalchemy as sa

revision = "0005_store_external_messages"
down_revision = "0004_store_handoff_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("agent_sessions.id"), nullable=False),
        sa.Column("segment_id", sa.String(36), sa.ForeignKey("agent_segments.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_external_messages_session_id", "external_messages", ["session_id"])
    op.create_index("ix_external_messages_segment_id", "external_messages", ["segment_id"])


def downgrade() -> None:
    raise RuntimeError("Downgrade is unsupported; restore the pre-migration database backup.")
