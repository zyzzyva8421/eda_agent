"""FastAPI application entry point."""

from __future__ import annotations

import logging

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from eda_agent.api.routers.agent_router import router as agent_router
from eda_agent.api.routers.auth_router import router as auth_router
from eda_agent.api.routers.metrics_router import router as metrics_router
from eda_agent.api.routers.runs_router import router as runs_router
from eda_agent.config import settings

# Configure structured logging
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, settings.log_level.upper(), logging.INFO)
    )
)

app = FastAPI(
    title="EDA Agent API",
    description="LLM-driven EDA agent for PPA/parameter tuning.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(runs_router)
app.include_router(agent_router)
app.include_router(metrics_router)


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


def cli_main() -> None:
    """CLI entry point: launch the Uvicorn server."""
    import uvicorn

    uvicorn.run(
        "eda_agent.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )
