"""The light demo profile (Q-F8-2): without a model the app never loads the embedding stack,
and it builds its data on first use.

Run in a fresh interpreter, so modules other tests imported cannot hide what the app loads.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEAVY = ("torch", "sentence_transformers", "transformers")

# Opens a prepared answer, then the record viewer on one of its IDs, as a visitor would.
SCRIPT = r"""
import sys
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(sys.argv[1], default_timeout=180)
at.run()
at.sidebar.button[0].click().run()
at.session_state["record"] = "TBL-001"
at.run()
assert not at.exception, at.exception
titles = [e.label for e in at.expander]
assert "Record TBL-001" in titles, titles
print("HEAVY:" + ",".join(name for name in sys.argv[2:] if name in sys.modules))
"""


def test_the_demo_never_imports_torch_or_sentence_transformers(tmp_path):
    env = {
        **os.environ,
        "METACOMPASS_DATA_DIR": str(tmp_path / "data"),  # empty: the app generates it
        "LLM_PROVIDER": "", "LLM_MODEL": "", "LLM_API_KEY": "",
    }  # fmt: skip
    out = subprocess.run(
        [sys.executable, "-c", SCRIPT, str(ROOT / "app" / "streamlit_app.py"), *HEAVY],
        capture_output=True, text=True, env=env, cwd=ROOT, timeout=600,
    )  # fmt: skip
    assert out.returncode == 0, out.stderr[-3000:]
    loaded = next(line for line in out.stdout.splitlines() if line.startswith("HEAVY:"))
    assert loaded == "HEAVY:"
    assert (tmp_path / "data" / "raw" / "reports.csv").is_file()
