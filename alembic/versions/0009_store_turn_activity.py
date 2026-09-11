"""Persist compact tool activity for mobile reconnects."""
from alembic import op
import sqlalchemy as sa

revision = "0009_store_turn_activity"
down_revision = "0008_add_global_settings"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("turns", sa.Column("activity_json", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("turns", "activity_json")
