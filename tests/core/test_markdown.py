from agent_web.markdown import render_markdown


def test_markdown_supports_rich_content_without_allowing_active_html():
    rendered = render_markdown(
        "# Result\n\n- [x] Done\n\n| A | B |\n| - | - |\n| 1 | 2 |\n\n"
        "<script>alert(1)</script> [unsafe](javascript:alert(1))"
    )

    assert "<h1>Result</h1>" in rendered
    assert 'type="checkbox" disabled checked' in rendered
    assert "<table>" in rendered
    assert "<script>" not in rendered
    assert 'href="javascript:' not in rendered
