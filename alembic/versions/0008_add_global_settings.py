"""Add host-wide Codex defaults and per-chat instruction snapshots."""

from alembic import op
import sqlalchemy as sa

revision = "0008_add_global_settings"
down_revision = "0007_store_turn_agent_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("model", sa.String(120), nullable=True),
        sa.Column("reasoning", sa.String(80), nullable=True),
        sa.Column("custom_instructions", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.add_column("agent_sessions", sa.Column("custom_instructions", sa.Text(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Downgrade is unsupported; restore the pre-migration database backup.")
