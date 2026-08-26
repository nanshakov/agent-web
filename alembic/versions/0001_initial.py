"""Initial Agent Web schema."""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("projects", sa.Column("id", sa.String(36), primary_key=True), sa.Column("name", sa.String(200), nullable=False), sa.Column("path", sa.String(2048), nullable=False, unique=True), sa.Column("model", sa.String(120)), sa.Column("reasoning", sa.String(80)), sa.Column("sandbox", sa.String(40), nullable=False), sa.Column("approval_policy", sa.String(40), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_table("agent_sessions", sa.Column("id", sa.String(36), primary_key=True), sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False), sa.Column("native_thread_id", sa.String(255), nullable=False, unique=True), sa.Column("title", sa.String(300)), sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_index("ix_agent_sessions_project_id", "agent_sessions", ["project_id"])
    op.create_table("turns", sa.Column("id", sa.String(36), primary_key=True), sa.Column("session_id", sa.String(36), sa.ForeignKey("agent_sessions.id"), nullable=False), sa.Column("client_request_id", sa.String(100), nullable=False, unique=True), sa.Column("prompt", sa.Text(), nullable=False), sa.Column("status", sa.String(40), nullable=False), sa.Column("response", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_index("ix_turns_session_id", "turns", ["session_id"])
    op.create_table("audit_events", sa.Column("id", sa.String(36), primary_key=True), sa.Column("kind", sa.String(80), nullable=False), sa.Column("subject_id", sa.String(36)), sa.Column("detail", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))


def downgrade() -> None:
    raise RuntimeError("Downgrade is unsupported; restore the pre-migration database backup.")
