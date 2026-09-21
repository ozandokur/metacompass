"""MetaCompass demo (spec §10.2): prepared questions with their full agent trace, a record
viewer, and free text only when a model is configured.

    streamlit run app/streamlit_app.py

The eight prepared questions come from the dev set and answer instantly from
app/cached_answers.json (scripts/build_demo_cache.py): no model call, no quota. Free text
runs the real agent through the same quota guard as the eval, since both draw on one
free-tier daily quota (D25); it is off unless a model is configured, and limited per session
and per day. The app imports the agent directly instead of calling the API, so a deploy is
one process.

Three environment variables exist for the smoke test: METACOMPASS_DEMO_CACHE (the answers
file), METACOMPASS_DATA_DIR and METACOMPASS_EMBEDDER ("hash" skips loading the model).
"""

import json
import os
from datetime import date
from pathlib import Path

import streamlit as st

from metacompass.agent.loop import Agent
from metacompass.config import PROJECT_ROOT, load_settings
from metacompass.retrieval.embedders import HashEmbedder, SentenceTransformerEmbedder
from metacompass.service import Components, build_components, live_llm

APP_DIR = Path(__file__).resolve().parent
CACHE_FILE = Path(os.environ.get("METACOMPASS_DEMO_CACHE", APP_DIR / "cached_answers.json"))
DATA_DIR = Path(os.environ.get("METACOMPASS_DATA_DIR", PROJECT_ROOT / "data"))
EMBEDDER = os.environ.get("METACOMPASS_EMBEDDER", "model")
SESSION_LIMIT = 5  # free-text questions per browser session (spec §10.2)
TRACE_OUTPUT_CHARS = 1500  # of each tool output shown in the trace
REPO_URL = "https://github.com/ozandokur/metacompass"
RESULTS_URL = f"{REPO_URL}/blob/main/eval/results.md"


@st.cache_data
def prepared() -> dict:
    return json.loads(CACHE_FILE.read_text(encoding="utf-8"))


@st.cache_resource
def components() -> Components:
    embedder = (
        HashEmbedder(dim=64)
        if EMBEDDER == "hash"
        else SentenceTransformerEmbedder(load_settings().embedding_model)
    )
    return build_components(DATA_DIR, embedder)


@st.cache_resource
def model():
    """The guarded live model, or None: free text is off without one."""
    return live_llm(load_settings(), DATA_DIR / "app_quota_log.json", DATA_DIR / "cache" / "llm")


@st.cache_resource
def daily_counter() -> dict:
    # One per server process, shared by every session: the day's free-text questions.
    return {"date": date.today().isoformat(), "count": 0}


def free_text_allowed() -> tuple[bool, str]:
    """Whether one more free-text question may run, and why not when it may not."""
    counter = daily_counter()
    if counter["date"] != date.today().isoformat():
        counter.update(date=date.today().isoformat(), count=0)
    if st.session_state.get("asked", 0) >= SESSION_LIMIT:
        return False, f"This session has used its {SESSION_LIMIT} free questions."
    if counter["count"] >= load_settings().demo_daily_limit:
        return False, "The demo's free questions for today are used up."
    return True, ""


def show(question: str, result: dict, note: str, view: str) -> None:
    answer = result["answer"]
    st.markdown(f"**Question:** {question}")
    with st.container(border=True):
        st.markdown(answer["answer"])
        chips("Answer", answer["answer_ids"], f"answer-{view}")
        chips("Evidence", answer["evidence_ids"], f"evidence-{view}")
        if answer["abstained"]:
            st.warning("Abstained: the metadata does not hold this answer.")
        if result["stripped_ids"]:
            st.warning("Unverified IDs removed: " + ", ".join(result["stripped_ids"]))
    tokens = result["input_tokens"] + result["output_tokens"]
    # A prepared answer was replayed from a cache: its model steps took no time, so neither
    # they nor the total say anything about the agent. Tool steps really ran and keep theirs.
    replayed = view.startswith("prepared")
    timing = "" if replayed else f"{result['latency_ms']} ms · "
    st.caption(f"{timing}{result['tool_calls']} tool calls · {tokens} tokens · {note}")
    with st.expander("Agent trace", expanded=False):
        for number, step in enumerate(result["steps"], start=1):
            if step["kind"] == "tool":
                st.markdown(f"**{number}. {step['name']}** · {step['duration_ms']} ms")
                st.json(step["arguments"])
                st.code(step["summary"][:TRACE_OUTPUT_CHARS], language="json")
            else:
                took = "" if replayed else f" · {step['duration_ms']} ms"
                st.markdown(f"{number}. model: {step['summary']}{took}")


