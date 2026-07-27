# 🍳 SnapChef — AI-Powered Recipe Generation from Your Ingredients

[![See It In Action](https://img.shields.io/badge/Live%20Demo-snapchef--app.streamlit.app-orange)](https://snapchef-app.streamlit.app)
[![API Health](https://img.shields.io/badge/API-Azure%20Container%20Apps-blue)](https://snapchef-api.politesea-1ef3c6e3.eastus.azurecontainerapps.io/health)

Ever opened your fridge and had no idea what to cook? SnapChef solves that. Tell it what ingredients you have and it generates a custom recipe using only what's in your kitchen, no grocery runs needed.

---

## Demo

![SnapChef Demo](/Assets/Demo2x.gif)

*Live demo of SnapChef generating a recipe from available ingredients with follow-up customisation.*

---

## Live Application

| Component | URL |
|-----------|-----|
| Frontend (Streamlit) | [snapchef-app.streamlit.app](https://snapchef-app.streamlit.app) |
| Backend API | [snapchef-api.../health](https://snapchef-api.politesea-1ef3c6e3.eastus.azurecontainerapps.io/health) |
| API Docs (Swagger) | [snapchef-api.../docs](https://snapchef-api.politesea-1ef3c6e3.eastus.azurecontainerapps.io/docs) |

---

## Architecture

![SnapChef Architecture](/Assets/Software_Arch.png)

```
User (Browser)
    ↓ HTTPS
Streamlit Frontend (Streamlit Community Cloud)
    ↓ HTTP GET /search
FastAPI Backend (Azure Container Apps)
    ↓                        ↓
BM25 Index (in-memory)   Pinecone Vector DB (500,471 vectors)
    ↓                        ↓
         Reciprocal Rank Fusion (RRF)
         Top 10 recipes retrieved
              ↓
         GPT-4o Recipe Generation
              ↓
    Streaming response to user
```

---

## Features

- **Google OAuth Authentication** — secure login with cookie persistence across sessions
- **Hybrid Search** — BM25 keyword search + Pinecone dense retrieval merged via RRF
- **500,471 recipes indexed** — full Food.com dataset embedded and searchable
- **Ingredient gap detection** — suggests missing ingredients before generating
- **GPT-4o recipe generation** — strict ingredient constraint enforcement with streaming output
- **Multi-turn follow-up chat** — refine recipes with natural language ("make it spicier", "make it vegan")
- **Intent classification guardrail** — off-topic messages redirected before hitting GPT-4o
- **Appliance detection** — flags kitchen appliances the recipe requires
- **Human-in-the-loop feedback** — thumbs up/down logged for quality analysis
- **Cross-encoder reranking** — available locally (disabled in cloud for memory optimisation)

---

## Evaluation Results

### RAGAS Retrieval Evaluation (51 synthetic test cases)

| Metric | Score |
|--------|-------|
| Faithfulness | 0.844 |
| Answer Relevancy | 0.804 |
<!-- | Context Recall | 0.340 | -->
<!-- | Context Precision | 0.305 | -->

Test set generated using RAGAS `TestsetGenerator` with 7 domain-specific personas from 400 sampled recipes, evaluated against the live hybrid retrieval pipeline (BM25 + Pinecone, top-10, RRF k=60).

### LLM-as-Judge Generation Evaluation (19 golden test cases)

| Metric | OpenAI Judge (GPT-4o-mini) | Anthropic Judge (Claude Haiku) |
|--------|---------------------------|-------------------------------|
| Ingredient Faithfulness | 4.74 / 5 | 4.84 / 5 |
| Coherence | 5.00 / 5 | 5.00 / 5 |
| Relevance | 4.89 / 5 | 5.00 / 5 |
| Completeness | 5.00 / 5 | 5.00 / 5 |
| **Overall** | **4.92 / 5** | **4.96 / 5** |

Cross-provider scores differ by only 0.04 on overall — consistent results across independent judges confirm no self-evaluation bias.

---

## Repository Structure

```
SnapChef/
├── apps/
│   ├── Home.py                      # Streamlit frontend — login, ingredient input
│   └── pages/
│       └── GenerateRecipe.py        # Recipe generation, follow-up chat, feedback
│
├── services/
│   ├── app.py                       # FastAPI backend — hybrid search endpoint
│   ├── requirements.txt             # Backend-only dependencies for Docker
│   └── ChromaDB/
│       └── recipes.csv              # Food.com dataset (500,471 recipes)
│
├── terraform/
│   ├── main.tf                      # Azure resources (Container App, ACR, etc.)
│   ├── variables.tf                 # Input variable definitions
│   ├── outputs.tf                   # Post-deploy URLs and names
│   └── terraform.tfvars             # Your actual values (gitignored)
│
├── Assets/
│   ├── Demo2x.gif                   # App demo
│   └── Software_Arch.png            # Architecture diagram
│
├── generate_embedding.ipynb         # One-time: embed recipes into ChromaDB
├── migrate_to_pinecone.py           # One-time: migrate ChromaDB → Pinecone
├── generate_testset.py              # RAGAS synthetic test set generation
├── run_eval_ragas_synthetic.py      # RAGAS evaluation runner
├── llm_as_judge.py                  # LLM-as-judge evaluation (Pattern 1)
├── golden_test_set.json             # 20 hand-crafted test cases
├── Dockerfile                       # Backend container image
├── .dockerignore                    # Excludes ChromaDB binary files from image
├── deploy.sh                        # Full deployment script
└── requirements.txt                 # Root dependencies for local dev
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Streamlit, Google OAuth2, streamlit-cookies-manager |
| Backend | FastAPI, Uvicorn, Pydantic |
| Vector Store | Pinecone (serverless, AWS us-east-1, 500,471 vectors, dim=384) |
| Embedding Model | all-MiniLM-L6-v2 (sentence-transformers) |
| Keyword Search | BM25 (rank-bm25), 50,000 recipe sample |
| Search Fusion | Reciprocal Rank Fusion (RRF, k=60) |
| Reranking | cross-encoder/ms-marco-MiniLM-L-6-v2 (local only) |
| LLM Generation | GPT-4o (streaming) |
| LLM Classification | GPT-4o-mini (intent classifier, missing ingredient detection) |
| Conversation Memory | LangChain RunnableWithMessageHistory + InMemoryChatMessageHistory |
| Evaluation | RAGAS, LLM-as-judge (OpenAI + Anthropic cross-validation) |
| Infrastructure | Terraform, Azure Container Apps, Azure Container Registry |
| CI/CD | Docker Buildx (linux/amd64 cross-compilation) |

---

## How It Works

### 1. Retrieval — Hybrid Search

When a user submits ingredients, SnapChef runs two parallel searches:

**Dense search (Pinecone):** The query is encoded into a 384-dimensional vector using `all-MiniLM-L6-v2`. Pinecone finds the 40 nearest vectors across 500,471 embedded recipes using approximate nearest neighbour search.

**Keyword search (BM25):** The query is tokenised and scored against 50,000 recipes using Best Match 25 — a classic IR algorithm that rewards exact ingredient name matches and rare terms.

**RRF merge:** Both ranked lists are merged using Reciprocal Rank Fusion (`score = Σ 1/(rank + 60)`). Recipes appearing highly in both lists win. Top 10 returned.

### 2. Gap Detection

The retrieved recipes are compared against the user's ingredient list by GPT-4o-mini. Any ingredients in the recipes that the user doesn't have are surfaced as suggestions — the user can select which they actually have before generation.

### 3. Generation

GPT-4o receives the top 10 recipes as context and generates a custom recipe following strict rules: only use listed ingredients, handle culinary incompatibilities gracefully, assume water is always available, respond with warmth if ingredients are too limited.

### 4. Follow-up

Every follow-up message is first classified by GPT-4o-mini (add_ingredient / substitute / dietary_restriction / serving_change / recipe_tweak / off_topic). Off-topic messages are redirected. Valid requests update the recipe using the full conversation history via LangChain's message history.

---

## Evaluation Framework

### RAGAS (Retrieval Quality)

Measures whether the retrieval pipeline finds recipes that actually contain the information needed to answer the user's query. Four metrics: faithfulness, answer relevancy, context recall, context precision.

Test set generated synthetically using RAGAS `TestsetGenerator` with 7 domain-specific personas (limited ingredients, time constraints, dietary restrictions, serving size variations) from 400 sampled recipes.

### LLM-as-Judge (Generation Quality)

Pattern 1 — single score with reasoning. GPT-4o-mini and Claude Haiku independently score each generated recipe on a 0-5 rubric across 4 criteria. Cross-provider validation confirms scores are consistent and not inflated by self-evaluation bias.

### Human-in-the-Loop

Thumbs up/down feedback logged to `eval_results/user_feedback.csv` with timestamp, ingredients, cooking time, and recipe snippet. Provides real user signals as online quality metrics.

---

## Local Setup

### Prerequisites
- Python 3.11+
- Docker Desktop
- OpenAI API key
- Pinecone API key
- Google OAuth credentials

### 1. Clone and install

```bash
git clone https://github.com/ketkipatankar18/SnapChef.git
cd SnapChef
pip install -r requirements.txt
```

### 2. Configure secrets

Create `apps/.streamlit/secrets.toml`:

```toml
OPEN_AI_API_KEY      = "sk-proj-..."
ANTHROPIC_API_KEY    = "sk-ant-..."
PINECONE_API_KEY     = "pcsk_..."
GOOGLE_CLIENT_ID     = "your-client-id"
GOOGLE_CLIENT_SECRET = "your-client-secret"
PASSWORD             = "any-string-for-cookie-encryption"
BACKEND_URL          = "http://127.0.0.1:8000"
REDIRECT_URI         = "http://localhost:8501"
```

### 3. Start the backend

```bash
python services/app.py
```

Startup loads `recipes.csv` (500k rows), connects to Pinecone, loads the embedding model, and builds the BM25 index. Takes 60-90 seconds on first run.

### 4. Start the frontend

```bash
streamlit run apps/Home.py
```

Open [http://localhost:8501](http://localhost:8501).

---

## Cloud Deployment

Infrastructure is provisioned with Terraform on Azure.

### Prerequisites
- Azure CLI (`az login`)
- Terraform (`brew install hashicorp/tap/terraform`)
- Docker Desktop

### Deploy

```bash
# 1. Provision Azure infrastructure
cd terraform
terraform init
terraform apply

# 2. Build and push Docker image (Apple Silicon cross-compile)
cd ..
az acr login --name snapchefacr

docker buildx build \
  --platform linux/amd64 \
  -t snapchefacr.azurecr.io/snapchef-api:latest \
  --push \
  -f Dockerfile .

# 3. Update Container App
az containerapp update \
  --name snapchef-api \
  --resource-group snapchef-rg \
  --image snapchefacr.azurecr.io/snapchef-api:latest
```

### Azure Resources Created

| Resource | Type | Purpose |
|----------|------|---------|
| snapchef-rg | Resource Group | Logical container for all resources |
| snapchefacr | Container Registry | Stores Docker images |
| snapchef-logs | Log Analytics Workspace | Centralised logging |
| snapchef-env | Container Apps Environment | Runtime cluster |
| snapchef-api | Container App | FastAPI backend (1 vCPU, 2GB RAM) |

---

## Running Evaluations

```bash
# Generate synthetic test set (requires OpenAI key)
python generate_testset.py --n 51 --max 400

# Run RAGAS evaluation
python run_eval_ragas_synthetic.py

# Run LLM-as-judge (OpenAI)
JUDGE_PROVIDER=openai python llm_as_judge.py

# Run LLM-as-judge (Anthropic cross-validation)
JUDGE_PROVIDER=anthropic python llm_as_judge.py
```

Results saved to `eval_results/` and `evallm_as_judge_results/`.

---

## Key Design Decisions

**Why Pinecone over ChromaDB?**
ChromaDB embeds the 3.5GB vector index inside the Docker image. In Azure's 2GB RAM container, loading it causes OOMKilled errors. Pinecone hosts vectors externally — the container only needs an API connection, reducing the image from 4.87GB to 1.1GB.

**Why hybrid search?**
Dense search misses exact ingredient names ("tahini" may not be near "sesame paste" in vector space). BM25 misses paraphrases ("spicy food" doesn't keyword-match "jalapeño"). Together they cover what the other misses.

**Why cross-encoder reranking is disabled in cloud?**
The cross-encoder loads PyTorch a second time alongside sentence-transformers, pushing RAM usage beyond 2GB. Disabled in Azure, available locally. Noted as a future improvement pending further memory optimisation.

**Why BM25 uses 50k sample?**
Building BM25 requires reading the full corpus into memory at startup. 500k recipes takes 5+ minutes exceeding Azure's startup probe timeout. 50k builds in ~30 seconds with minimal quality impact since BM25 is the keyword fallback — Pinecone handles primary search across all 500k.

---

## Dataset

[Food.com Recipes](https://www.kaggle.com/datasets/realalexanderwei/food-com-recipes-with-ingredients-and-tags) — 500,471 recipes with ingredients, steps, tags, and serving information.

Embeddings generated using `all-MiniLM-L6-v2` and stored in Pinecone (index: `snapchef-recipes`, dim=384, metric=cosine, serverless AWS us-east-1).
