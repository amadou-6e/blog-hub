from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_compose_wires_backend_to_healthy_runner_and_separate_storage():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    backend = services["backend"]

    assert backend["environment"]["CLI_RUNNER_URL"] == "http://cli-runner:8001"
    assert backend["depends_on"]["cli-runner"]["condition"] == "service_healthy"
    assert "bloghub-data:/app/data" in backend["volumes"]
    assert "bloghub-credential-keys:/run/bloghub-keys" in backend["volumes"]
    assert services["cli-runner"]["healthcheck"]
    assert services["backend"]["healthcheck"]


def test_skyvern_is_opt_in_and_does_not_gate_agent_runner_startup():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert "depends_on" not in services["cli-runner"]
    for service in ("skyvern-postgres", "skyvern", "skyvern-ui"):
        assert services[service]["profiles"] == ["hashnode-browser"]


def test_cli_runner_installs_callback_http_client():
    requirements = (ROOT / "cli-runner" / "requirements.txt").read_text(
        encoding="utf-8"
    ).splitlines()

    assert any(requirement.startswith("httpx") for requirement in requirements)
