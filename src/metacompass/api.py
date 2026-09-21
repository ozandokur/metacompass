"""HTTP API over the agent (spec §10.1): /health, /ask and /records/{record_id}.

    uvicorn metacompass.api:app

Everything a request needs is built once when the server starts (lifespan) and shared.
Only the full system is served: the ablation configurations exist to be measured, not
offered. The model client is passed in, so tests run the whole API with a scripted model;
without a configured model /ask answers 503 while records stay available. No error
response carries a stack trace or an exception message.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from metacompass.agent.llm import LLMClient
from metacompass.agent.loop import Agent, AgentResult
from metacompass.config import PROJECT_ROOT, PROMPT_VERSION, load_settings
from metacompass.retrieval.embedders import SentenceTransformerEmbedder
from metacompass.service import Components, build_components, live_llm

logger = logging.getLogger(__name__)

DATA_SEED = 42
DATA_DIR = PROJECT_ROOT / "data"
# Its own log, not eval/results/quota_log.json: that file is a committed record of the eval
# runs and must not move when someone tries the app. The provider's 429 still stops both.
APP_QUOTA_LOG = DATA_DIR / "app_quota_log.json"

# Tool error codes of get_record and the HTTP status each one means.
RECORD_ERRORS = {"NOT_FOUND": 404, "INVALID_ARGUMENT": 422}


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    config: Literal["full"] = "full"


def create_app(
    components: Components | None = None, llm: LLMClient | None = None, *, from_env: bool = False
) -> FastAPI:
    """The app. Tests pass components and a model; `from_env` builds both at start-up."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if from_env:
            settings = load_settings()
            embedder = SentenceTransformerEmbedder(settings.embedding_model)
            app.state.components = build_components(DATA_DIR, embedder)
            app.state.llm = live_llm(settings, APP_QUOTA_LOG, DATA_DIR / "cache" / "llm")
        yield

    app = FastAPI(title="MetaCompass", lifespan=lifespan)
    app.state.components = components
    app.state.llm = llm

    @app.exception_handler(Exception)
    async def hide_internals(request: Request, error: Exception) -> JSONResponse:
        # The log keeps the details; the caller learns only that it failed.
        logger.exception("request to %s failed", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "internal error"})

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "data_seed": DATA_SEED, "prompt_version": PROMPT_VERSION}

    @app.post("/ask")
    def ask(request: AskRequest) -> AgentResult:
        if app.state.llm is None:
            raise HTTPException(status_code=503, detail="no language model is configured")
        agent = Agent(app.state.llm, app.state.components.registry)
        return agent.run(request.question)

    @app.get("/records/{record_id}")
    def record(record_id: str) -> dict:
        payload, _ = app.state.components.registry.call("get_record", {"record_id": record_id})
        error = payload.get("error")
        if error:
            status = RECORD_ERRORS.get(error["code"], 500)
            detail = error["message"] if status != 500 else "internal error"
            raise HTTPException(status_code=status, detail=detail)
        return payload

    return app


app = create_app(from_env=True)
