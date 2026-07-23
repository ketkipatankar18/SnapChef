"""
generate_testset.py - Synthetic Test Set Generator

This program uses RAGAS TestsetGenerator to automatically create evaluation
question-answer pairs directly from the recipe corpus/recipe.csv.

This is better than manual test sets creation because:
  - Questions are grounded in recipes that actually exist in the DB
  - Covers diverse question types (simple, reasoning, multi-context)
  - Reproducible and scalable

What is the overall flow followed?
1) First we are picking 500 recipes from CSV, they act as nodes
2) Internally RAGAS has CustomNodeFilter which filters bad nodes. 
3) Summarize each node, LLM calls made to do this. Slower section. 
RAGAS uses the generator_llm passed itself for all its internal tasks 
including summarization, question generation, and quality filtering. 
Bad nodes those that could not be summarized. 
4) Embed all the nodes using the embeddings passed to the TestsetGenerator
5) Use the embeddings for each node to cluster similar recipes
6) Generate candidate questions - same generator_llm used here
7) Score and filter questions - same generator_llm used here. For older 
RAGAS version another llm, called the critic_llm used to be passed.
8) Return the best n_questions obtained

Usage:
  python generate_testset.py --n 50 --csv services/ChromaDB/recipes.csv

Output:
  eval_results/synthetic_testset.csv   — use this with run_eval_ragas_synthetic.py
"""

import os
import json
import tomllib
# python's built-in library fro cmd arguments
import argparse
import pandas as pd
from pathlib import Path
# from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_openai import ChatOpenAI

# The reason is RAGAS doesn't accept a raw SentenceTransformer object. 
# It has its own internal embedding interface and requires something that implements 
# embed_documents() and embed_query() methods with specific signatures.
from langchain_community.embeddings import SentenceTransformerEmbeddings

# Document is a LangChain object wraps text with metadata - RAGAS requires this format (does not accept raw strings/ DataFrames)
from langchain_core.documents import Document
from ragas.testset import TestsetGenerator
from ragas.testset.persona import Persona
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper

secrets_path = Path(".streamlit/secrets.toml")
with open(secrets_path, "rb") as f:
    secrets = tomllib.load(f)

OPEN_AI_API_KEY = secrets.get("OPEN_AI_API_KEY", "")  # If variable not set, return empty string and do not crash
OUTPUT_DIR = Path("eval_results")
OUTPUT_DIR.mkdir(exist_ok=True)

def load_recipes_as_documents(csv_path: str, max_recipes: int = 500) -> list[Document]:
    """
    Load recipes from CSV and convert to LangChain Documents.
    RAGAS TestsetGenerator expects Document objects with page_content + metadata.
    We sample max_recipes to keep generation cost low.
    """
    print(f"Loading recipes from {csv_path}...")
    df = pd.read_csv(csv_path)

    # Our dataset has more than max_recipes rows hence randomly sample max_recipes rows 
    if len(df) > max_recipes:
        df = df.sample(n=max_recipes, random_state=42)
        print(f"Sampled {max_recipes} recipes from {len(df)} total")

    documents = []
    # row is pandas Series
    for _, row in df.iterrows():
        # Build rich text content — same format used in generate_embedding.ipynb
        name = str(row.get("name", row.get("title", "Unknown Recipe"))) # Try getting recipe name if not present try title - nested fallback - our csv uses title in the generate embeddings and name in app.py
        description = str(row.get("description", ""))
        ingredients = str(row.get("ingredients_raw", row.get("ingredients", "")))
        steps = str(row.get("steps", ""))
        servings = str(row.get("servings", ""))

        # Build a single string/full text read by RAGAS to understand recipe and generate questions
        page_content = (
            f"Recipe: {name}\n"
            f"Servings: {servings}\n"
            f"Description: {description}\n"
            f"Ingredients: {ingredients}\n"
            f"Steps: {steps}"
        )

        # Wrap the text in a Document object
        # Metadata is used by RAGAS for filtering and traceability - knowing which recipe a generated question came from
        doc = Document(
            page_content=page_content,
            # structured data attached to the document
            metadata={
                "name": name,
                "servings": servings,
                "source": "food_com_recipes",
            }
        )
        documents.append(doc)

    print(f"Loaded {len(documents)} recipe documents")
    return documents

