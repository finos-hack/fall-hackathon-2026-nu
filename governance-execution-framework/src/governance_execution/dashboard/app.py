"""Dashboard: FastAPI + Jinja2 + vanilla JS on port 8001. Mermaid is vendored under static/ (no CDN).

Run: ``uv run python -m governance_execution.dashboard.app`` (or ``uvicorn --factory governance_execution.dashboard.app:create_app --port 8001``).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from agip_shared.settings import Settings, get_settings

from ..store.repository import MemoryRepository
from ..store.sink import ArtifactSink
from .data import ReportStore
from .routers import api, architecture, mvp, pages, reassess, rules

HERE = Path(__file__).resolve().parent
CATALOGS = HERE.parents[3] / "rule-authoring-framework" / "catalogs"
LABEL_SCORING = "illustrative, not approved policy"
LABEL_SPECTRAL = "design-level evidence only"
PORT = 8001


def create_app(settings: Optional[Settings] = None, data_dir: Optional[Path] = None,
               build: Optional[Callable[[str], Any]] = None, catalog_paths: Optional[list[Path]] = None) -> FastAPI:
    """Build the dashboard FastAPI app and attach shared state (data dir, report store, artifact sink, catalog paths, templates, assessment builder).

    ``build(mode, **kw)`` returns a (coordinator, executor) pair; by default it comes from ``exec.factory`` and is imported lazily.
    """
    s = settings or get_settings()
    data = Path(data_dir or s.data_dir)
    repo = MemoryRepository(data)
    app = FastAPI(title="AI Governance Intelligence Platform", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.data_dir = data
    app.state.reports = ReportStore(data)
    app.state.sink = ArtifactSink(repo, data)
    app.state.catalog_paths = catalog_paths or [CATALOGS / "controls.catalog.yaml", CATALOGS / "risks.catalog.yaml"]
    if build is None:
        from ..exec import factory

        def build(mode: str, **kw: Any):
            """Default assessment builder: delegate to ``exec.factory.build`` with the app's settings, repository and data dir."""
            return factory.build(mode, settings=s, repo=repo, data_dir=data, **kw)
    app.state.build = build
    app.state.settings = s
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    # ASSET_V busts browser caches of /static/app.css when the file changes
    templates.env.globals.update(LABEL_SCORING=LABEL_SCORING, LABEL_SPECTRAL=LABEL_SPECTRAL,
                                 ASSET_V=int((HERE / "static" / "app.css").stat().st_mtime))
    app.state.templates = templates
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    app.include_router(mvp.router)
    app.include_router(rules.router)
    app.include_router(architecture.router)
    app.include_router(pages.router)
    app.include_router(reassess.router)
    app.include_router(api.router)
    return app


def main() -> None:
    """Serve the dashboard with uvicorn on 127.0.0.1 only (not exposed externally)."""
    import uvicorn
    uvicorn.run(create_app(), host="127.0.0.1", port=PORT)


if __name__ == "__main__":
    main()
