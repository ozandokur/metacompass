"""What the image must never contain or do (spec §11.1, phase 8 acceptance), checked on the
build files themselves so it holds even where Docker is not running."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")


def ignored() -> set[str]:
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    return {line.strip().rstrip("/") for line in lines if line.strip() and not line.startswith("#")}


def test_secrets_plans_notes_and_local_data_stay_out_of_the_image():
    # The key file, the private plan and the learning notes are never shipped; data/ is
    # regenerated in the image from seed 42 instead of copied from a workstation.
    assert {".env", "docs/plan", "docs/learn", "data", ".git"} <= ignored()


def test_the_container_runs_as_the_spaces_user_and_serves_the_demo_on_7860():
    user_at = DOCKERFILE.index("USER user")
    assert user_at < DOCKERFILE.index("COPY")  # nothing is copied as root
    assert "--uid 1000" in DOCKERFILE
    assert "EXPOSE 7860" in DOCKERFILE
    assert '"app/streamlit_app.py", "--server.port", "7860"' in DOCKERFILE


def test_no_model_key_is_baked_into_the_image():
    assert "LLM_API_KEY" not in DOCKERFILE
    assert "COPY --chown=user .env" not in DOCKERFILE


def test_the_space_readme_template_declares_a_docker_space_on_the_app_port():
    readme = (ROOT / "deploy" / "hf_space_README.md").read_text(encoding="utf-8")
    front = readme.split("---")[1]
    assert "sdk: docker" in front and "app_port: 7860" in front
