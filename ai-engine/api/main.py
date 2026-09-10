"""
ai-engine/api/main.py

FastAPI entrypoint for the StandIQ AI Engine.

Endpoints:
  GET  /          — welcome message
  GET  /health    — liveness check (Render health probe)
  POST /analyze   — per-requirement compliance analysis (called by backend)
  POST /recommend — end-to-end standard recommendation from a free-text query
"""

import logging
import os

# ---------------------------------------------------------------------------
# OpenMP safety — MUST run before faiss / torch / lightgbm are imported
# (i.e. before `from src.recommender import Recommender` below). Those wheels
# each bundle their own copy of libomp; initialising a second OpenMP runtime
# in a single process aborts with SIGSEGV on macOS. This flag lets them
# coexist. Pinning to one thread also trims memory + thread oversubscription
# on the 512 MB Render box. setdefault() so an explicit env var still wins.
# ---------------------------------------------------------------------------
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

from src.reasoning.analyzer import Analyzer
from src.recommender import Recommender

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

import threading
from contextlib import asynccontextmanager

# ---------------------------------------------------------------------------
# Global singletons
# ---------------------------------------------------------------------------
analyzer: Analyzer = None
recommender: Recommender = None
startup_status: str = "starting"

def load_recommender():
    """Background thread function to load Recommender without blocking the API."""
    global recommender, startup_status
    try:
        logger.info("Background thread starting Recommender (generating embeddings if not cached)...")
        recommender = Recommender()
        startup_status = "ok" if recommender.retriever else "error"
        logger.info("Background loading finished. Status: %s", startup_status)
    except Exception as e:
        logger.error("Error loading Recommender in background: %s", e)
        startup_status = "error"

@asynccontextmanager
async def lifespan(app: FastAPI):
    global analyzer, recommender, startup_status
    logger.info("Lifespan starting — Initialising Analyzer…")
    analyzer = Analyzer()

    if os.getenv("SKIP_RECOMMENDER", "").lower() == "true":
        # Combined-service mode: /recommend is unused; skip the 300+ MB Recommender
        # (FAISS index + BM25 + numpy embeddings) so the combined backend+ai-engine
        # process fits within Render Free 512 MB.
        # We still need the applicability ML model loaded for MLReasoner to work.
        logger.info("SKIP_RECOMMENDER=true — loading applicability model directly (no Recommender).")
        try:
            import os as _os
            from src.ml.applicability_model import load_applicability_model
            _root = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", ".."))
            load_applicability_model(
                model_path=_os.path.join(_root, "standiq_applicability_model_v2.joblib"),
                metadata_path=_os.path.join(_root, "standiq_applicability_model_v2_metadata.json"),
            )
            logger.info("Applicability model loaded (SKIP_RECOMMENDER path).")
        except Exception as exc:
            logger.error("Failed to load applicability model in SKIP_RECOMMENDER mode: %s", exc)
        startup_status = "ok"
    else:
        # Start recommender in a background thread so FastAPI can bind to the port
        # and answer /health checks immediately.
        startup_status = "starting"
        thread = threading.Thread(target=load_recommender, daemon=True)
        thread.start()

    yield

    logger.info("Lifespan shutting down.")

