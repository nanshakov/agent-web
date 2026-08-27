import json
from pathlib import Path

from agent_web.cline import ClineHistory


def test_cline_history_reads_task_and_messages(tmp_path: Path):
    task_id = "task-123"
    (tmp_path / "state").mkdir()
    task_dir = tmp_path / "tasks" / task_id
    task_dir.mkdir(parents=True)
    (tmp_path / "state" / "taskHistory.json").write_text(json.dumps([{
        "id": task_id, "task": "Review project", "cwdOnTaskInitialization": "C:/work/project",
    }]), "utf-8")
    (task_dir / "ui_messages.json").write_text(json.dumps([
        {"ask": "followup", "text": "Please review this."},
        {"say": "text", "text": "I will review it."},
    ]), "utf-8")

    history = ClineHistory(tmp_path)

    assert history.tasks()[0]["title"] == "Review project"
    assert history.messages(task_id) == [
        {"role": "user", "content": "Please review this."},
        {"role": "assistant", "content": "I will review it."},
    ]
