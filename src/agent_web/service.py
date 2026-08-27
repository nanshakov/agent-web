from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from agent_web.codex.base import CodexBackend
from agent_web.db.models import AgentSession, AuditEvent, Project, Turn


class AgentService:
    def __init__(self, session_factory: async_sessionmaker, backend: CodexBackend, roots: tuple[Path, ...]):
        self.session_factory = session_factory
        self.backend = backend
        self.roots = tuple(root.resolve() for root in roots)
        self._active_projects: set[str] = set()

    def validate_project_path(self, raw_path: str) -> Path:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_dir() or not (path / ".git").exists():
            raise ValueError("Project must be an existing Git working tree")
        if not self.roots or not any(path.is_relative_to(root) for root in self.roots):
            raise ValueError("Project is outside configured allowed roots")
        return path

    async def create_project(self, name: str, raw_path: str) -> Project:
        path = self.validate_project_path(raw_path)
        async with self.session_factory() as db:
            project = Project(name=name, path=str(path))
            db.add(project)
            db.add(AuditEvent(kind="project.created", subject_id=project.id))
            await db.commit()
            await db.refresh(project)
            return project

    async def list_projects(self) -> list[Project]:
        async with self.session_factory() as db:
            return list((await db.scalars(select(Project).order_by(Project.name))).all())

    async def update_project_agent_settings(
        self, project_id: str, model: str | None, reasoning: str | None, sandbox: str,
        approval_policy: str,
    ) -> Project:
        async with self.session_factory() as db:
            project = await db.get(Project, project_id)
            if project is None:
                raise LookupError("Project not found")
            project.model = model
            project.reasoning = reasoning
            project.sandbox = sandbox
            project.approval_policy = approval_policy
            db.add(AuditEvent(kind="project.agent_settings_updated", subject_id=project.id))
            await db.commit()
            await db.refresh(project)
            return project

    async def import_existing_codex_sessions(self) -> int:
        """Import only threads whose Git cwd is already inside an allowed root."""
        threads = await self.backend.list_threads()
        imported = 0
        async with self.session_factory() as db:
            for thread in threads:
                cwd = thread.get("cwd")
                native_id = thread.get("id")
                if not cwd or not native_id:
                    continue
                path = Path(cwd).expanduser().resolve()
                if not path.is_dir() or not (path / ".git").exists():
                    continue
                if not any(path.is_relative_to(root) for root in self.roots):
                    continue
                project = await db.scalar(select(Project).where(Project.path == str(path)))
                if project is None:
                    project = Project(name=path.name, path=str(path))
                    db.add(project)
                    await db.flush()
                    db.add(AuditEvent(kind="project.discovered", subject_id=project.id))
                existing = await db.scalar(
                    select(AgentSession).where(AgentSession.native_thread_id == native_id)
                )
                if existing is None:
                    db.add(AgentSession(
                        project_id=project.id,
                        native_thread_id=native_id,
                        title=thread.get("title"),
                    ))
                    imported += 1
            if imported:
                db.add(AuditEvent(kind="codex.sessions_imported", detail=str(imported)))
                await db.commit()
        return imported

    async def create_session(self, project_id: str) -> AgentSession:
        async with self.session_factory() as db:
            project = await db.get(Project, project_id)
            if project is None:
                raise LookupError("Project not found")
            native_id = await self.backend.start_thread(
                Path(project.path), model=project.model, sandbox=project.sandbox,
                reasoning=project.reasoning, approval_policy=project.approval_policy,
            )
            session = AgentSession(project_id=project.id, native_thread_id=native_id)
            db.add(session)
            db.add(AuditEvent(kind="session.created", subject_id=session.id))
            await db.commit()
            await db.refresh(session)
            return session

    async def session_history(self, session_id: str) -> list[dict[str, str]]:
        async with self.session_factory() as db:
            session = await db.get(AgentSession, session_id)
            if session is None:
                raise LookupError("Session not found")
            native_thread_id = session.native_thread_id
        return await self.backend.thread_history(native_thread_id)

    async def create_turn(self, session_id: str, prompt: str, request_id: str) -> Turn:
        async with self.session_factory() as db:
            existing = await db.scalar(select(Turn).where(Turn.client_request_id == request_id))
            if existing:
                return existing
            session = await db.get(AgentSession, session_id)
            if session is None:
                raise LookupError("Session not found")
            project = await db.get(Project, session.project_id)
            if project is None:
                raise LookupError("Project not found")
            if project.id in self._active_projects:
                raise RuntimeError("Project already has an active turn")
            turn = Turn(session_id=session.id, client_request_id=request_id, prompt=prompt, status="running")
            db.add(turn)
            db.add(AuditEvent(kind="turn.started", subject_id=turn.id))
            await db.commit()
            await db.refresh(turn)
        self._active_projects.add(project.id)
        try:
            response = await self.backend.run_turn(
                session.native_thread_id, prompt, sandbox=project.sandbox
            )
            async with self.session_factory() as db:
                stored = await db.get(Turn, turn.id)
                stored.response, stored.status = response, "completed"
                db.add(AuditEvent(kind="turn.completed", subject_id=turn.id))
                await db.commit()
                return stored
        except Exception:
            async with self.session_factory() as db:
                stored = await db.get(Turn, turn.id)
                stored.status = "failed"
                await db.commit()
            raise
        finally:
            self._active_projects.discard(project.id)

    async def run_turn_background(self, *args) -> None:
        await asyncio.create_task(self.create_turn(*args))
