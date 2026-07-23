"""
migrate_to_pinecone.py
======================
One-time script to migrate embeddings from ChromaDB to Pinecone.

What this does:
1. Reads all vectors from your local ChromaDB (already computed, no GPU needed)
2. Reads recipe metadata from recipes.csv
3. Uploads everything to Pinecone in batches

Run once:
  python migrate_to_pinecone.py

After this script succeeds, your Pinecone index has all recipe embeddings
and you never need to run it again.
"""

import tomllib
import pandas as pd
import chromadb
from pathlib import Path
from pinecone import Pinecone, ServerlessSpec

# ── Config ────────────────────────────────────────────────────────────────────
secrets_path = Path(".streamlit/secrets.toml")
with open(secrets_path, "rb") as f:
    secrets = tomllib.load(f)

PINECONE_API_KEY = secrets.get("PINECONE_API_KEY", "")
CHROMA_PATH      = "services/ChromaDB/dataset"
CSV_PATH         = "services/ChromaDB/recipes.csv"
INDEX_NAME       = "snapchef-recipes"
BATCH_SIZE = 500

if not PINECONE_API_KEY:
    print("ERROR: PINECONE_API_KEY not found in secrets.toml")
    exit(1)

# ── Connect to ChromaDB ───────────────────────────────────────────────────────
print("Connecting to ChromaDB...")
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection    = chroma_client.get_collection(name="my_collection")
total         = collection.count()
print(f"Found {total} vectors in ChromaDB")

# ── Load recipes CSV for metadata ─────────────────────────────────────────────
# Pinecone stores metadata alongside vectors so we can return recipe details
# without a separate database lookup
print("Loading recipes.csv...")
df = pd.read_csv(CSV_PATH)
print(f"Loaded {len(df)} recipes")

# Build a lookup dict: recipe_id → metadata dict
# We store key fields so the search endpoint can return recipe details
# directly from Pinecone without hitting the CSV
recipe_lookup = {}
for _, row in df.iterrows():
    recipe_id = str(int(row["id"]))
    recipe_lookup[recipe_id] = {
        "name":             str(row.get("name", "")),
        "description":      str(row.get("description", ""))[:500],  # truncate long descriptions
        "ingredients_raw":  str(row.get("ingredients_raw", "")),
        "steps":            str(row.get("steps", ""))[:1000],        # truncate long steps
        # "servings":         float(row.get("servings", 0) or 0),
        "servings": float(row.get("servings", 0) or 0) if pd.notna(row.get("servings")) else 0.0,
    }

# ── Connect to Pinecone ───────────────────────────────────────────────────────
print("Connecting to Pinecone...")
pc    = Pinecone(api_key=PINECONE_API_KEY)
existing_indexes = [idx.name for idx in pc.list_indexes()]
if INDEX_NAME not in existing_indexes:
    print(f"Creating Pinecone index '{INDEX_NAME}'...")
    pc.create_index(
        name=INDEX_NAME,
        dimension=384,        # all-MiniLM-L6-v2 output dimension
        metric="cosine",
        spec=ServerlessSpec(
            cloud="aws",
            region="us-east-1"
        )
    )
    print(f"Index '{INDEX_NAME}' created")
else:
    print(f"Index '{INDEX_NAME}' already exists")
index = pc.Index(INDEX_NAME)
print(f"Connected to index: {INDEX_NAME}")
print(f"Index stats before migration: {index.describe_index_stats()}")

# ── Extract vectors from ChromaDB in batches ──────────────────────────────────
# ChromaDB stores: ids, embeddings, metadatas
# We fetch in batches of BATCH_SIZE to avoid memory issues
print(f"\nMigrating {total} vectors to Pinecone...")
print(f"Batch size: {BATCH_SIZE}")

migrated = 0
errors   = 0

# Get all IDs first
all_ids = collection.get(include=[])["ids"]

for i in range(0, len(all_ids), BATCH_SIZE):
    batch_ids = all_ids[i:i + BATCH_SIZE]

    # Fetch embeddings for this batch from ChromaDB
    batch_data = collection.get(
        ids=batch_ids,
        include=["embeddings"]
    )

    # Build Pinecone upsert format: list of (id, vector, metadata) tuples
    vectors_to_upsert = []
    for j, chroma_id in enumerate(batch_data["ids"]):
        embedding = batch_data["embeddings"][j]
        metadata  = recipe_lookup.get(chroma_id, {})

        # vectors_to_upsert.append({
        #     "id":     chroma_id,          # recipe ID as string
        #     "values": embedding,           # 384-dim float vector
        #     "metadata": metadata           # recipe details
        # })

        vectors_to_upsert.append({
            "id":     chroma_id,
            # convert numpy array to plain Python list of floats
            "values": [float(v) for v in embedding],
            "metadata": {
                k: float(v) if hasattr(v, 'item') else str(v) if v is not None else ""
                for k, v in metadata.items()
            }
        })

    # Upload batch to Pinecone
    try:
        index.upsert(vectors=vectors_to_upsert)
        migrated += len(vectors_to_upsert)
        print(f"  Uploaded {migrated}/{total} vectors")
    except Exception as e:
        print(f"  ⚠️  Batch {i//BATCH_SIZE + 1} failed: {e}")
        errors += len(vectors_to_upsert)

# ── Final stats ───────────────────────────────────────────────────────────────
print(f"\n{'='*50}")
print(f"Migration complete!")
print(f"  Migrated: {migrated}")
print(f"  Errors:   {errors}")
print(f"\nPinecone index stats after migration:")
print(index.describe_index_stats())
print(f"\nNext step: update services/app.py to use Pinecone")