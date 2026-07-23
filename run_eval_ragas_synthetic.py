"""
run_eval_ragas_synthetic.py - RAGAS Evaluation
"""

import os
import json
import tomllib
import requests
import pandas as pd
from datetime import datetime
from pathlib import Path

# from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_openai import ChatOpenAI
from langchain_community.embeddings import SentenceTransformerEmbeddings

from ragas import evaluate # main scoring function, pass it a dataset and list of metrics
from ragas.metrics import faithfulness, answer_relevancy, context_recall, context_precision # 4 metric objects RAGAS uses internally
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from datasets import Dataset # Hugging Face datasets

secrets_path = Path(".streamlit/secrets.toml")
with open(secrets_path, "rb") as f:
    secrets = tomllib.load(f)

OPEN_AI_API_KEY = secrets.get("OPEN_AI_API_KEY", "") 
BACKEND_URL    = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
TESTSET_PATH   = Path("eval_results/synthetic_testset.csv")
# TESTSET_PATH = Path("eval_results/synthetic_testset_filtered.csv")
OUTPUT_DIR     = Path("eval_results")

# critic_llm scores: "Is this question good enough to keep in the test set?"
# runs ONCE when building the test set

# eval_ragas_synthetic.py
# llm scores: "Is this pipeline answer faithful / relevant / recalled correctly?"
# runs ONCE per test case during evaluation

llm = LangchainLLMWrapper(ChatOpenAI(
    model="gpt-4o-mini",
    openai_api_key=OPEN_AI_API_KEY,
    temperature=0,
))

# embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(
#     model="text-embedding-3-small",
#     openai_api_key=OPENAI_API_KEY,
# ))

# RAGAS uses llm to judge whether an answer is faithful to the context.
# Here the embeddings are only used by RAGAS to compare "does this answer semantically match the question?"
# sentence_transformer = HuggingFaceEmbeddings(
#     model_name="all-MiniLM-L6-v2",
#     model_kwargs={"device": "cpu"},
#     encode_kwargs={"normalize_embeddings": True})
# embeddings = LangchainEmbeddingsWrapper(sentence_transformer)

sentence_transformer = SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")
embeddings = LangchainEmbeddingsWrapper(sentence_transformer)

def safe_avg(scores):
    valid = [s for s in scores if s is not None and str(s) != 'nan']
    return round(float(sum(valid) / len(valid)), 4) if valid else 0.0

def retrieve_and_format(query: str, n: int = 5) -> list[str]:
    try:
        # production Flask backend, the same GET /search endpoint the Streamlit app calls.
        # Here query is the question in the testset, they are specific to clusters with similar recipes so the recipes selected should mainly contain relevant ones.
        resp = requests.get(f"{BACKEND_URL}/search", params={"query": query, "n": n}, timeout=15)
        resp.raise_for_status()
        recipes = resp.json()
    except Exception as e:
        print(f"  ⚠️  Backend error: {e}")
        return []

    # Convert each recipe dict into a plain string
    contexts = []
    for r in recipes:
        ings = r.get("ingredients_raw", [])
        if ings is None:
            ings = []
        elif isinstance(ings, str):
            ings = [ings]
        elif not isinstance(ings, list):
            ings = [str(ings)]
        contexts.append(
            f"{r.get('name','Untitled')} (serves {r.get('servings','N/A')})\n"
            f"Description: {r.get('description','')}\n"
            f"Ingredients: {', '.join(ings)}\n"
            f"Steps: {r.get('steps','') or 'No steps provided.'}"
        )
    return contexts

def generate_answer(question: str, contexts: list[str]) -> str:
    # module-level llm is wrapped in LangchainLLMWrapper for RAGAS, you can't call .invoke() on it directly. 
    gen_llm = ChatOpenAI(
        model="gpt-4o-mini",
        openai_api_key=OPEN_AI_API_KEY,
        temperature=0, # The same question with the same context always produces the same answer. 
    )
    context_block = "\n\n".join(contexts)
    prompt = f"""You are a helpful AI chef. Answer this question using only the provided recipes.

Question: {question}

Retrieved recipes:
{context_block}

Answer concisely using only information from the recipes above."""
    return gen_llm.invoke(prompt).content

def run_synthetic_eval():
    print("=" * 60)
    print("SnapChef RAGAS Evaluation — Synthetic Test Set")
    print("=" * 60)

    if not TESTSET_PATH.exists():
        print(f"ERROR: {TESTSET_PATH} not found.")
        print("Run generate_testset.py first to create the synthetic test set.")
        exit(1)

    df = pd.read_csv(TESTSET_PATH)
    print(f"\nLoaded {len(df)} synthetic test cases from {TESTSET_PATH}\n")

    # RAGAS synthetic testset columns vary based on the version, handle both
    question_col  = "user_input"  if "user_input"  in df.columns else "question"
    reference_col = "reference"   if "reference"   in df.columns else "ground_truth"

    questions, answers, contexts_list, ground_truths = [], [], [], []

    for i, row in df.iterrows():
        question  = str(row[question_col])
        reference = str(row[reference_col])

        print(f"[{i+1:02d}/{len(df)}] {question[:60]}")

        # For the questions as query get n recipes and their context
        # contexts = retrieve_and_format(question)
        contexts = retrieve_and_format(question, n=10)
        if not contexts:
            print("         ⚠️  No contexts retrieved — skipping")
            continue

        answer = generate_answer(question, contexts)

        questions.append(question)
        answers.append(answer)
        contexts_list.append(contexts)
        ground_truths.append(reference)
        print(f"         ✓")

    print(f"\nScoring {len(questions)} samples with RAGAS... {len(questions)} questions x 4 metrics = {len(questions)*4} individual scoring operations\n")

    # RAGAS's retrieved_contexts field expects a list of strings where each string is one retrieved document. In our case, one string per recipe.
    dataset = Dataset.from_dict({
        "user_input":         questions,
        "response":           answers,
        "retrieved_contexts": contexts_list,
        "reference":          ground_truths,
    })

    results = evaluate(
        dataset=dataset,
        metrics=[faithfulness, answer_relevancy, context_recall, context_precision],
        llm=llm,
        embeddings=embeddings,
    )

    scores_df = results.to_pandas()
    csv_path  = OUTPUT_DIR / f"synthetic_scores_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    scores_df.to_csv(csv_path, index=False)

    recall_scores = [s for s in results["context_recall"] if s is not None and str(s) != 'nan']

    summary = {
        "timestamp":         datetime.now().isoformat(),
        "testset":           "synthetic",
        "n_samples":         len(questions),
        "faithfulness":      safe_avg(results["faithfulness"]),
        "answer_relevancy":  safe_avg(results["answer_relevancy"]),
        "context_recall":    safe_avg(results["context_recall"]),
        "context_precision": safe_avg(results["context_precision"]),
    }
    with open(OUTPUT_DIR / "synthetic_ragas_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 60)
    print("SYNTHETIC EVAL RESULTS")
    print("=" * 60)
    for k, v in summary.items():
        if isinstance(v, float):
            print(f"  {k:<22}: {v:.4f}")
    print("=" * 60)

if __name__ == "__main__":
    if not OPEN_AI_API_KEY:
        print("ERROR: Set OPENAI_API_KEY environment variable first.")
        exit(1)
    run_synthetic_eval()