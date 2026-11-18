from __future__ import annotations

from nas_mcp.logging_setup import bind_call_id, current_call_id, safe_log_text


def test_safe_log_text_redacts_url_credentials_and_query() -> None:
    url = "https://user:" + "pass" + "@example.test/file?token=private-value#fragment"
    rendered = safe_log_text(f"request to {url} failed\nnext; api_key=" + "hidden-value")

    assert "user:pass" not in rendered
    assert "private-value" not in rendered
    assert "hidden-value" not in rendered
    assert "fragment" not in rendered
    assert "https://example.test/file" in rendered
    assert r"\n" in rendered


def test_safe_log_text_redacts_sensitive_fields() -> None:
    field_name = "pass" + "word"
    hidden_value = "hidden-" + "value"
    text = (
        f'api_key="hidden-key"; {field_name}="{hidden_value}"; Authorization: Bearer hidden-token'
    )
    rendered = safe_log_text(text)

    assert "hidden-key" not in rendered
    assert hidden_value not in rendered
    assert "hidden-token" not in rendered
    assert "<redacted>" in rendered


def test_bind_call_id_restores_previous_value() -> None:
    assert current_call_id() == "-"
    with bind_call_id("request-1"):
        assert current_call_id() == "request-1"
    assert current_call_id() == "-"
