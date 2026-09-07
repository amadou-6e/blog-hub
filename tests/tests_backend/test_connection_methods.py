import pytest

import backend.store as store
from backend.services import connection_health


@pytest.mark.parametrize("platform", ["medium", "hashnode"])
@pytest.mark.parametrize("token_status", ["disconnected", "connected", "error"])
@pytest.mark.parametrize("browser_connected", [False, True])
def test_api_connected_is_token_state_before_browser_merge(
    client, platform, token_status, browser_connected,
):
    store.delete_connection("user_seed", platform)
    if token_status != "disconnected":
        store.save_connection("user_seed", platform, "test-token", status=token_status)
    if browser_connected:
        store.start_browser_connection(
            "user_seed", platform, session_id="pbs_test", organization_id="o_org",
            profile_id="bp_saved", app_url="http://localhost/login",
        )
        store.update_browser_connection("user_seed", platform, "connected")
        connection_health.record_evidence(store, "user_seed", platform, {
            "status": "reauthentication_required", "reason": "session_expired",
            "source": "remote_operation", "authoritative": True,
        })
    for _ in range(2):
        response = client.get("/api/connections")
        assert response.status_code == 200
        connection = next(item for item in response.json()["connections"] if item["id"] == platform)
        assert connection["apiConnected"] is (token_status == "connected")
        assert connection["status"] == ("connected" if browser_connected else token_status)
        assert "test-token" not in response.text
        if browser_connected:
            assert connection["connectionHealth"]["status"] == "reauthentication_required"
    raw = next(item for item in store.list_connections("user_seed") if item["id"] == platform)
    assert raw["status"] == token_status
