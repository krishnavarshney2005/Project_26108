"""
kartikey/api/main.py

FastAPI application entry point.

Run locally:
    cd backend
    uvicorn kartikey.api.main:app --reload --port 8000

Routers are mounted under /api/v1/.
The /health endpoint lives at root for load-balancer checks.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shared.config import settings
from shared.config import DEV_API_KEY as _SHIPPED_DEV_API_KEY
from shared.utils import AppError, get_logger

logger = get_logger(__name__)

app = FastAPI(
    title="SIH 26108 — Procurement Intelligence API",
    description=(
        "An AI-powered procurement intelligence platform that unifies fragmented "
        "standards, regulations, certifications, and procurement data into a single "
        "workflow. Helps procurement officers make faster, more accurate, transparent, "
        "and defensible decisions."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
origins = [origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()]

# allow_credentials is deliberately off. The API authenticates with an X-API-Key
# header, never a cookie, so it has nothing to gain from credentialed requests —
# and the combination it used to declare (`allow_origins=["*"]` together with
# `allow_credentials=True`) is not one the CORS spec permits. Starlette answers
# it with a literal `Access-Control-Allow-Origin: *`, which every browser then
# refuses to honour for a credentialed request, so the setting bought nothing and
# broke wildcard origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

if settings.app_env.lower().startswith("prod"):
    if settings.allowed_origins.strip() == "*":
        logger.warning(
            "CORS is open to every origin in a production environment. Set "
            "ALLOWED_ORIGINS to the deployed frontend's URL.",
        )
    if settings.api_key == _SHIPPED_DEV_API_KEY:
        logger.warning(
            "The API key is still the development default that ships in this "
            "repository, so it is public. Set API_KEY in the environment.",
        )

# ---------------------------------------------------------------------------
# API Key Protection
# ---------------------------------------------------------------------------
@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    # Skip API key check for health, docs, and OPTIONS requests
    if request.url.path in ["/health", "/docs", "/openapi.json", "/redoc"] or request.method == "OPTIONS":
        return await call_next(request)
        
    api_key = request.headers.get("X-API-Key")
    if not api_key or api_key != settings.api_key:
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized", "message": "Invalid or missing X-API-Key header"},
        )
        
    return await call_next(request)


# ---------------------------------------------------------------------------
# Global error handler — converts AppError subclasses to structured JSON
# ---------------------------------------------------------------------------
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    logger.warning("AppError [%s]: %s", exc.code, exc.message)
    return JSONResponse(
        status_code=400,
        content={"error": exc.code, "message": exc.message},
    )


# ---------------------------------------------------------------------------
# Routers
# Uncomment each router as it is implemented.
# ---------------------------------------------------------------------------

from kartikey.api.routes import documents, analyses, standards, reports, simulator, translation, procurement, extract

app.include_router(documents.router, prefix="/api/v1")
app.include_router(analyses.router,  prefix="/api/v1")
app.include_router(extract.router, prefix="/api/v1")

app.include_router(standards.router, prefix="/api/v1")
app.include_router(reports.router,   prefix="/api/v1")
app.include_router(simulator.router, prefix="/api/v1")
app.include_router(translation.router, prefix="/api/v1")
app.include_router(procurement.router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["health"])
async def health() -> dict:
    """
    Health check — confirms the server is up and returns basic stack info.
    Frontend and DevOps can poll this to verify the backend is reachable.

    Also reports live model/catalog values so the UI doesn't have to hardcode them.
    """
    from kartikey.orchestration.knowledge_registry import get_registry

    registry = get_registry()

    standards_count = None
    try:
        standards_count = registry.standards_store.count()
    except Exception:  # pragma: no cover - count is best-effort telemetry
        pass

    return {
        "status": "ok",
        "service": "sih26108-backend",
        "version": "0.1.0",
        "environment": settings.app_env,
        "retrieval_mode": registry.retrieval_mode,
        "retrieval_reason": registry.retrieval_reason,
        "gemini_model": settings.gemini_model,
        "standards_count": standards_count,
        "aiml_service_configured": bool(settings.aiml_service_url),
    }


# ---------------------------------------------------------------------------
# Startup / shutdown events
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def on_startup() -> None:
    logger.info(
        "SIH 26108 backend starting up — env=%s debug=%s",
        settings.app_env,
        settings.app_debug,
    )
    
    from kartikey.orchestration.knowledge_registry import initialize_knowledge_registry
    from shared.seed_data import get_seed_standards, get_seed_evidence
    from kartikey.api.routes.analyses import initialize_persistence

    await initialize_persistence()
    
    registry = initialize_knowledge_registry()
    
    # Load seed data (MVP vertical slice)
    for std in get_seed_standards():
        registry.standards_store.add(std)
    for ev in get_seed_evidence():
        registry.evidence_store.add(ev)
        
    logger.info(
        "Loaded seed data: %d standards, %d evidence records.",
        registry.standards_store.count(),
        registry.evidence_store.count(),
    )


@app.on_event("shutdown")
async def on_shutdown() -> None:
    logger.info("SIH 26108 backend shutting down.")
