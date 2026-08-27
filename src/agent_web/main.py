from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from agent_web.codex.base import UnavailableCodexBackend
from agent_web.codex.sdk_backend import SdkCodexBackend
from agent_web.config import Settings
from agent_web.db.database import create_database, migrate_database
from agent_web.service import AgentService
from agent_web.updater import UpdateError, Updater


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    path: str


class TurnInput(BaseModel):
    prompt: str = Field(min_length=1)
    client_request_id: str = Field(min_length=8, max_length=100)


class ProjectAgentSettingsInput(BaseModel):
    model: str | None = Field(default=None, max_length=120)
    reasoning: str | None = Field(default=None, max_length=80)


def error(code: str, message: str, status: int) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def create_app(settings: Settings, backend=None) -> FastAPI:
    engine, session_factory = create_database(settings.database_url)
    backend = backend or SdkCodexBackend()
    service = AgentService(session_factory, backend, settings.allowed_roots)
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        migrate_database(settings.data_dir, settings.database_url)
        app.state.update_status = {"state": "not_configured"}

        async def import_existing_sessions() -> None:
            try:
                await service.import_existing_codex_sessions()
            except Exception:
                # Discovery is a convenience; diagnostics remain available if Codex is offline.
                pass

        async def check_updates() -> None:
            if not settings.update_repository_url:
                return
            app.state.update_status = {"state": "checking"}
            try:
                status = await asyncio.to_thread(Updater(Path(__file__).parents[2], settings).status)
                app.state.update_status = {
                    "state": "available" if status.available else "up_to_date",
                    "current_commit": status.current_commit,
                    "available_commit": status.available_commit,
                    "commits": list(status.commits),
                }
            except UpdateError as error:
                app.state.update_status = {"state": "error", "message": str(error)}
            except Exception:
                app.state.update_status = {"state": "error", "message": "Could not check for updates"}

        import_task = asyncio.create_task(import_existing_sessions())
        update_task = asyncio.create_task(check_updates())
        yield
        import_task.cancel()
        update_task.cancel()
        await engine.dispose()

    app = FastAPI(title="Agent Web", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.service = service
    app.state.settings = settings
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        return templates.TemplateResponse(request, "index.html", {"lan_mode": settings.host == "0.0.0.0"})

    @app.get("/api/v1/health")
    async def health():
        ready, detail = await backend.health()
        return {"status": "ready" if ready else "codex_unavailable", "codex": detail}

    @app.get("/api/v1/capabilities")
    async def capabilities():
        return backend.capabilities.__dict__

    @app.get("/api/v1/codex/status")
    async def codex_status():
        try:
            models = await backend.models()
        except Exception:
            models = []
        return {
            "models": models,
            "usage": {
                "available": False,
                "message": "Remaining limits are not available through the local Codex SDK.",
            },
        }

    @app.get("/api/v1/update")
    async def update_status():
        return app.state.update_status

    @app.get("/api/v1/projects")
    async def projects():
        rows = await service.list_projects()
        return [{"id": p.id, "name": p.name, "path": p.path, "sandbox": p.sandbox,
                 "approval_policy": p.approval_policy, "model": p.model, "reasoning": p.reasoning} for p in rows]

    @app.post("/api/v1/projects", status_code=201)
    async def add_project(payload: ProjectInput):
        try:
            project = await service.create_project(payload.name, payload.path)
        except ValueError as exc:
            raise error("invalid_project", str(exc), 422) from exc
        return {"id": project.id, "name": project.name, "path": project.path}

    @app.put("/api/v1/projects/{project_id}/agent-settings")
    async def update_project_agent_settings(project_id: str, payload: ProjectAgentSettingsInput):
        try:
            models = await backend.models()
            selected = next((item for item in models if item["id"] == payload.model), None)
            if payload.model is not None and selected is None:
                raise ValueError("Selected Codex model is not available")
            if payload.reasoning is not None and selected is not None:
                if payload.reasoning not in selected["reasoning_efforts"]:
                    raise ValueError("Selected reasoning level is not supported by this model")
            project = await service.update_project_agent_settings(
                project_id, payload.model, payload.reasoning
            )
        except LookupError as exc:
            raise error("not_found", str(exc), 404) from exc
        except ValueError as exc:
            raise error("invalid_agent_settings", str(exc), 422) from exc
        return {"id": project.id, "model": project.model, "reasoning": project.reasoning}

    @app.post("/api/v1/projects/{project_id}/sessions", status_code=201)
    async def add_session(project_id: str):
        try:
            session = await service.create_session(project_id)
        except LookupError as exc:
            raise error("not_found", str(exc), 404) from exc
        except Exception as exc:
            raise error("codex_unavailable", str(exc), 503) from exc
        return {"id": session.id, "native_thread_id": session.native_thread_id}

    @app.get("/api/v1/projects/{project_id}/sessions")
    async def sessions(project_id: str):
        from sqlalchemy import select
        from agent_web.db.models import AgentSession

        async with session_factory() as db:
            rows = list((await db.scalars(
                select(AgentSession).where(AgentSession.project_id == project_id, AgentSession.archived.is_(False))
            )).all())
        return [{"id": row.id, "title": row.title, "native_thread_id": row.native_thread_id} for row in rows]

    @app.post("/api/v1/sessions/{session_id}/turns")
    async def add_turn(session_id: str, payload: TurnInput):
        try:
            turn = await service.create_turn(session_id, payload.prompt, payload.client_request_id)
        except LookupError as exc:
            raise error("not_found", str(exc), 404) from exc
        except RuntimeError as exc:
            raise error("project_busy", str(exc), 409) from exc
        except Exception as exc:
            raise error("turn_failed", str(exc), 502) from exc
        return {"id": turn.id, "status": turn.status, "response": turn.response}

    return app
