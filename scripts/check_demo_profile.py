"""V11: the light demo profile in a clean venv, the way a free host runs it (Q-F8-2).

    python scripts/check_demo_profile.py [--serve-seconds 0]

Extracts HEAD into a temporary folder (no data/, no .env), creates a venv from
app/requirements.txt alone, and in that venv: opens the app with AppTest, clicks a prepared
question, opens the record viewer, and checks that torch, sentence-transformers and
transformers are neither loaded nor even installed. Then it starts Streamlit for real,
times the cold start until /_stcore/health answers, and fetches the page. It prints the
install time, the venv size and the timings. --serve-seconds keeps the server up that long
for a look in a browser.
"""

import argparse
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = 8599
HEAVY = ("torch", "sentence_transformers", "transformers")

APP_CHECK = r"""
import importlib.util, sys
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("app/streamlit_app.py", default_timeout=180)
at.run()
labels = [b.label for b in at.sidebar.button]
at.sidebar.button[0].click().run()
at.session_state["record"] = "TBL-001"
at.run()
assert not at.exception, at.exception
assert "Record TBL-001" in [e.label for e in at.expander]
assert len(at.sidebar.text_input) == 0, "no free-text box without a model"
loaded = [m for m in sys.argv[1:] if m in sys.modules]
installed = [m for m in sys.argv[1:] if importlib.util.find_spec(m) is not None]
print(f"prepared questions: {len(labels)}; record viewer: ok; free-text box: none")
print(f"heavy modules loaded: {loaded or 'none'}; installed: {installed or 'none'}")
sys.exit(1 if loaded or installed else 0)
"""


def _size(folder: Path) -> float:
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) / 1e6


def _wait_for(url: str, timeout: float) -> float:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return time.perf_counter() - started
        except OSError:
            time.sleep(0.25)
    raise TimeoutError(url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the light demo profile in a clean venv.")
    parser.add_argument("--serve-seconds", type=int, default=0)
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "clone"
        tree.mkdir()
        archive = subprocess.run(
            ["git", "archive", "HEAD"], cwd=ROOT, capture_output=True, check=True
        )
        subprocess.run(["tar", "-x", "-C", str(tree)], input=archive.stdout, check=True)
        venv = tree / ".venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        python = venv / ("Scripts" if sys.platform == "win32" else "bin") / "python"
        started = time.perf_counter()
        subprocess.run([str(python), "-m", "pip", "install", "--quiet", "-r", "app/requirements.txt"],
                       cwd=tree, check=True)  # fmt: skip
        print(f"install from app/requirements.txt: {time.perf_counter() - started:.0f} s, "
              f"venv {_size(venv):.0f} MB")  # fmt: skip
        env_blank = {"LLM_PROVIDER": "", "LLM_MODEL": "", "LLM_API_KEY": ""}
        env = {**__import__("os").environ, **env_blank}
        check = subprocess.run([str(python), "-c", APP_CHECK, *HEAVY], cwd=tree, env=env,
                               capture_output=True, text=True)  # fmt: skip
        print(check.stdout.strip() or check.stderr[-2000:])
        if check.returncode:
            print("V11: FAILED")
            return 1
        started = time.perf_counter()
        server = subprocess.Popen(
            [str(python), "-m", "streamlit", "run", "app/streamlit_app.py", "--server.port",
             str(PORT), "--server.headless", "true"],
            cwd=tree, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )  # fmt: skip
        try:
            health = _wait_for(f"http://localhost:{PORT}/_stcore/health", 120)
            page = _wait_for(f"http://localhost:{PORT}/", 30)
            print(f"cold start: health after {health:.1f} s, page {page:.2f} s later")
            if args.serve_seconds:
                print(f"serving on http://localhost:{PORT} for {args.serve_seconds} s")
                time.sleep(args.serve_seconds)
        finally:
            server.terminate()
            server.wait(timeout=30)
    print("V11: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