def generate_synthetic_testset(
    csv_path: str,
    n_questions: int = 50,
    max_recipes: int = 500,
):
    # The above type hints do not affect execution, help IDE catch mistakes
    """
    Generate a synthetic test set using RAGAS TestsetGenerator.

    RAGAS generates 3 types of questions automatically:
      - Simple: "What ingredients are needed for X?"
      - Reasoning: "Why would someone use Y technique in this recipe?"
      - Multi-context: questions that require combining info from multiple recipes
    """
    print("=" * 60)
    print("RAGAS Synthetic Testset Generator")
    print("=" * 60)

    # Create the question generator LLM
    # LangchainLLMWrapper is an adapter. RAGAS has its own internal model interface
    # The adapter makes a LangChain ChatOpenAI object speak that interface, without it RAGAS would not know how to call the model.
    generator_llm = LangchainLLMWrapper(ChatOpenAI(
        model="gpt-4o-mini",
        openai_api_key=OPEN_AI_API_KEY,
        # at 0 picks most probable tokens producing repetitive output and 0.7 pcks less probable tokens producing creative output
        temperature=0.7,    # some creativity/randomness for diverse questions
    ))

    # older RAGAS versions had a two-model setup and older RAGAS API looked like this
    # generator = TestsetGenerator.from_langchain(
    #     generator_llm=generator_llm,
    #     critic_llm=critic_llm,
    #     embeddings=embeddings,
    # )

    # If we use the older RAGAS version we can create the quality filter LLM
    # Not explicitely passed to the TestsetGenerator, newer RAGAS versions handle the critic internally
    # critic_llm = LangchainLLMWrapper(ChatOpenAI(
    #     model="gpt-4o-mini",
    #     openai_api_key=OPEN_AI_API_KEY,
    #     # We want reproducible scoring and not random filtering
    #     temperature=0,      # fully deterministic for quality filtering, same question gets same quality score
    # ))

    # Creates an embedding model, RAGAS uses this to convert recipe text into vectors
    
    # embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(
    #     model="text-embedding-3-small",
    #     openai_api_key=OPENAI_API_KEY,
    # ))

    # sentence_transformer = HuggingFaceEmbeddings(
    # model_name="all-MiniLM-L6-v2",
    # model_kwargs={"device": "cpu"},
    # encode_kwargs={"normalize_embeddings": True})
    # embeddings = LangchainEmbeddingsWrapper(sentence_transformer)

    # embeddings = HuggingfaceEmbeddings(model_name="all-MiniLM-L6-v2")

    sentence_transformer = SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")
    embeddings = LangchainEmbeddingsWrapper(sentence_transformer)

    # Load your actual recipe corpus
    documents = load_recipes_as_documents(csv_path, max_recipes)

    personas = [
        Persona(
            name="home cook with limited ingredients",
            role_description=(
                "A home cook who only has a few ingredients available and wants to know "
                "what they can make with what they have. Always asks questions like "
                "'I have X and Y, what can I make?' or 'What recipe uses these ingredients?' "
                "Never asks about specific named recipes or cookbook titles."
            ),
        ),
        Persona(
            name="busy person with time constraints",
            role_description=(
                "A busy person who wants quick recipes within a specific time limit. "
                "Asks questions about recipes that can be made in under 30 minutes or "
                "30-60 minutes using common ingredients. Focuses on cooking time and "
                "simplicity, not on specific recipe names."
            ),
        ),
        Persona(
        name="cook with dietary preferences",
        role_description=(
            "Someone who wants to cook with the ingredients they have on hand while "
            "respecting certain food preferences. Asks what dishes can be made from "
            "a given set of ingredients, and how recipes can be adapted using only "
            "what is available. Never references specific recipe names or cookbooks."
            ),
        ),
        Persona(
            name="beginner cook",
            role_description=(
                "A beginner in the kitchen who has a small set of basic ingredients and "
                "wants simple step-by-step guidance on what to cook. Asks what dishes "
                "are possible with a handful of ingredients and wants easy instructions. "
                "Focuses on what they have, not on specific named recipes."
            ),
        ),
        Persona(
            name="cook planning for a specific number of servings",
            role_description=(
                "Someone cooking for a specific number of people who has a handful of "
                "ingredients and wants to know what dish they can make for that group. "
                "Always asks things like 'I have X and Y, what can I cook for 4 people?' "
                "Never mentions specific recipe names, cookbooks, or asks how to scale "
                "a named recipe. Always starts from ingredients, never from a recipe name."
            ),
        ),
        Persona(
            name="spontaneous cook using leftover ingredients",
            role_description=(
                "Someone who wants to use up leftover ingredients before they spoil. "
                "Asks what recipes can be made from a specific combination of ingredients "
                "they currently have. Always ingredient-driven, never asks about specific "
                "recipe names or restaurant dishes."
            ),
        ),
        Persona(
            name="cook with limited quantities of ingredients",
            role_description=(
                "Someone who has the right ingredients but only small amounts of each — "
                "not enough for a full standard recipe. Always frames questions around "
                "the limited quantities they actually have, mentioning approximate amounts "
                "rather than precise measurements. Never asks about specific named recipes "
                "and never assumes they have full quantities of anything."
            ),
        ),
    ]

    # Initialise generator - creates generator object
    generator = TestsetGenerator(
        llm=generator_llm,
        embedding_model=embeddings,
        persona_list=personas,
    )

    print(f"\nGenerating {n_questions} synthetic test questions from recipe corpus...")

    # RAGAS runs an internal multi-step pipeline
    # take all recipes/ documents under documents and embed them 
    # cluster similar recipes
    # For each cluster, generator llm generates candidate questions (simple, reasoning and multi-context)
    # critical llm scores each question for clarity and answerability
    # filters out low quality questions
    # Keep the n_questions best question with their reference answers
    testset = generator.generate_with_langchain_docs(
        documents,
        testset_size=n_questions,
    )

    # Convert to DataFrame
    df = testset.to_pandas()

    # Save CSV
    # output will look like user_input, reference, reference_contexts
    output_path = OUTPUT_DIR / "synthetic_testset.csv"
    df.to_csv(output_path, index=False)

    print(f"\n{'='*60}")
    print(f"Generated {len(df)} test cases")
    print(f"Saved to: {output_path}")
    print(f"{'='*60}")
    print("\nColumns in your test set:")
    for col in df.columns:
        print(f"  - {col}")
    print("\nSample questions generated:")
    for i, row in df.head(5).iterrows():
        print(f"  [{i+1}] {str(row.get('user_input', row.get('question', '')))[:80]}")

    print("\nNext step: run eval_ragas_synthetic.py with this test set")
    return df

# Main Block 

if __name__ == "__main__":
    # Read the command line arguments
    # Each add_argument registers one flag
    parser = argparse.ArgumentParser(description="Generate synthetic RAGAS test set from recipe corpus")
    parser.add_argument("--csv",  default="services/ChromaDB/recipes.csv", help="Path to your recipes CSV")
    parser.add_argument("--n",    type=int, default=50,  help="Number of test questions to generate") # type int means parser converts from string to int
    parser.add_argument("--max",  type=int, default=500, help="Max recipes to sample from corpus")
    args = parser.parse_args()

    # Two guards
    if not OPEN_AI_API_KEY:
        print("ERROR: OPEN_AI_API_KEY not found in /.streamlit/secrets.toml")
        exit(1) # stops python immediately, as 1 in Unix convention means something went wrong

    if not Path(args.csv).exists():
        print(f"ERROR: CSV not found at {args.csv}")
        exit(1)

    generate_synthetic_testset(args.csv, args.n, args.max)