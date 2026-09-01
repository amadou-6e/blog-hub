import httpx
import pytest

import backend.services.cli_runner as cli_runner
from backend.services.cli_runner import api_key_from_connection_token


def test_real_api_key_is_forwarded_to_runner():
    assert api_key_from_connection_token("sk-openai-secret") == "sk-openai-secret"


def test_persisted_cli_session_markers_do_not_override_runner_login():
    assert api_key_from_connection_token("web_session:openai") is None
    assert api_key_from_connection_token("cli_session") is None
    assert api_key_from_connection_token(None) is None


def test_logout_wraps_runner_read_timeout(monkeypatch):
    request = httpx.Request("POST", "http://runner/logout")

    class TimeoutClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, *_args, **_kwargs):
            raise httpx.ReadTimeout("timed out", request=request)

    monkeypatch.setattr(cli_runner, "_client", TimeoutClient)

    with pytest.raises(cli_runner.RunnerUnavailable, match="transport failed"):
        cli_runner.logout_browser_profile("medium", "o_org", "bp_profile")
