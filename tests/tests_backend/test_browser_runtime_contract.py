"""Keep shared-profile readers and writers on the same Chromium storage format."""
from pathlib import Path
import re

from packaging.requirements import Requirement
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
# Patchright 1.62.1's driver/package/browsers.json pins Chromium 151.0.7922.34.
PATCHRIGHT_VERSION = "1.62.1"
CHROMIUM_EXECUTABLE = "/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome"


@pytest.mark.parametrize("requirements", [
    "cli-runner/requirements.txt",
    "experiments/skyvern/patchright-requirements.txt",
    "validation/requirements.lock",
])
def test_profile_runtimes_pin_the_same_patchright(requirements):
    declarations = []
    for line in (ROOT / requirements).read_text().splitlines():
        if re.match(r"^patchright(?:\s|[=<>!~;\[]|$)", line):
            declarations.append(Requirement(line.split("\\", 1)[0].strip()))
    assert len(declarations) == 1, f"{requirements} must pin Patchright exactly once"
    assert str(declarations[0].specifier) == f"=={PATCHRIGHT_VERSION}"
    assert declarations[0].marker is None


@pytest.mark.parametrize("compose", [
    "docker-compose.yml",
    "experiments/skyvern/docker-compose.patchright.yml",
    "validation/compose.yml",
])
def test_skyvern_uses_the_chromium_installed_by_runner_patchright(compose):
    config = yaml.safe_load((ROOT / compose).read_text())
    environment = config["services"]["skyvern"]["environment"]
    assert environment["CHROME_EXECUTABLE_PATH"] == CHROMIUM_EXECUTABLE, (
        f"{compose}: Skyvern must use Patchright {PATCHRIGHT_VERSION}'s Chromium, "
        "not the older browser inherited from the Skyvern base image"
    )


@pytest.mark.parametrize("dockerfile, requirements, installed_requirements", [
    ("cli-runner/Dockerfile", "requirements.txt", "requirements.txt"),
    ("experiments/skyvern/Dockerfile.patchright", "patchright-requirements.txt",
     "/tmp/patchright-requirements.txt"),
    ("validation/Dockerfile", "validation/requirements.lock", "/tmp/requirements.lock"),
    ("validation/Dockerfile.skyvern", "experiments/skyvern/patchright-requirements.txt",
     "/tmp/requirements.txt"),
])
def test_profile_images_install_chromium_after_pinned_patchright(
    dockerfile, requirements, installed_requirements,
):
    source = (ROOT / dockerfile).read_text().replace("\\\n", " ")
    instructions = source.splitlines()
    copies = [line.split() for line in instructions if line.startswith("COPY ")]
    assert any(copy[1] == requirements for copy in copies)
    runs = [line for line in instructions if line.startswith("RUN ")]
    install_requirements = next(
        index for index, run in enumerate(runs)
        if "pip install " in run and f"-r {installed_requirements}" in run
    )
    install_browser = next((
        index for index, run in enumerate(runs)
        if re.search(r"\bpatchright install(?: --with-deps)? chromium\b", run)
    ), None)
    assert install_browser is not None, f"{dockerfile} must install Patchright's Chromium"
    assert install_requirements <= install_browser
    if install_requirements == install_browser:
        run = runs[install_browser]
        assert run.index(f"-r {installed_requirements}") < run.index("patchright install")
