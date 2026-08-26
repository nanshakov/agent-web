from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from agent_web.config import Settings
from agent_web.db.database import migrate_database


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateStatus:
    current_commit: str
    available_commit: str | None
    commits: tuple[str, ...]

    @property
    def available(self) -> bool:
        return self.available_commit is not None and self.available_commit != self.current_commit


class Updater:
    def __init__(self, project_root: Path, settings: Settings) -> None:
        self.project_root = project_root
        self.settings = settings

    def git(self, *args: str, check: bool = True) -> str:
        result = subprocess.run(
            ["git", *args], cwd=self.project_root, text=True, capture_output=True, check=False
        )
        if check and result.returncode:
            raise UpdateError(result.stderr.strip() or result.stdout.strip() or "Git command failed")
        return result.stdout.strip()

    def _require_config(self) -> tuple[str, str]:
        if not self.settings.update_repository_url:
            raise UpdateError("Update repository is not configured. Run 'agent-web configure-update'.")
        return self.settings.update_repository_url, self.settings.update_branch

    def status(self) -> UpdateStatus:
        repository, branch = self._require_config()
        current = self.git("rev-parse", "HEAD")
        self.git("fetch", "--quiet", repository, branch)
        available = self.git("rev-parse", "FETCH_HEAD")
        if available == current:
            return UpdateStatus(current, available, ())
        ancestry = subprocess.run(
            ["git", "merge-base", "--is-ancestor", current, available],
            cwd=self.project_root,
            capture_output=True,
            check=False,
        )
        if ancestry.returncode:
            raise UpdateError("Remote main is not a fast-forward update; resolve the Git history manually.")
        commits = tuple(self.git("log", "--format=%h %s", f"{current}..{available}").splitlines())
        return UpdateStatus(current, available, commits)

    def apply(self) -> UpdateStatus:
        if self.git("status", "--porcelain"):
            raise UpdateError("Installation checkout has local changes; update is blocked.")
        status = self.status()
        if not status.available:
            return status
        self.git("merge", "--ff-only", "FETCH_HEAD")
        uv = "uv"
        sync = subprocess.run([uv, "sync", "--extra", "dev", "--frozen"], cwd=self.project_root)
        if sync.returncode:
            raise UpdateError("Dependencies could not be synchronized. Resolve manually; the database was not migrated.")
        migrate_database(self.settings.data_dir, self.settings.database_url)
        return self.status()
