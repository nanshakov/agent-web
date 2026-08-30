from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def new_id() -> str:
    return str(uuid4())


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    path: Mapped[str] = mapped_column(String(2048), unique=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reasoning: Mapped[str | None] = mapped_column(String(80), nullable=True)
    agent: Mapped[str] = mapped_column(String(40), default="codex")
    sandbox: Mapped[str] = mapped_column(String(40), default="workspace_write")
    approval_policy: Mapped[str] = mapped_column(String(40), default="ask")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppSetting(Base):
    __tablename__ = "app_settings"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default="global")
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reasoning: Mapped[str | None] = mapped_column(String(80), nullable=True)
    custom_instructions: Mapped[str | None] = mapped_column(Text(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentSession(Base):
    """A user-visible logical chat, potentially spanning several agents."""
    __tablename__ = "agent_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    native_thread_id: Mapped[str] = mapped_column(String(255), unique=True)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    custom_instructions: Mapped[str | None] = mapped_column(Text(), nullable=True)
    archived: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentSegment(Base):
    """One native Codex/OpenCode session within a logical chat."""
    __tablename__ = "agent_segments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id"), index=True)
    native_thread_id: Mapped[str] = mapped_column(String(255), unique=True)
    agent: Mapped[str] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reasoning: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sandbox: Mapped[str] = mapped_column(String(40), default="workspace_write")
    status: Mapped[str] = mapped_column(String(40), default="active")
    handoff_pending: Mapped[bool] = mapped_column(default=False)
    handoff_context: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Turn(Base):
    __tablename__ = "turns"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id"), index=True)
    segment_id: Mapped[str | None] = mapped_column(ForeignKey("agent_segments.id"), nullable=True, index=True)
    client_request_id: Mapped[str] = mapped_column(String(100), unique=True)
    prompt: Mapped[str] = mapped_column(Text())
    agent_prompt: Mapped[str | None] = mapped_column(Text(), nullable=True)
    attachments_json: Mapped[str | None] = mapped_column(Text(), nullable=True)
    agent: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reasoning: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sandbox: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="queued")
    response: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExternalMessage(Base):
    """A message discovered later in an agent's native session history."""
    __tablename__ = "external_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id"), index=True)
    segment_id: Mapped[str] = mapped_column(ForeignKey("agent_segments.id"), index=True)
    position: Mapped[int] = mapped_column()
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(80))
    subject_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
