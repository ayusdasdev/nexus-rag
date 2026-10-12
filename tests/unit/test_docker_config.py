"""Guard rails for the container setup (M9 9.4): the Dockerfile, .dockerignore and the
compose `app` profile keep the properties ADR-0015 depends on."""

import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]  # transitive dep, no stubs installed

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "Dockerfile").read_text()
IGNORED = {
    line.strip()
    for line in (ROOT / ".dockerignore").read_text().splitlines()
    if line.strip() and not line.startswith("#")
}
COMPOSE: dict[str, Any] = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
APP_SERVICES = ("migrate", "api", "worker")


def test_every_base_image_is_pinned_by_tag_and_digest() -> None:
    bases = re.findall(r"^FROM\s+(\S+)", DOCKERFILE, re.MULTILINE)

    assert bases
    for base in bases:
        assert re.fullmatch(
            r"python:3\.12\.\d+-slim-bookworm@sha256:[0-9a-f]{64}", base
        )


def test_the_runtime_stage_runs_as_a_non_root_user_with_a_healthcheck() -> None:
    runtime = DOCKERFILE.split(" AS runtime", 1)[1]

    users = re.findall(r"^USER\s+(\S+)", runtime, re.MULTILINE)
    assert users and users[-1] not in ("root", "0")
    assert re.search(r"^HEALTHCHECK .*?/health", runtime, re.MULTILINE | re.DOTALL)


def test_no_secret_model_or_upload_is_copied_into_the_image() -> None:
    copied = " ".join(re.findall(r"^COPY\s+(.+)$", DOCKERFILE, re.MULTILINE))

    for forbidden in (".env", "data", "eval", "fastembed", "huggingface"):
        assert forbidden not in copied
    assert "COPY . " not in DOCKERFILE  # only named paths, never the whole context
    for entry in (".env", ".env.*", "data/", "eval/state/", ".venv/", ".git/"):
        assert entry in IGNORED, entry


def test_the_app_profile_services_are_opt_in_and_mount_the_models_read_only() -> None:
    services = COMPOSE["services"]

    for name in APP_SERVICES:
        service = services[name]
        assert service["profiles"] == ["app"], name
    for name in ("api", "worker"):
        volumes = services[name]["volumes"]
        models = [v for v in volumes if "/models/" in v]
        assert models and all(v.endswith(":ro") for v in models), (name, volumes)
        assert any(v.startswith("uploads:") and not v.endswith(":ro") for v in volumes)
        environment = services[name]["environment"]
        assert environment["FASTEMBED_CACHE_DIR"].startswith("/models/")
        assert "JWT_SECRET" not in environment  # secrets come from .env, never compose


def test_infrastructure_services_still_start_without_the_profile() -> None:
    for name in ("postgres", "redis", "qdrant"):
        assert "profiles" not in COMPOSE["services"][name]


def test_make_app_down_stops_only_the_app_services_and_keeps_volumes() -> None:
    # `docker compose --profile app down` also removes postgres, redis and qdrant (seen
    # 2026-10-12): app-down must name the app services and never use `down` or `-v`.
    makefile = (ROOT / "Makefile").read_text()
    recipe = makefile.split("\napp-down:", 1)[1].split("\n\n", 1)[0]

    assert " down" not in recipe and " -v" not in recipe
    for name in APP_SERVICES:
        assert name in recipe
    assert "\napp-up:" in makefile
