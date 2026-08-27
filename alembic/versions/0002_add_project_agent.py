"""Store the selected agent implementation for each project."""

from alembic import op
import sqlalchemy as sa

revision = "0002_add_project_agent"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("agent", sa.String(40), nullable=False, server_default="codex"))


def downgrade() -> None:
    raise RuntimeError("Downgrade is unsupported; restore the pre-migration database backup.")
