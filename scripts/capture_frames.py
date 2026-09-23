"""Takes the demo GIF's frames from a running app, through a headless browser (phase 9).

    python scripts/capture_frames.py [--base http://localhost:8501]
    python scripts/capture_frames.py --only 03_trace     # retake one frame

Streamlit draws in the browser over a websocket, so a plain `--screenshot` catches a
half-drawn page. This drives Edge (or Chrome) over the DevTools protocol instead: for each
frame it opens the URL that puts the app in the wanted state (see the deep links in
app/streamlit_app.py), waits until the text that frame is supposed to show is really on the
page, scrolls the interesting part into view, and only then takes the picture.

The viewport is pinned with Emulation.setDeviceMetricsOverride, so every frame comes out the
same size whatever the host window does; the GIF builder refuses frames of different sizes.
The websocket client is `websockets`, already pinned for the project; nothing is installed.

The default address is the app's own frame. Streamlit Community Cloud serves an outer shell
whose body is empty and whose only content is an iframe at /~/+/ plus its own toolbar and
badge; pointing at the frame both makes the page readable from here and leaves the pictures
showing the app alone, which is what the GIF is about.

The five frames are the demo's story: an empty page, an impact answer, the agent trace
behind it, a record opened from a chip, and a question the agent refuses to answer.
"""

import argparse
import asyncio
import base64
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from PIL import Image
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = (
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path("/usr/bin/google-chrome"),
    Path("/usr/bin/chromium"),
)
# name, query string, text that must be on the page, text to scroll into view (or None)
FRAMES = (
    ("01_start", "", "Pick a question on the left", None),
    ("02_impact", "q=impact", "60 reports", None),
    ("03_trace", "q=impact&trace=open", "impact_analysis", "Agent trace"),
    ("04_record", "q=impact&record=EMP-031", "Head of Aftersales", "Record EMP-031"),
    ("05_abstain", "q=unanswerable", "Abstained", None),
)
# The deepest element holding the text is the one scrolled, so a whole section is not moved
# by its outermost container. 'start' puts that heading at the top and fills the frame with
# what comes under it, which is the part worth reading; the margin is backed off afterwards so
# the heading itself is not flush against the edge.
SCROLL_SCRIPT = """
(() => {
  const needle = %s;
  const margin = %d;
  const hit = [...document.querySelectorAll('*')]
    .filter(node => node.textContent.includes(needle))
    .pop();
  if (!hit) return false;
  hit.scrollIntoView({block: 'start', inline: 'nearest'});
  let box = hit.parentElement;
  while (box && box.scrollHeight <= box.clientHeight) box = box.parentElement;
  (box || document.scrollingElement).scrollTop -= margin;
  return true;
})()
"""


def _browser() -> Path:
    for path in BROWSERS:
        if path.exists():
            return path
    raise SystemExit("no Edge or Chrome found for the screenshots")


class Devtools:
    """The few DevTools calls this needs, over one websocket to one page."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.next_id = 0

    async def __aenter__(self) -> "Devtools":
        # A screenshot comes back as one base64 message far past the 1 MB default limit.
        self.socket = await connect(self.url, max_size=None)
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.socket.close()

    async def call(self, method: str, **params: object) -> dict:
        self.next_id += 1
        await self.socket.send(json.dumps({"id": self.next_id, "method": method, "params": params}))
        while True:  # events arrive on the same socket and are not answers
            message = json.loads(await self.socket.recv())
            if message.get("id") == self.next_id:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})

    async def evaluate(self, expression: str) -> object:
        result = await self.call("Runtime.evaluate", expression=expression, returnByValue=True)
        return result.get("result", {}).get("value")

    async def shows(self, needle: str) -> bool:
        return bool(await self.evaluate(f"document.body.innerText.includes({json.dumps(needle)})"))


async def capture(
    page_ws: str, url: str, needle: str, scroll: str | None, out: Path, args: argparse.Namespace
) -> None:
    async with Devtools(page_ws) as page:
        await page.call("Page.enable")
        await page.call(
            "Emulation.setDeviceMetricsOverride",
            width=args.width,
            height=args.height,
            deviceScaleFactor=1,
            mobile=False,
        )
        await page.call("Page.navigate", url=url)
        deadline = time.monotonic() + args.wait
        while True:  # a sleeping host has to wake up, and the first record builds the data
            await asyncio.sleep(0.25)
            if await page.shows(needle):
                break
            if time.monotonic() > deadline:
                raise RuntimeError(f"{out.name}: {needle!r} never appeared within {args.wait}s")
        await asyncio.sleep(args.settle)  # let the last labels and icons paint
        if scroll:
            if not await page.evaluate(SCROLL_SCRIPT % (json.dumps(scroll), args.margin)):
                raise RuntimeError(f"{out.name}: nothing to scroll to ({scroll!r})")
            await asyncio.sleep(1.0)  # the scroll can be animated
        shot = await page.call("Page.captureScreenshot", format="png")
        out.write_bytes(base64.b64decode(shot["data"]))


def page_socket(port: int) -> str:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10) as response:
        pages = [target for target in json.load(response) if target["type"] == "page"]
    return pages[0]["webSocketDebuggerUrl"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture the demo GIF's frames.")
    parser.add_argument("--base", default="https://metacompass.streamlit.app/~/+")
    parser.add_argument("--out", type=Path, default=ROOT / "assets" / "frames")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--port", type=int, default=9333)
    parser.add_argument("--wait", type=float, default=120.0, help="seconds to wait for the text")
    parser.add_argument("--settle", type=float, default=2.5, help="seconds after the text shows")
    parser.add_argument("--margin", type=int, default=90, help="pixels left above a scroll target")
    parser.add_argument("--only", default=None, help="frame names to retake, comma separated")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    wanted = args.only.split(",") if args.only else None
    frames = [frame for frame in FRAMES if wanted is None or frame[0] in wanted]
    if not frames:
        raise SystemExit(f"no frame called {args.only}; have {[f[0] for f in FRAMES]}")
    with tempfile.TemporaryDirectory() as profile:
        browser = subprocess.Popen(
            [
                str(_browser()), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                f"--window-size={args.width},{args.height}", "--force-device-scale-factor=1",
                f"--remote-debugging-port={args.port}", f"--user-data-dir={profile}",
                "--no-first-run", "--no-default-browser-check", "about:blank",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )  # fmt: skip
        try:
            for attempt in range(40):
                try:
                    page_ws = page_socket(args.port)
                    break
                except OSError:  # the debugging port is not listening yet
                    if attempt == 39:
                        raise SystemExit("the browser never opened its debugging port") from None
                    time.sleep(0.5)
            for name, query, needle, scroll in frames:
                url = f"{args.base}/?{query}" if query else f"{args.base}/"
                out = args.out / f"{name}.png"
                asyncio.run(capture(page_ws, url, needle, scroll, out, args))
                with Image.open(out) as image:
                    size = f"{image.width}x{image.height}"
                print(f"{name}: {size}, {out.stat().st_size / 1024:.0f} KB")
        finally:
            browser.terminate()
            browser.wait(timeout=30)
    return 0


if __name__ == "__main__":
    sys.exit(main())
