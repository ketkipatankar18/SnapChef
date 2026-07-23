# GenerateRecipe.py

# Import libraries
import json
import streamlit as st
import requests
from langchain_openai import ChatOpenAI
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

st.title("👩‍🍳 SnapChef: Generating Your Recipe")

required_keys = ["serving_size", "cooking_time", "ingredients_list"]
for k in required_keys:
    if k not in st.session_state:
        st.warning("Incomplete input. Please go back to the home page.")
        st.stop()

serving_size = st.session_state["serving_size"]
cooking_time = st.session_state["cooking_time"]
prompt_text = st.session_state["prompt"]
ingredients_list = st.session_state["ingredients_list"]

# For recipe generation
# With streaming, the model sends back tokens one at a time as it generates them, like watching someone type. 
# With st.write_stream() the user sees the recipe appear word by word instead of waiting for the full response.
llm = ChatOpenAI(
    openai_api_key=st.secrets["OPEN_AI_API_KEY"],
    model="gpt-4o", # Name of the OpenAI model we used
    streaming=True,
)

# For two classification tasks
# Without streaming, the API waits until the entire response is finished, then sends it all at once. 
# For classification you don't want streaming, you need the complete JSON {"intent": "add_ingredient"} before you can parse it.
# Need full JSON before we do anything
llm_sync = ChatOpenAI(
    openai_api_key=st.secrets["OPEN_AI_API_KEY"],
    model="gpt-4o-mini",
    streaming=False,
)

# Since streamlit reruns entire file on every interaction, if we don't add chat to session state,
# it would be reset to empty dict on every rerun and we will not remember the conversation.
if "chat_store" not in st.session_state:
    st.session_state.chat_store = {}

# RunnableWithMessageHistory calls this function automatically before every LLM call
def get_session_history(session_id: str) -> InMemoryChatMessageHistory:
    """
    This function takes a session id string and returns history object for that session.
    If session does not exist, it creates one.
    In our app the session id is "snapchef_session" hence there is always one history
    """
    if session_id not in st.session_state.chat_store:
        st.session_state.chat_store[session_id] = InMemoryChatMessageHistory()
    return st.session_state.chat_store[session_id]

# Define the structure of every message sent to the LLM
# Contains the system prompt - the chef persona and rules, always present, never changes
# message place holder, when chain runs, LangChain looks up chat_store for our session and injects all previous messages automatically
# For first call this will be empty, second it will have the original recipe, third, recipe and followup
prompt_template = ChatPromptTemplate.from_messages([
    ("system", """You are a strict AI chef. You ONLY use ingredients the user explicitly says they have.
Never assume pantry staples. Never add ingredients not on the user's list unless they explicitly add them.
Always format responses in clean markdown with headings, bullet points, and emojis."""),
    MessagesPlaceholder(variable_name="history"),
    ("human", "{input}"), # Current user's message
])

# pipe operator, LangChain's LCEL - LangChain Expression Language
# This means feed the output of the prompt template into llm
# Prompt template formats everything into a list of messages 
# LLM receives prompt and runs and generate response
# This just defines a pipeline
chain = prompt_template | llm

# wraps the chain with InMemoryChatMessageHistory stored in st.session_state.chat_store 
# This is what remembers the conversation across follow-up questions.
conversation = RunnableWithMessageHistory(
    chain, # pipeline defined above
    get_session_history, # function that we will call to get/create the chat_store
    input_messages_key="input", # Current users message as key in dict
    history_messages_key="history", # which placeholder in the prompt do we replace with history
)

SESSION_ID = "snapchef_session"

# Helper function
def stream_text(input_text):
    # This call, automatically loads the history from chat_store, injects it into the message placeholder
    # in the prompt template, runs the chain and saves the new exchange back to history
    # Output is a mix of object types as it runs, some can be AIMessageChunk objects containing text, also have other metadata objects
    # hasattr(chunk, "content") this focuses only on the text-bearing chunks and produces the string content.
    # it is a python generator yielding one token at a time
    # When it is called it generate one token at a time, st.write_stream(stream_text(build_llm_prompt())) calls next() on it repeatedly and render each token to the screen as it arrives
    for chunk in conversation.stream(
        {"input": input_text},
        config={"configurable": {"session_id": SESSION_ID}},
    ):
        if hasattr(chunk, "content"):
            yield chunk.content

