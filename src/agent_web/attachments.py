from __future__ import annotations

import json
from pathlib import Path, PurePath
from typing import Protocol
from uuid import uuid4


class Upload(Protocol):
    filename: str | None
    content_type: str | None

    async def read(self, size: int = -1) -> bytes: ...


TEXT_EXTENSIONS = {
    ".c", ".cc", ".conf", ".cpp", ".css", ".csv", ".go", ".h", ".hpp",
    ".html", ".ini", ".java", ".js", ".json", ".jsx", ".kt", ".log", ".md",
    ".php", ".properties", ".py", ".rb", ".rs", ".sh", ".sql", ".svg", ".toml",
    ".ts", ".tsx", ".txt", ".xml", ".yaml", ".yml", ".env", ".ipynb",
}
TEXT_FILENAMES = {"dockerfile", "gemfile", "makefile", "procfile"}
TEXT_CONTENT_TYPES = {"application/json", "application/sql", "application/xml"}
MAX_EXTRACTED_CHARS = 100_000
CHUNK_SIZE = 1024 * 1024


def attachment_directory(project_path: Path, session_id: str) -> Path:
    project = project_path.resolve()
    directory = (project / ".agent-web" / "attachments" / session_id).resolve()
    if not directory.is_relative_to(project):
        raise ValueError("Invalid attachment directory")
    return directory


def _safe_original_name(filename: str | None) -> str:
    # PurePath on Windows does not treat backslashes as separators on POSIX.
    name = PurePath((filename or "attachment").replace("\\", "/")).name
    return name[:255] or "attachment"


def _kind(name: str, content_type: str) -> str | None:
    suffix = Path(name).suffix.lower()
    if content_type.startswith("image/"):
        return "image"
    if (content_type.startswith("text/") or content_type in TEXT_CONTENT_TYPES
            or suffix in TEXT_EXTENSIONS or name.lower() in TEXT_FILENAMES):
        return "text"
    return None


def _stored_suffix(name: str) -> str:
    suffix = Path(name).suffix.lower()
    return suffix if 1 < len(suffix) <= 16 and suffix[1:].isalnum() else ""


def _exclude_from_git(project_path: Path) -> None:
    exclude = project_path / ".git" / "info" / "exclude"
    if not (project_path / ".git").is_dir():
        return
    exclude.parent.mkdir(parents=True, exist_ok=True)
    marker = ".agent-web/"
    current = exclude.read_text("utf-8", errors="replace") if exclude.exists() else ""
    if marker not in current.splitlines():
        prefix = "" if not current or current.endswith("\n") else "\n"
        exclude.write_text(f"{current}{prefix}{marker}\n", encoding="utf-8")


async def store_uploads(project_path: Path, session_id: str, uploads: list[Upload]) -> list[dict[str, object]]:
    if not uploads:
        return []
    directory = attachment_directory(project_path, session_id)
    directory.mkdir(parents=True, exist_ok=True)
    _exclude_from_git(project_path)
    created: list[Path] = []
    metadata: list[dict[str, object]] = []
    try:
        for upload in uploads:
            original_name = _safe_original_name(upload.filename)
            content_type = (upload.content_type or "application/octet-stream").lower()
            kind = _kind(original_name, content_type)
            if kind is None:
                raise ValueError(f"Unsupported attachment type: {original_name}")
            suffix = _stored_suffix(original_name)
            stored_name = f"{uuid4()}{suffix}"
            destination = directory / stored_name
            size = 0
            created.append(destination)
            with destination.open("xb") as stream:
                while chunk := await upload.read(CHUNK_SIZE):
                    stream.write(chunk)
                    size += len(chunk)
            relative_path = destination.relative_to(project_path.resolve()).as_posix()
            metadata.append({
                "name": original_name,
                "path": relative_path,
                "content_type": content_type,
                "size": size,
                "kind": kind,
            })
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        try:
            directory.rmdir()
        except OSError:
            pass
        raise
    return metadata


def load_metadata(raw: str | None) -> list[dict[str, object]]:
    if not raw:
        return []
    value = json.loads(raw)
    return value if isinstance(value, list) else []


def agent_prompt(project_path: Path, prompt: str, attachments: list[dict[str, object]]) -> str:
    if not attachments:
        return prompt
    lines = [prompt.strip() or "Inspect the attached files.", "", "Attached files:"]
    for item in attachments:
        absolute_path = (project_path / str(item["path"])).resolve()
        lines.append(
            f'- {item["name"]} ({item["kind"]}, {item["content_type"]}, {item["size"]} bytes): '
            f'`{absolute_path}`'
        )
        if item["kind"] != "text":
            continue
        with absolute_path.open("rb") as stream:
            raw = stream.read(MAX_EXTRACTED_CHARS * 4 + 1)
        decoded = raw.decode("utf-8-sig", errors="replace")
        truncated = absolute_path.stat().st_size > len(raw) or len(decoded) > MAX_EXTRACTED_CHARS
        text = decoded[:MAX_EXTRACTED_CHARS]
        label = "first 100000 characters" if truncated else "content"
        lines.extend((f"\n--- {item['name']} ({label}) ---", text, f"--- end {item['name']} ---"))
    return "\n".join(lines)
