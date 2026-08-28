"""Add agent segments without discarding existing logical chats."""

from alembic import op
import sqlalchemy as sa

revision = "0003_add_logical_chat_segments"
down_revision = "0002_add_project_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_segments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("agent_sessions.id"), nullable=False),
        sa.Column("native_thread_id", sa.String(255), nullable=False, unique=True),
        sa.Column("agent", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120)),
        sa.Column("reasoning", sa.String(80)),
        sa.Column("sandbox", sa.String(40), nullable=False, server_default="workspace_write"),
        sa.Column("status", sa.String(40), nullable=False, server_default="active"),
        sa.Column("handoff_pending", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agent_segments_session_id", "agent_segments", ["session_id"])
    # SQLite cannot add a foreign-key constraint through ALTER TABLE. The ORM
    # still models the relationship; the column remains nullable for old rows.
    op.add_column("turns", sa.Column("segment_id", sa.String(36), nullable=True))
    op.create_index("ix_turns_segment_id", "turns", ["segment_id"])

    # Every pre-existing native session becomes the initial, active segment of
    # its existing user-visible chat. The original session id is reused so no
    # data has to be regenerated or guessed.
    op.execute("""
        INSERT INTO agent_segments
            (id, session_id, native_thread_id, agent, model, reasoning, sandbox, status, handoff_pending)
        SELECT id, id, native_thread_id,
               CASE WHEN native_thread_id LIKE 'opencode:%' THEN 'opencode' ELSE 'codex' END,
               NULL, NULL, 'workspace_write', 'active', 0
        FROM agent_sessions
    """)
    op.execute("UPDATE turns SET segment_id = session_id WHERE segment_id IS NULL")


def downgrade() -> None:
    raise RuntimeError("Downgrade is unsupported; restore the pre-migration database backup.")
