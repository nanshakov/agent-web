"""Persist source history for cross-agent handoffs."""

from alembic import op
import sqlalchemy as sa

revision = "0004_store_handoff_context"
down_revision = "0003_add_logical_chat_segments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_segments", sa.Column("handoff_context", sa.Text(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Downgrade is unsupported; restore the pre-migration database backup.")