def classify_followup(user_message: str, current_ingredients: list) -> dict:
    """
    This function, sends out a message to llm with the user's message and current ingredients. Strict response format followed."""
    
    classification_prompt = f"""You are classifying a follow-up message in a recipe app.

The user's current ingredients are: {', '.join(current_ingredients)}
The user's follow-up message is: "{user_message}"

Classify the intent as exactly one of:
- "add_ingredient": user wants to add a new ingredient to use
- "substitute": user wants to replace an ingredient
- "dietary_restriction": user has a dietary need (vegan, gluten-free, etc.)
- "serving_change": user wants different serving size
- "recipe_tweak": user wants to adjust taste, spice level, texture, etc.
- "off_topic": message is unrelated to cooking or the current recipe

Reply in this exact format (JSON only, no other text):
{{"intent": "add_ingredient", "safe": true, "reason": "user wants to add cinnamon"}}"""

    result = llm_sync.invoke(classification_prompt)
    try:
        # Parse the string into a python dict
        return json.loads(result.content)
    except Exception:
        # If the model ingnores instructions and returns something unparseable, we default to recipe_tweak as it is the safest assumption 
        return {"intent": "recipe_tweak", "safe": True, "reason": "could not classify"}

def detect_missing_ingredients(recipe_summary: str, user_ingredients: list) -> list:
    detection_prompt = f"""Here are some recipe descriptions:
{recipe_summary}

The user only has these ingredients: {', '.join(user_ingredients)}

List the ingredients mentioned in the recipes that the user does NOT have.
Rules:
- Return ingredient names only — no quantities, no units, no numbers
- No verbs, no preparation instructions (e.g. "minced", "chopped", "boiled")
- Just the plain ingredient name e.g. "garlic" not "2 cloves garlic, minced"
- Reply with a simple comma-separated list only
- If none are missing, reply with "none"
- Do not include pantry assumptions, only list things explicitly in the recipes above"""

    # return a comma seperated string as output
    result = llm_sync.invoke(detection_prompt)
    raw = result.content.strip()
    if raw.lower() == "none" or not raw:
        return []
    return [i.strip() for i in raw.split(",") if i.strip()]

def build_llm_prompt():
    """
    Build the actual recipe generation prompt"""
    return f"""The user wants: "{prompt_text}".

Retrieved recipes for inspiration:
{st.session_state.get("recipe_summary", "")}

STRICT RULES:
1. ONLY use these ingredients: {', '.join(st.session_state["ingredients_list"])}
2. Do NOT add any other ingredients, not even pantry staples like salt or oil
3. If a step needs something unavailable, skip it or substitute from the user's list
4. If ingredients are too limited, make the simplest possible dish and explain honestly

Create a recipe for {serving_size} servings within {cooking_time}.

Format in clean markdown:

# 🍽️ [Dish Name]

**⏱️ Cook time:** X minutes

---

## 🛒 Ingredients (serves {serving_size})
- only list ingredients from the user's available list

---

## 👨‍🍳 Instructions
1. Step one
2. Step two

---

> 💡 **Tip:** [one practical tip]"""

# STAGE 1: Retrieve recipes and detect missing ingredients 
# On first run the recipe summary is not in the session state - retrieve the recipes 
if "recipe_summary" not in st.session_state:
    with st.spinner("Searching recipes..."):
        query = (
            f"{prompt_text} that can be made with "
            f"{', '.join(ingredients_list)} and takes {cooking_time}."
        )
        backend_url = st.secrets.get("BACKEND_URL", "http://127.0.0.1:8000")
        try:
            response = requests.get(
                f"{backend_url}/search",
                params={"query": query, "n": 5},
                timeout=10,
            )
            response.raise_for_status()
            api_response = response.json()
        except requests.exceptions.RequestException as e:
            st.error(f"Could not reach the recipe search API: {e}")
            st.stop()

        recipe_summary = ""
        for i, recipe in enumerate(api_response, 1):
            title = recipe.get("name", "Untitled")
            servings = recipe.get("servings", "N/A")
            desc = recipe.get("description", "")
            ingredients = recipe.get("ingredients_raw", [])
            if isinstance(ingredients, str):
                ingredients = [ingredients]
            ingredients_fmt = ", ".join(ingredients) if ingredients else "Not specified"
            steps = recipe.get("steps", "") or "No steps provided."
            recipe_summary += (
                f"{i}. {title} — serves {servings}\n"
                f"   Description: {desc}\n"
                f"   Ingredients: {ingredients_fmt}\n"
                f"   Steps: {steps}\n\n"
            )
        st.session_state["recipe_summary"] = recipe_summary

    with st.spinner("Checking what ingredients you might need..."):
        missing = detect_missing_ingredients(
            st.session_state["recipe_summary"],
            st.session_state["ingredients_list"]
        )
        st.session_state["missing_ingredients"] = missing

