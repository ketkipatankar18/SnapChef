"""
app.py - SnapChef Backend API (FastAPI + Pinecone)
===================================================
Updated to use Pinecone instead of ChromaDB for vector search.

Benefits over ChromaDB:
  - No local index file (image drops from 4.8GB to ~500MB)
  - No OOM issues (vectors live in Pinecone cloud)
  - Cold start drops from 3 minutes to 15 seconds
  - Scales automatically

Hybrid search still works:
  - Dense: Pinecone vector search (replaces ChromaDB)
  - Sparse: BM25 on recipes.csv (unchanged)
  - RRF merge (unchanged)
"""

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
import pandas as pd
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
from pinecone import Pinecone
from pydantic import BaseModel, ConfigDict
from typing import Optional

# ── Pydantic response model ───────────────────────────────────────────────────
class RecipeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    id:               Optional[int]   = None
    name:             Optional[str]   = None
    description:      Optional[str]   = None
    ingredients_raw:  Optional[str]   = None
    steps:            Optional[str]   = None
    servings:         Optional[float] = None

# ── Config ────────────────────────────────────────────────────────────────────
CSV_PATH         = "services/ChromaDB/recipes.csv"   # still needed for BM25
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY", "")
INDEX_NAME       = "snapchef-recipes"

# ── Global resources ──────────────────────────────────────────────────────────
RECIPES_DF    = None
BM25_DF       = None
BM25_INDEX    = None
model         = None
pinecone_index = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global RECIPES_DF, BM25_DF, BM25_INDEX, model, pinecone_index

    print("Loading SnapChef backend resources...", flush=True)

    try:
        RECIPES_DF = pd.read_csv(CSV_PATH)
        print(f"  ✓ Loaded {len(RECIPES_DF)} recipes from CSV", flush=True)
    except Exception as e:
        print(f"  ✗ CSV load failed: {e}", flush=True)
        raise

    try:
        pc = Pinecone(api_key=PINECONE_API_KEY)
        pinecone_index = pc.Index(INDEX_NAME)
        stats = pinecone_index.describe_index_stats()
        print(f"  ✓ Connected to Pinecone — {stats.total_vector_count} vectors indexed", flush=True)
    except Exception as e:
        print(f"  ✗ Pinecone connection failed: {e}", flush=True)
        raise

    try:
        model = SentenceTransformer("all-MiniLM-L6-v2")
        print("  ✓ Embedding model loaded (all-MiniLM-L6-v2)", flush=True)
    except Exception as e:
        print(f"  ✗ Model load failed: {e}", flush=True)
        raise

    try:
        def build_recipe_text(row):
            name        = str(row.get("name", ""))
            description = str(row.get("description", ""))
            ingredients = str(row.get("ingredients_raw", ""))
            return f"{name} {description} {ingredients}".lower().split()

        # RECIPE_CORPUS = [build_recipe_text(row) for _, row in RECIPES_DF.iterrows()]
        # BM25_INDEX    = BM25Okapi(RECIPE_CORPUS)
        # print("  ✓ BM25 index built", flush=True)

        # Sample 50k recipes for BM25 — builds in ~30s vs 5min for 500k
        # Pinecone handles full 500k for dense search, BM25 is keyword fallback
        BM25_DF       = RECIPES_DF.sample(n=50000, random_state=42) if len(RECIPES_DF) > 50000 else RECIPES_DF
        RECIPE_CORPUS = [build_recipe_text(row) for _, row in BM25_DF.iterrows()]
        BM25_INDEX    = BM25Okapi(RECIPE_CORPUS)
        print(f"  ✓ BM25 index built ({len(BM25_DF)} recipes)", flush=True)

    except Exception as e:
        print(f"  ✗ BM25 build failed: {e}", flush=True)
        raise

    print("Backend ready.\n", flush=True)
    yield
    print("Shutting down SnapChef backend...", flush=True)

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="SnapChef Recipe Search API",
    description="Hybrid search (BM25 + Pinecone dense retrieval) for recipe recommendations",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    stats = pinecone_index.describe_index_stats() if pinecone_index else {}
    return {
        "status":        "healthy",
        "recipes":       len(RECIPES_DF) if RECIPES_DF is not None else 0,
        "vectors":       stats.total_vector_count if stats else 0,
        "vector_store":  "pinecone",
    }

# ── Hybrid search ─────────────────────────────────────────────────────────────
def hybrid_search(query_text: str, n_results: int = 10) -> list[dict]:
    """
    Hybrid search combining Pinecone dense retrieval and BM25 keyword search.
    Same RRF merge as before — only the dense retrieval changed from ChromaDB to Pinecone.
    """
    CANDIDATE_POOL = n_results * 4

    # ── Dense retrieval via Pinecone ──────────────────────────────────────────
    # Same concept as ChromaDB query — encode query, find nearest vectors
    # Difference: vectors live in Pinecone cloud, not local disk
    query_embedding = model.encode([query_text])[0].tolist()
    pinecone_results = pinecone_index.query(
        vector=query_embedding,
        top_k=CANDIDATE_POOL,
        include_metadata=False,  # we get full details from CSV
    )
    dense_ids = [int(match.id) for match in pinecone_results.matches]

    # ── BM25 keyword retrieval ────────────────────────────────────────────────
    # Unchanged from ChromaDB version
    tokenized_query  = query_text.lower().split()
    bm25_scores      = BM25_INDEX.get_scores(tokenized_query)
    bm25_top_indices = bm25_scores.argsort()[-CANDIDATE_POOL:][::-1].tolist()
    # bm25_ids         = [int(RECIPES_DF.iloc[i]["id"]) for i in bm25_top_indices]
    bm25_ids = [int(BM25_DF.iloc[i]["id"]) for i in bm25_top_indices]
    
    # ── Reciprocal Rank Fusion ────────────────────────────────────────────────
    # Unchanged
    k = 60
    rrf_scores: dict[int, float] = {}
    for rank, recipe_id in enumerate(dense_ids):
        rrf_scores[recipe_id] = rrf_scores.get(recipe_id, 0) + 1 / (rank + k)
    for rank, recipe_id in enumerate(bm25_ids):
        rrf_scores[recipe_id] = rrf_scores.get(recipe_id, 0) + 1 / (rank + k)

    top_ids = sorted(rrf_scores, key=rrf_scores.get, reverse=True)[:n_results]
    print(f"Hybrid search ids: {top_ids}")

    matched_df = RECIPES_DF[RECIPES_DF["id"].isin(top_ids)]
    return matched_df.to_dict(orient="records")

# ── Search endpoint ───────────────────────────────────────────────────────────
@app.get(
    "/search",
    response_model=list[RecipeResponse],
    summary="Search recipes using hybrid retrieval",
    description="Combines Pinecone dense search and BM25 keyword search via RRF",
)
async def search(
    query: str = Query(..., description="Search query"),
    n:     int = Query(10, description="Number of recipes to return", ge=1, le=50),
):
    if not query.strip():
        raise HTTPException(status_code=400, detail="Missing 'query' parameter")
    recipes = hybrid_search(query_text=query, n_results=n)
    return recipes

# ── Run directly ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)