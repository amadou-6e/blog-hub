from backend.services.cli_runner import api_key_from_connection_token


def test_real_api_key_is_forwarded_to_runner():
    assert api_key_from_connection_token("sk-openai-secret") == "sk-openai-secret"


def test_persisted_cli_session_markers_do_not_override_runner_login():
    assert api_key_from_connection_token("web_session:openai") is None
    assert api_key_from_connection_token("cli_session") is None
    assert api_key_from_connection_token(None) is None
