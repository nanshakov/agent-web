from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

import uvicorn

from agent_web.config import Settings, config_file, default_data_dir, read_config, write_config
from agent_web.main import create_app
from agent_web.tooling import find_codex
from agent_web.updater import UpdateError, Updater


def load_settings(data_dir: Path, *, host: str = "127.0.0.1", port: int = 8765) -> Settings:
    payload = read_config(data_dir)
    return Settings(
        data_dir=data_dir,
        allowed_roots=tuple(Path(p) for p in payload["roots"]),
        host=host,
        port=port,
        update_repository_url=payload.get("update_repository_url"),
        update_branch=payload.get("update_branch", "main"),
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-web")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create local configuration")
    init.add_argument("--root", type=Path, action="append")
    init.add_argument("--discover-codex", action="store_true", help="Discover Git project cwd values from local Codex chats")
    configure_update = commands.add_parser("configure-update", help="Configure the Git source for application updates")
    configure_update.add_argument("--repository-url", required=True)
    configure_update.add_argument("--branch", default="main")
    update = commands.add_parser("update", help="Check or apply an Agent Web update")
    update_subcommands = update.add_subparsers(dest="update_command", required=True)
    update_subcommands.add_parser("check")
    apply = update_subcommands.add_parser("apply")
    apply.add_argument("--yes", action="store_true", help="Apply the fetched fast-forward update")
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
        existing = read_config(data_dir)
        existing["roots"] = roots
        write_config(data_dir, existing)
        print(f"Configured {len(roots)} allowed root(s) in {config_file(data_dir)}")
        return
    if args.command == "configure-update":
        payload = read_config(data_dir)
        payload["update_repository_url"] = args.repository_url
        payload["update_branch"] = args.branch
        write_config(data_dir, payload)
        print(f"Update source: {args.repository_url} ({args.branch})")
        return
    if args.command == "update":
        settings = load_settings(data_dir)
        updater = Updater(Path(__file__).parents[2], settings)
        try:
            if args.update_command == "check":
                status = updater.status()
                print(f"Current: {status.current_commit[:12]}")
                print(f"Available: {status.available_commit[:12] if status.available_commit else 'none'}")
                print("\n".join(status.commits) or "Already up to date.")
            else:
                if not args.yes:
                    parser.error("update apply requires --yes")
                status = updater.apply()
                print(f"Active: {status.available_commit[:12] if status.available_commit else status.current_commit[:12]}")
        except UpdateError as error:
            print(f"Update failed: {error}", file=sys.stderr)
            raise SystemExit(1)
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
