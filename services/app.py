# app.py - SnapChef Backend API (FastAPI + Pinecone)

# Import libraries
import os
import tomllib
import pandas as pd
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
from pinecone import Pinecone
from pydantic import BaseModel, ConfigDict


# Pydantic response model - define the recipe class
class RecipeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    id:               Optional[int]   = None
    name:             Optional[str]   = None
    description:      Optional[str]   = None
    ingredients_raw:  Optional[str]   = None
    steps:            Optional[str]   = None
    servings:         Optional[float] = None

def load_pinecone_key():
    # First check environment variable (used in Azure/Docker)
    key = os.environ.get("PINECONE_API_KEY", "")
    if key:
        return key
    # Fallback to local secrets.toml (used in local dev)
    secrets_path = Path(".streamlit/secrets.toml")
    if secrets_path.exists():
        with open(secrets_path, "rb") as f:
            secrets = tomllib.load(f)
        return secrets.get("PINECONE_API_KEY", "")
    return ""

# Configurations
CSV_PATH         = "services/ChromaDB/recipes.csv"   # still needed for BM25
PINECONE_API_KEY = load_pinecone_key()
INDEX_NAME       = "snapchef-recipes"

# Define Global variable 
RECIPES_DF    = None
BM25_DF       = None
BM25_INDEX    = None
model         = None
pinecone_index = None

# Lifespan content manager
# The lifespan replaces Flask's module-level loading. 
# Everything expensive (loading models, connecting to databases) 
# runs once when the server starts, not on every request.
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Define all global variables
    # global declarations are necessary because Python functions create their own scope
    global RECIPES_DF, BM25_DF, BM25_INDEX, model, pinecone_index
    try:
        # Load the recipe CSV
        RECIPES_DF = pd.read_csv(CSV_PATH)
        print(f"Loaded {len(RECIPES_DF)} recipes from CSV", flush=True)
    except Exception as e:
        print(f"CSV load failed: {e}", flush=True)
        raise

    # Connect to Pinecone
    try:
        pc = Pinecone(api_key=PINECONE_API_KEY)
        pinecone_index = pc.Index(INDEX_NAME)
        stats = pinecone_index.describe_index_stats()
        print(f"Connected to Pinecone — {stats.total_vector_count} vectors indexed", flush=True)
    except Exception as e:
        print(f"Pinecone connection failed: {e}", flush=True)
        raise
    
    # Load the embedding model
    try:
        model = SentenceTransformer("all-MiniLM-L6-v2")
        print("Embedding model loaded (all-MiniLM-L6-v2)", flush=True)
    except Exception as e:
        print(f"Model load failed: {e}", flush=True)
        raise

    try:
        def build_recipe_text(row):
            name        = str(row.get("name", ""))
            description = str(row.get("description", ""))
            ingredients = str(row.get("ingredients_raw", ""))
            return f"{name} {description} {ingredients}".lower().split()

        # Sample 50k recipes for BM25
        # Pinecone handles full 500k for dense search, BM25 is keyword fallback
        BM25_DF       = RECIPES_DF.sample(n=50000, random_state=42) if len(RECIPES_DF) > 50000 else RECIPES_DF
        RECIPE_CORPUS = [build_recipe_text(row) for _, row in BM25_DF.iterrows()]
        BM25_INDEX    = BM25Okapi(RECIPE_CORPUS)
        print(f"BM25 index built ({len(BM25_DF)} recipes)", flush=True)
    except Exception as e:
        print(f"BM25 build failed: {e}", flush=True)
        raise

    print("Backend ready.\n", flush=True)
    # This is where the server actually runs 
    # Everything before yield is startup
    # Everything after is shutdown
    yield
    print("Shutting down SnapChef backend...", flush=True)

# FastAPI app
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

# Health check 
@app.get("/health")
async def health():
    stats = pinecone_index.describe_index_stats() if pinecone_index else {}
    return {
        "status":        "healthy",
        "recipes":       len(RECIPES_DF) if RECIPES_DF is not None else 0,
        "vectors":       stats.total_vector_count if stats else 0,
        "vector_store":  "pinecone",
    }

# Hybrid search
def hybrid_search(query_text: str, n_results: int = 10) -> list[dict]:
    """
    Hybrid search combining Pinecone dense retrieval and BM25 keyword search.
    Same RRF merge as before — only the dense retrieval changed from ChromaDB to Pinecone.
    """
    CANDIDATE_POOL = n_results * 4

    # Dense retrieval via Pinecone
    # Same concept as ChromaDB query, encode query, find nearest vectors
    # Difference: vectors live in Pinecone cloud, not local disk
    query_embedding = model.encode([query_text])[0].tolist()
    pinecone_results = pinecone_index.query(
        vector=query_embedding,
        top_k=CANDIDATE_POOL,
        include_metadata=False,  # we get full details from CSV
    )
    dense_ids = [int(match.id) for match in pinecone_results.matches]

    # BM25 keyword retrieval
    # Unchanged from ChromaDB version
    tokenized_query  = query_text.lower().split()
    bm25_scores      = BM25_INDEX.get_scores(tokenized_query)
    bm25_top_indices = bm25_scores.argsort()[-CANDIDATE_POOL:][::-1].tolist()
    # bm25_ids         = [int(RECIPES_DF.iloc[i]["id"]) for i in bm25_top_indices]
    bm25_ids = [int(BM25_DF.iloc[i]["id"]) for i in bm25_top_indices]
    
    # Reciprocal Rank Fusion
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

# Search endpoint
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

# Main
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)