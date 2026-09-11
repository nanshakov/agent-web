import json
from pathlib import Path

from agent_web.codex.sdk_backend import SdkCodexBackend


def journal_message(role: str, text: str) -> str:
    content_type = "input_text" if role == "user" else "output_text"
    return json.dumps({
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": role,
            "content": [{"type": content_type, "text": text}],
        },
    })


def test_journal_history_prefers_current_desktop_transcript(tmp_path: Path):
    thread_id = "01a0246a-ea67-7a90-975d-0025df33e822"
    transcript = tmp_path / "2026" / "09" / "10"
    transcript.mkdir(parents=True)
    log = transcript / f"rollout-{thread_id}.jsonl"
    log.write_text("\n".join((
        json.dumps({"type": "session_meta", "payload": {"thread_id": thread_id}}),
        journal_message("developer", "do not expose"),
        journal_message("user", "Prepare the PR"),
        journal_message("assistant", "UI is running"),
        "{incomplete final line",
    )), encoding="utf-8")

    backend = SdkCodexBackend(session_logs_dir=tmp_path)

    assert backend._journal_history(thread_id) == [
        {"role": "user", "content": "Prepare the PR"},
        {"role": "assistant", "content": "UI is running"},
    ]


def test_journal_history_ignores_invalid_thread_ids(tmp_path: Path):
    backend = SdkCodexBackend(session_logs_dir=tmp_path)

    assert backend._journal_history("../../other-thread") == []
