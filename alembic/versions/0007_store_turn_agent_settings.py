"""Store the agent settings used for each turn."""

from alembic import op
import sqlalchemy as sa

revision = "0007_store_turn_agent_settings"
down_revision = "0006_add_turn_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("turns", sa.Column("agent", sa.String(length=40), nullable=True))
    op.add_column("turns", sa.Column("model", sa.String(length=120), nullable=True))
    op.add_column("turns", sa.Column("reasoning", sa.String(length=80), nullable=True))
    op.add_column("turns", sa.Column("sandbox", sa.String(length=40), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Downgrade is unsupported; restore the pre-migration database backup.")