#  STAGE 2: If missing ingredients found, pause and ask user
if st.session_state.get("missing_ingredients") and "recipe_generated" not in st.session_state:
    missing = st.session_state["missing_ingredients"]

    # st.info(
    #     f"🔍 The best matching recipes also use: **{', '.join(missing)}**\n\n"
    #     f"Select any you actually have to get a better recipe, then click **Regenerate**. "
    #     f"Or skip to generate with just your original ingredients."
    # )

    st.info(
        "🔍 The best matching recipes use some ingredients you may have. "
        "Check the dropdown below and select any you actually have to get a better recipe."
    )

    selected = st.multiselect(
        "✅ Which of these do you actually have?",
        options=missing,
        key="missing_multiselect",
        help="Select multiple — all selected items will be added to your ingredient list"
    )

    col1, col2 = st.columns(2)
    with col1:
        regenerate_clicked = st.button(
            f"🔄 Add {len(selected)} ingredient(s) & regenerate" if selected else "🔄 Regenerate",
            disabled=not selected,
            use_container_width=True,
        )
    with col2:
        skip_clicked = st.button(
            "➡️ Skip — use my original ingredients only",
            use_container_width=True,
        )

    if regenerate_clicked and selected:
        for ing in selected:
            if ing not in st.session_state["ingredients_list"]:
                st.session_state["ingredients_list"].append(ing)
        # Clear only the recipe so retrieval isn't re-run, but generation is
        st.session_state.pop("recipe_generated", None)
        st.session_state.pop("chat_store", None)
        st.session_state.pop("chat_history", None)
        st.session_state["missing_ingredients"] = []  # clear so we don't show missing ingredients again
        st.rerun()

    if not skip_clicked:
        st.stop()  # Hold here until user clicks one of the two buttons

# STAGE 3: Generate recipe
if "recipe_generated" not in st.session_state:
    with st.chat_message("assistant"):
        with st.spinner("Cooking up your recipe..."):
            response_text = st.write_stream(stream_text(build_llm_prompt()))
    st.session_state.recipe_generated = response_text
else:
    with st.chat_message("assistant"):
        st.markdown(st.session_state.recipe_generated)

st.divider()

# Follow-up Q&A
st.markdown("#### 💬 Customize your recipe")
st.caption("Try: 'make it spicier', 'I also have eggs', 'make it vegan', 'reduce to 1 serving'")

if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []

for q, a in st.session_state["chat_history"]:
    with st.chat_message("user"):
        st.markdown(q)
    with st.chat_message("assistant"):
        st.markdown(a)

user_followup = st.chat_input("Ask a follow-up to refine your recipe...")

if user_followup:
    with st.chat_message("user"):
        st.markdown(user_followup)

    with st.spinner("Thinking..."):
        classification = classify_followup(user_followup, st.session_state["ingredients_list"])

    if classification.get("intent") == "off_topic":
        with st.chat_message("assistant"):
            st.markdown(
                "🤔 That doesn't seem related to your recipe. "
                "Try asking me to adjust spice level, swap an ingredient, "
                "change servings, or add a dietary restriction."
            )
        st.session_state["chat_history"].append((user_followup, "Off-topic — redirected user."))
    else:
        if classification.get("intent") == "add_ingredient":
            new_ing = user_followup.strip().lower()
            if new_ing not in st.session_state["ingredients_list"]:
                st.session_state["ingredients_list"].append(new_ing)
            followup_prompt = (
                f"The user now also has: {new_ing}. "
                f"Full ingredient list: {', '.join(st.session_state['ingredients_list'])}. "
                f"Update the recipe to incorporate {new_ing} if it makes sense. "
                f"Only use ingredients from their list."
            )
        else:
            followup_prompt = (
                f"User request: {user_followup}\n"
                f"Remember: only use ingredients from this list: {', '.join(st.session_state['ingredients_list'])}"
            )

        with st.chat_message("assistant"):
            followup_response = st.write_stream(stream_text(followup_prompt))

        st.session_state["chat_history"].append((user_followup, followup_response))