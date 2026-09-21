"""Publishes the demo to a Hugging Face Space (phase 8).

    python scripts/deploy_space.py [--repo Ozandokur/metacompass]

The GitHub README and the Space README cannot be one file: a Space reads its configuration
from a YAML block at the top of its README, which a portfolio README should not show. So
the Space gets a staging folder with only what the app needs to build and run (the package,
the app with its prepared answers, the build files and the warm-up script) and
deploy/hf_space_README.md as its README. No model key goes to the Space: the free tier's
daily quota belongs to the evaluation (Ozan, 2026-09-21), so the demo serves only the
prepared answers. The upload uses the token of `hf auth login`; it never appears in the
code, the arguments or the output.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "Ozandokur/metacompass"
# What the image needs: see the Dockerfile. Everything else stays in the source repository.
FILES = (
    "Dockerfile", ".dockerignore", ".gitattributes", "LICENSE", "pyproject.toml",
    "requirements.txt", "scripts/warm_up.py", "scripts/smoke_check.py",
)  # fmt: skip
FOLDERS = ("src", "app")
SPACE_README = ROOT / "deploy" / "hf_space_README.md"


def _tracked(folder: str) -> list[str]:
    """The folder's tracked files; without git (a ZIP download), its files minus bytecode."""
    try:
        listing = subprocess.run(
            ["git", "ls-files", "--", folder], cwd=ROOT, check=True, capture_output=True,
            text=True,
        ).stdout  # fmt: skip
    except (subprocess.CalledProcessError, FileNotFoundError):
        return sorted(
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / folder).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        )
    return [line for line in listing.splitlines() if line]


def stage(target: Path) -> Path:
    """Copy the Space's files into `target`: tracked files only, so no cache, key or notes."""
    target.mkdir(parents=True, exist_ok=True)
    for name in [*FILES, *(f for folder in FOLDERS for f in _tracked(folder))]:
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, destination)
    shutil.copy2(SPACE_README, target / "README.md")
    return target


def publish(api, repo_id: str, folder: Path, message: str) -> str:
    """Create the Space if it does not exist, then upload the folder as one commit."""
    api.create_repo(repo_id=repo_id, repo_type="space", space_sdk="docker", exist_ok=True)
    return api.upload_folder(
        repo_id=repo_id,
        repo_type="space",
        folder_path=str(folder),
        commit_message=message,
        # Files the source no longer has are removed, so the Space mirrors this commit.
        delete_patterns=["*"],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish the demo to a Hugging Face Space.")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    args = parser.parse_args(argv)
    from huggingface_hub import HfApi

    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, check=True, capture_output=True,
        text=True,
    ).stdout.strip()  # fmt: skip
    with tempfile.TemporaryDirectory() as tmp:
        staged = stage(Path(tmp) / "space")
        files = sum(1 for p in staged.rglob("*") if p.is_file())
        commit = publish(HfApi(), args.repo, staged, f"Deploy MetaCompass {sha}")
    print(f"uploaded {files} files from {sha} to {args.repo}: {commit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