def chips(title: str, ids: list[str], key: str) -> None:
    """IDs as clickable chips that wrap onto new lines; a click opens the record viewer."""
    if not ids:
        return

    def open_record() -> None:
        if st.session_state[key]:
            st.session_state["record"] = st.session_state[key]

    # The key carries the question shown, so a new answer starts with nothing selected.
    st.pills(title, ids, selection_mode="single", key=key, on_change=open_record)


def record_viewer() -> None:
    record_id = st.session_state.get("record")
    if not record_id:
        return
    payload, _ = components().registry.call("get_record", {"record_id": record_id})
    with st.expander(f"Record {record_id}", expanded=True):
        st.json(payload)


def sidebar() -> None:
    cache = prepared()
    st.sidebar.markdown("### Try a question")
    # These were picked from development questions the agent got right; say so, and point
    # to where its measured accuracy is.
    st.sidebar.caption(
        f"Prepared: development questions the agent answered correctly. Measured accuracy "
        f"on the held-out test set is in the [evaluation results]({RESULTS_URL})."
    )
    for number, entry in enumerate(cache["questions"]):
        if st.sidebar.button(entry["label"], key=f"q{number}", help=entry["question"]):
            st.session_state["shown"] = {"kind": "prepared", "number": number}
            st.session_state.pop("record", None)

    st.sidebar.markdown("### Ask your own")
    llm = model()
    if llm is None:
        # The public demo has no model key: the free tier's daily quota belongs to the
        # evaluation. Say how to ask a question instead of showing a box that cannot work.
        st.sidebar.caption(
            "Free text needs a model: run the app locally with your own Google AI Studio key "
            f"(see the [README]({REPO_URL}#run-it-locally))."
        )
    else:
        free_text(llm)
    about()


def free_text(llm) -> None:
    allowed, reason = free_text_allowed()
    question = st.sidebar.text_input(
        "Question", max_chars=500, disabled=not allowed, key="free_text"
    )
    if not allowed:
        st.sidebar.caption(reason)
    elif st.sidebar.button("Ask", key="ask") and question.strip():
        with st.spinner("The agent is working…"):
            result = Agent(llm, components().registry).run(question.strip())
        st.session_state["asked"] = st.session_state.get("asked", 0) + 1
        daily_counter()["count"] += 1
        st.session_state["shown"] = {"kind": "live", "question": question.strip(),
                                     "result": result.model_dump(mode="json"),
                                     "serial": st.session_state["asked"]}  # fmt: skip
        st.session_state.pop("record", None)


def about() -> None:
    st.sidebar.markdown("### About")
    st.sidebar.markdown(
        "A tool-using agent over the BI metadata of a fictional company: six tools, a plain "
        f"loop, and an abstain path. [Evaluation results]({RESULTS_URL}) · [Source]({REPO_URL})"
    )


def main() -> None:
    st.set_page_config(page_title="MetaCompass", layout="wide")
    st.markdown("## MetaCompass · BI metadata agent")
    st.markdown("`Synthetic data` — fictional company *Northwind Motors*; no real data anywhere.")
    sidebar()
    shown = st.session_state.get("shown")
    if shown is None:
        st.markdown("Pick a question on the left to see the answer and every step behind it.")
    elif shown["kind"] == "prepared":
        cache = prepared()
        entry = cache["questions"][shown["number"]]
        meta = cache["metadata"]
        note = (
            f"prepared answer recorded with {meta.get('model', '?')}, prompt "
            f"{meta.get('prompt_version', '?')}, {meta.get('date', '?')}; no model call"
        )
        show(entry["question"], entry["result"], note, view=f"prepared-{shown['number']}")
    else:
        show(shown["question"], shown["result"], "live answer", view=f"live-{shown['serial']}")
    record_viewer()


main()