app = FastAPI(
    title="StandIQ AI Engine",
    description="BIS standards recommendation and compliance analysis engine",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — allow backend and frontend origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request / Response models for /analyze
# ---------------------------------------------------------------------------
class Requirement(BaseModel):
    id: str
    analysis_id: str
    text: str
    normalized_text: Optional[str] = None
    category: str = "other"
    is_reference: Optional[str] = None
    cited_year: Optional[int] = None
    relevance_score: Optional[float] = None
    semantic_score: Optional[float] = None

    cited_designation: Optional[str] = None
    location: Optional[str] = None
    page: Optional[int] = None
    extracted_at: Optional[str] = None
    extraction_confidence: Optional[float] = None
    from_corrigendum: bool = False
    corrigendum_number: Optional[int] = None

class Standard(BaseModel):
    id: str
    is_number: str
    title: str
    status: str
    year: Optional[int] = None
    relevance_score: Optional[float] = None
    semantic_score: Optional[float] = None


class AimlRequest(BaseModel):
    analysis_id: str
    extracted_text: str
    requirements: List[Requirement]
    retrieved_standards: List[Standard]

class AimlFinding(BaseModel):
    finding_id: str
    requirement_id: str
    verdict: str
    reason: str
    recommended_action: Optional[str] = None
    applicable_standard_ids: List[str] = []
    evidence_ids: List[str] = []
    confidence: float

class AimlResponse(BaseModel):
    analysis_id: str
    findings: List[AimlFinding]
    extraction_metadata: Dict[str, Any] = Field(default_factory=dict)

# ---------------------------------------------------------------------------
# Request / Response models for /recommend
# ---------------------------------------------------------------------------
class RecommendRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=2000,
                       description="Free-text procurement query or tender excerpt")
    top_k: int = Field(default=5, ge=1, le=20,
                       description="Number of standards to return")

class RecommendResponse(BaseModel):
    query: str
    query_understanding: Dict[str, Any] = {}
    recommendations: List[Dict[str, Any]] = []
    related_standards: List[str] = []
    test_methods: List[str] = []
    safety_standards: List[str] = []
    normative_references: List[str] = []
    potential_gaps: List[Dict[str, Any]] = []
    currentness: Dict[str, Any] = {}
    additional_currentness: Dict[str, Any] = {}
    confidence: str = "low"
    error: Optional[str] = None

class CompareRequest(BaseModel):
    standard_ids: List[str] = Field(..., min_length=2, max_length=5, description="List of IS numbers to compare")

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    cnt = len(recommender.standards) if recommender else 0
    return {
        "service": "StandIQ AI Engine",
        "version": "2.0.0",
        "endpoints": ["/health", "/analyze", "/recommend", "/compare"],
        "standards_indexed": cnt,
        "startup_status": startup_status,
    }

from src.compare import compare_standards

@app.post("/compare")
def compare(request: CompareRequest):
    """
    Compares two or more standard IDs by querying the Gemini model with
    the curated knowledge base data.
    """
    if startup_status != "ok":
        raise HTTPException(status_code=503, detail="AI Engine is still loading knowledge base. Please try again in a moment.")

    try:
        result = compare_standards(request.standard_ids, recommender.standards)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Compare endpoint failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/health")
def health():
    """Liveness check — Render uses this to confirm the service is up."""
    # We return HTTP 200 even if 'starting', so Render doesn't kill the container
    # before embeddings are done generating.
    return {
        "status": "ok" if startup_status == "ok" else startup_status,
        "recommender_ready": recommender is not None and recommender.retriever is not None,
        "standards_count": len(recommender.standards) if recommender else 0,
        "analyzer_mode": getattr(analyzer, "_mode", "unknown") if analyzer else "unknown",
    }


@app.post("/analyze", response_model=AimlResponse)
def analyze(request: AimlRequest):
    """
    Per-requirement compliance analysis.
    Called by the StandIQ backend with pre-extracted requirements and pre-retrieved standards.
    """
    try:
        response = analyzer.process(request)
        return response
    except Exception as exc:
        logger.error("Analysis failed for analysis_id=%s: %s", request.analysis_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/recommend")
def recommend(request: RecommendRequest):
    """
    End-to-end BIS standards recommendation from a free-text procurement query.

    Uses hybrid BM25 + semantic retrieval, Gemini query understanding,
    deterministic currentness checking, and structured gap detection.
    """
    if startup_status != "ok":
        raise HTTPException(status_code=503, detail="Recommender is still starting up. Please try again in a moment.")

    try:
        result = recommender.recommend(request.query, top_k=request.top_k)
        if "error" in result:
            raise HTTPException(status_code=503, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Recommend endpoint failed for query='%s': %s", request.query[:80], exc)
        raise HTTPException(status_code=500, detail=str(exc))
