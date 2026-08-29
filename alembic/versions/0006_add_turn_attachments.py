"""Store attachment metadata and the prompt submitted to the agent."""

from alembic import op
import sqlalchemy as sa

revision = "0006_add_turn_attachments"
down_revision = "0005_store_external_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("turns", sa.Column("agent_prompt", sa.Text(), nullable=True))
    op.add_column("turns", sa.Column("attachments_json", sa.Text(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Downgrade is unsupported; restore the pre-migration database backup.")
