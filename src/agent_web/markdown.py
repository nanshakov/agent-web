from __future__ import annotations

import mistune
from mistune.plugins.task_lists import task_lists


_markdown = mistune.create_markdown(
    escape=True,
    plugins=["table", task_lists],
)


def render_markdown(value: str | None) -> str | None:
    """Render display HTML while escaping HTML embedded in Markdown."""
    return _markdown(value) if value is not None else None
