from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import uvicorn

from agent_web.config import Settings, default_data_dir
from agent_web.main import create_app
from agent_web.tooling import find_codex


def config_path(data_dir: Path) -> Path:
    return data_dir / "config.json"


def load_settings(data_dir: Path, *, host: str = "127.0.0.1", port: int = 8765) -> Settings:
    path = config_path(data_dir)
    payload = json.loads(path.read_text("utf-8")) if path.exists() else {"roots": []}
    return Settings(data_dir=data_dir, allowed_roots=tuple(Path(p) for p in payload["roots"]), host=host, port=port)


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-web")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create local configuration")
    init.add_argument("--root", type=Path, action="append")
    init.add_argument("--discover-codex", action="store_true", help="Discover Git project cwd values from local Codex chats")
    serve = commands.add_parser("serve", help="Run Agent Web")
    serve.add_argument("--allow-lan", action="store_true")
    serve.add_argument("--port", type=int, default=8765)
    commands.add_parser("doctor", help="Print local diagnostics")
    test = commands.add_parser("run-tests", help="Run core and current-platform tests")
    test.add_argument("--with-codex", action="store_true")
    args = parser.parse_args()
    data_dir: Path = args.data_dir

    if args.command == "init":
        roots = [str(path.expanduser().resolve()) for path in args.root or []]
        if args.discover_codex:
            from agent_web.codex.sdk_backend import SdkCodexBackend

            async def discover() -> list[str]:
                return [item["cwd"] for item in await SdkCodexBackend().list_threads() if item.get("cwd")]

            roots.extend(discover_root for discover_root in asyncio.run(discover()) if Path(discover_root).is_dir())
        roots = list(dict.fromkeys(roots))
        if not roots:
            parser.error("init requires --root or --discover-codex")
        data_dir.mkdir(parents=True, exist_ok=True)
        config_path(data_dir).write_text(json.dumps({"roots": roots}, indent=2), "utf-8")
        print(f"Configured {len(roots)} allowed root(s) in {config_path(data_dir)}")
        return
    if args.command == "doctor":
        settings = load_settings(data_dir)
        print(f"Data: {settings.data_dir}\nRoots: {', '.join(map(str, settings.allowed_roots)) or 'none'}")
        print(f"Python: {sys.version.split()[0]}\nPlatform: {sys.platform}")
        print(f"Codex: {find_codex() or 'not found'}")
        return
    if args.command == "run-tests":
        paths = ["tests/core", f"tests/platform/{'windows' if sys.platform == 'win32' else 'macos'}"]
        command = [sys.executable, "-m", "pytest", *paths]
        if args.with_codex:
            command.append("tests/integration/codex")
        raise SystemExit(subprocess.call(command))
    settings = load_settings(data_dir, host="0.0.0.0" if args.allow_lan else "127.0.0.1", port=args.port)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
