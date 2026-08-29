from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from agent_web.cline import ClineHistory
from agent_web.codex.base import UnavailableCodexBackend
from agent_web.codex.sdk_backend import SdkCodexBackend
from agent_web.opencode_acp import OpenCodeAcpBackend
from agent_web.config import Settings
from agent_web.db.database import create_database, migrate_database
from agent_web.markdown import render_markdown
from agent_web.service import AgentService, chat_title
from agent_web.updater import UpdateError, Updater


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    path: str


class TurnInput(BaseModel):
    prompt: str = ""
    client_request_id: str = Field(min_length=8, max_length=100)


class ProjectAgentSettingsInput(BaseModel):
    agent: str = "codex"
    model: str | None = Field(default=None, max_length=120)
    reasoning: str | None = Field(default=None, max_length=80)
    sandbox: str = "workspace_write"
    approval_policy: str = "auto"


class SessionSwitchInput(ProjectAgentSettingsInput):
    pass


def error(code: str, message: str, status: int) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def create_app(settings: Settings, backend=None) -> FastAPI:
    engine, session_factory = create_database(settings.database_url)
    backends = backend if isinstance(backend, dict) else {"codex": backend} if backend is not None else {
        "codex": SdkCodexBackend(), "opencode": OpenCodeAcpBackend(),
    }
    service = AgentService(session_factory, backends, settings.allowed_roots)
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        migrate_database(settings.data_dir, settings.database_url)
        await service.recover_interrupted_turns()
        app.state.update_status = {"state": "not_configured"}

        async def import_existing_sessions() -> None:
            try:
                await service.import_existing_codex_sessions()
                await service.import_cline_sessions(ClineHistory())
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
        statuses = {name: await item.health() for name, item in backends.items()}
        return {"status": "ready" if any(ready for ready, _ in statuses.values()) else "agent_unavailable",
                "agents": {name: {"ready": ready, "detail": detail} for name, (ready, detail) in statuses.items()}}

    @app.get("/api/v1/capabilities")
    async def capabilities():
        return {name: item.capabilities.__dict__ for name, item in backends.items()}

    @app.get("/api/v1/codex/status")
    async def codex_status():
        try:
            models = await backends["codex"].models()
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
                 "approval_policy": p.approval_policy, "model": p.model, "reasoning": p.reasoning,
                 "agent": p.agent} for p in rows]

    @app.get("/api/v1/agents")
    async def agents():
        result = {}
        for name, item in backends.items():
            ready, detail = await item.health()
            result[name] = {"ready": ready, "detail": detail, "models": await item.models() if ready else []}
        return result

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
            if payload.sandbox not in {"read_only", "workspace_write"}:
                raise ValueError("Only read-only or workspace-write access is available")
            if payload.approval_policy != "auto":
                raise ValueError("Only autonomous approval is available in this UI")
            backend_for_agent = backends.get(payload.agent)
            if backend_for_agent is None:
                raise ValueError("Selected agent is not available")
            models = await backend_for_agent.models()
            selected = next((item for item in models if item["id"] == payload.model), None)
            if payload.model is not None and selected is None:
                raise ValueError("Selected model is not available for this agent")
            if payload.reasoning is not None and selected is not None:
                if payload.reasoning not in selected["reasoning_efforts"]:
                    raise ValueError("Selected reasoning level is not supported by this model")
            project = await service.update_project_agent_settings(
                project_id, payload.agent, payload.model, payload.reasoning, payload.sandbox, payload.approval_policy
            )
        except LookupError as exc:
            raise error("not_found", str(exc), 404) from exc
        except ValueError as exc:
            raise error("invalid_agent_settings", str(exc), 422) from exc
        return {"id": project.id, "agent": project.agent, "model": project.model, "reasoning": project.reasoning,
                "sandbox": project.sandbox, "approval_policy": project.approval_policy}

    @app.post("/api/v1/projects/{project_id}/sessions", status_code=201)
    async def add_session(project_id: str):
        try:
            session = await service.create_session(project_id)
        except LookupError as exc:
            raise error("not_found", str(exc), 404) from exc
        except Exception as exc:
            raise error("codex_unavailable", str(exc), 503) from exc
        return {"id": session.id, "native_thread_id": session.native_thread_id}

    @app.post("/api/v1/sessions/{session_id}/switch", status_code=201)
    async def switch_session(session_id: str, payload: SessionSwitchInput):
        try:
            if payload.sandbox not in {"read_only", "workspace_write"}:
                raise ValueError("Only read-only or workspace-write access is available")
            backend_for_agent = backends.get(payload.agent)
            if backend_for_agent is None:
                raise ValueError("Selected agent is not available")
            models = await backend_for_agent.models()
            selected = next((item for item in models if item["id"] == payload.model), None)
            if payload.model is not None and selected is None:
                raise ValueError("Selected model is not available for this agent")
            if payload.reasoning is not None and selected is not None and \
                    payload.reasoning not in selected["reasoning_efforts"]:
                raise ValueError("Selected reasoning level is not supported by this model")
            segment = await service.switch_session(
                session_id, agent=payload.agent, model=payload.model, reasoning=payload.reasoning,
                sandbox=payload.sandbox,
            )
        except LookupError as exc:
            raise error("not_found", str(exc), 404) from exc
        except RuntimeError as exc:
            raise error("chat_busy", str(exc), 409) from exc
        except ValueError as exc:
            raise error("invalid_agent_settings", str(exc), 422) from exc
        except Exception as exc:
            raise error("agent_unavailable", str(exc), 503) from exc
        return {"id": segment.id, "agent": segment.agent, "model": segment.model,
                "reasoning": segment.reasoning, "status": segment.status}

    @app.get("/api/v1/projects/{project_id}/sessions")
    async def sessions(project_id: str):
        from sqlalchemy import select
        from agent_web.db.models import AgentSegment, AgentSession, Turn

        async with session_factory() as db:
            rows = list((await db.scalars(
                select(AgentSession).where(AgentSession.project_id == project_id, AgentSession.archived.is_(False))
            )).all())
            active = {item.session_id: item for item in (await db.scalars(select(AgentSegment).where(
                AgentSegment.status == "active"))).all()}
            missing_titles = {row.id for row in rows if row.title is None}
            fallback_titles = {}
            if missing_titles:
                turns = (await db.scalars(select(Turn).where(
                    Turn.session_id.in_(missing_titles)).order_by(Turn.created_at)
                )).all()
                for turn in turns:
                    fallback_titles.setdefault(turn.session_id, chat_title(turn.prompt))
        return [{"id": row.id, "title": row.title or fallback_titles.get(row.id),
                 "native_thread_id": active.get(row.id).native_thread_id if row.id in active else row.native_thread_id,
                 "source": active.get(row.id).agent if row.id in active else "codex"} for row in rows]

    @app.delete("/api/v1/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str):
        try:
            await service.delete_session(session_id)
        except LookupError as exc:
            raise error("not_found", str(exc), 404) from exc
        except RuntimeError as exc:
            raise error("chat_busy", str(exc), 409) from exc
        return Response(status_code=204)

    @app.get("/api/v1/sessions/{session_id}/messages")
    async def session_messages(session_id: str):
        try:
            messages = await service.session_history(session_id)
            return [
                {
                    **message,
                    **(
                        {"rendered_content": render_markdown(message["content"])}
                        if message["role"] == "assistant"
                        else {}
                    ),
                }
                for message in messages
            ]
        except LookupError as exc:
            raise error("not_found", str(exc), 404) from exc
        except Exception as exc:
            raise error("history_unavailable", str(exc), 502) from exc

    @app.get("/api/v1/sessions/{session_id}/context")
    async def session_context(session_id: str):
        try:
            return await service.export_context(session_id)
        except LookupError as exc:
            raise error("not_found", str(exc), 404) from exc

    @app.get("/api/v1/sessions/{session_id}/context.md", response_class=PlainTextResponse)
    async def session_context_markdown(session_id: str):
        try:
            return await service.export_context_markdown(session_id)
        except LookupError as exc:
            raise error("not_found", str(exc), 404) from exc

    @app.post("/api/v1/sessions/{session_id}/turns")
    async def add_turn(session_id: str, request: Request, background_tasks: BackgroundTasks):
        uploads = []
        if request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
            form = await request.form(max_files=sys.maxsize, max_fields=sys.maxsize,
                                      max_part_size=sys.maxsize)
            prompt = str(form.get("prompt", ""))
            request_id = str(form.get("client_request_id", ""))
            uploads = [item for item in form.getlist("files")
                       if getattr(item, "filename", None) and hasattr(item, "read")]
        else:
            try:
                payload = TurnInput.model_validate(await request.json())
            except Exception as exc:
                raise error("invalid_turn", "Invalid turn payload", 422) from exc
            prompt, request_id = payload.prompt, payload.client_request_id
        if not 8 <= len(request_id) <= 100:
            raise error("invalid_turn", "Client request id must contain 8 to 100 characters", 422)
        if not prompt.strip() and not uploads:
            raise error("invalid_turn", "Add an instruction or at least one attachment", 422)
        try:
            turn, created = await service.enqueue_turn(session_id, prompt, request_id, uploads)
        except LookupError as exc:
            raise error("not_found", str(exc), 404) from exc
        except RuntimeError as exc:
            raise error("project_busy", str(exc), 409) from exc
        except ValueError as exc:
            raise error("invalid_attachment", str(exc), 422) from exc
        finally:
            for upload in uploads:
                await upload.close()
        if created:
            background_tasks.add_task(service.execute_turn, turn.id)
        return {"id": turn.id, "status": turn.status, "response": turn.response,
                "rendered_response": render_markdown(turn.response)}

    @app.get("/api/v1/turns/{turn_id}")
    async def get_turn(turn_id: str):
        try:
            turn = await service.get_turn(turn_id)
        except LookupError as exc:
            raise error("not_found", str(exc), 404) from exc
        return {"id": turn.id, "status": turn.status, "response": turn.response,
                "rendered_response": render_markdown(turn.response)}

    return app
