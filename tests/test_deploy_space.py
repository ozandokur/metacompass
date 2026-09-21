"""Publishing the demo to a Hugging Face Space (phase 8): what goes up, and how."""

import deploy_space


def test_the_staging_folder_holds_only_what_the_app_needs(tmp_path):
    staged = deploy_space.stage(tmp_path / "space")
    names = {p.relative_to(staged).as_posix() for p in staged.rglob("*") if p.is_file()}
    for needed in ("Dockerfile", "requirements.txt", "pyproject.toml", "README.md",
                   "app/streamlit_app.py", "app/cached_answers.json", "scripts/warm_up.py",
                   "src/metacompass/api.py"):  # fmt: skip
        assert needed in names, needed
    assert any(n.startswith("src/metacompass/data/vocab/") for n in names)
    for never in (".env", "PROGRESS.md", "CLAUDE.md"):
        assert never not in names, never
    for prefix in ("docs/", "eval/", "tests/", "data/", ".git/"):
        assert not any(n.startswith(prefix) for n in names), prefix
    assert not any("__pycache__" in n for n in names)


def test_the_space_readme_is_the_template_with_front_matter(tmp_path):
    staged = deploy_space.stage(tmp_path / "space")
    readme = (staged / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("---\n") and "sdk: docker" in readme and "app_port: 7860" in readme


class FakeApi:
    def __init__(self):
        self.calls = []

    def create_repo(self, **kwargs):
        self.calls.append(("create_repo", kwargs))

    def upload_folder(self, **kwargs):
        self.calls.append(("upload_folder", kwargs))
        return "https://huggingface.co/spaces/someone/metacompass/commit/abc"


def test_publishing_creates_a_docker_space_and_uploads_the_folder(tmp_path):
    api = FakeApi()
    staged = deploy_space.stage(tmp_path / "space")
    deploy_space.publish(api, "someone/metacompass", staged, "deploy abc1234")
    (create, created), (upload, uploaded) = api.calls
    assert create == "create_repo" and created["repo_type"] == "space"
    assert created["space_sdk"] == "docker" and created["exist_ok"] is True
    assert upload == "upload_folder" and uploaded["repo_type"] == "space"
    assert uploaded["folder_path"] == str(staged)
    assert "token" not in created and "token" not in uploaded  # from the login cache only
