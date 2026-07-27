# GenerateRecipe.py

# Import libraries
import json
import base64
import csv
import os
from datetime import datetime
import streamlit as st
import requests
from langchain_openai import ChatOpenAI
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from streamlit_cookies_manager import EncryptedCookieManager

# Remove padding at the top of the main content, so banner starts at level with sidebar buttons
st.markdown("""
    <style>
        .block-container {
            padding-top: 1rem !important;
        }
    </style>
""", unsafe_allow_html=True)

def get_image_base64(image_path):
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode()
    
# Logout in sidebar
cookies = EncryptedCookieManager(prefix="snapchef_", password=st.secrets["PASSWORD"])
if not cookies.ready():
    st.stop()

# Guard, to handle case where user clicks log out and is no more logged in, redirect to Home
if "token" not in st.session_state:
    st.switch_page("Home.py")
    st.stop()

# Log out button in sidebar
with st.sidebar:
    st.markdown("<br>" * 20, unsafe_allow_html=True)
    if st.button("Log out", type="secondary", use_container_width=True):
        del st.session_state["token"]
        cookies["token"] = ""
        cookies.save()
        st.session_state["just_logged_out"] = True
        st.switch_page("Home.py")

# Display the banner image with application title followed by a description
img_base64 = get_image_base64("Assets/banner_image.webp")

st.markdown(f"""
    <div style="
        position: relative;
        width: 100%;
        height: 200px;
        border-radius: 12px;
        overflow: hidden;
        margin-bottom: 1rem;
    ">
        <img src="data:image/webp;base64,{img_base64}" 
             style="width: 100%; height: 100%; object-fit: cover;">
        <div style="
            position: absolute;
            top: 50%;
            left: 0;
            right: 0;
            transform: translateY(-50%);
            background: rgba(255, 255, 255, 0.85);
            padding: 0.8rem 0;
            text-align: center;
        ">
            <h1 style="
                margin: 0;
                font-size: 2.5rem;
                color: #FF6B35;
                letter-spacing: 2px;
            ">🍳 SnapChef</h1>
            <p style="margin: 0; color: #555; font-size: 0.95rem;">
                Turn your ingredients into delicious recipes
            </p>
        </div>
    </div>
""", unsafe_allow_html=True)

# To improve the font size of context text 
st.markdown("""
    <style>
        .block-container {
            padding-top: 1rem !important;
        }
        .stMarkdown p, .stMarkdown li, .stCaption, label, .stSelectbox, .stTextInput {
            font-size: 1.05rem !important;
        }
    </style>
""", unsafe_allow_html=True)

# We cannot proceed further without certian user entries, although handles in Home additional caution taken here
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
llm_classify = ChatOpenAI(
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
    This function, sends out a message to llm with the user's message and current ingredients. Strict response format followed.
    """
    
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

    result = llm_classify.invoke(classification_prompt)
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
    - Generalize specific ingredient variants to their common form — e.g. "olive oil", 
    "vegetable oil", or "canola oil" should all be suggested simply as "oil". 
    Similarly "kosher salt" or "sea salt" should just be "salt". Only keep a 
    specific variant if it's genuinely distinct (e.g. "coconut milk" vs "milk" 
    are different ingredients, not variants of the same thing)
    - Reply with a simple comma-separated list only
    - If none are missing, reply with "none"
    - Do not include pantry assumptions, only list things explicitly in the recipes above"""

    # return a comma seperated string as output
    result = llm_classify.invoke(detection_prompt)
    raw = result.content.strip()
    if raw.lower() == "none" or not raw:
        return []
    seen = set()
    result = []
    for i in raw.split(","):
        cleaned = i.strip().lower()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(i.strip())
    return result

def log_feedback(rating: int):
    """
    Logs user feedback to a CSV file for offline analysis.
    rating=1 means positive (thumbs up), rating=0 means negative (thumbs down).
    This is the human-in-the-loop (HITL) feedback loop. 
    This provides real user signals for future A/B testing
    """
    feedback_dir = "eval_results"
    os.makedirs(feedback_dir, exist_ok=True)
    feedback_path = os.path.join(feedback_dir, "user_feedback.csv")

    file_exists = os.path.exists(feedback_path)

    with open(feedback_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "timestamp", "rating", "ingredients",
                "cooking_time", "serving_size", "prompt",
                "recipe_snippet"
            ])
        writer.writerow([
            datetime.now().isoformat(),
            rating,
            ", ".join(st.session_state.get("ingredients_list", [])),
            st.session_state.get("cooking_time", ""),
            st.session_state.get("serving_size", ""),
            st.session_state.get("prompt", ""),
            st.session_state.get("recipe_generated", "")[:200],
        ])
        
def build_llm_prompt():
    """
    Build the actual recipe generation prompt
    """

    return f"""The user wants: "{prompt_text}".

    Retrieved recipes for inspiration:
    {st.session_state.get("recipe_summary", "")}

    STRICT RULES:
    1. ONLY use these ingredients: {', '.join(st.session_state["ingredients_list"])}
    2. Do NOT add any other ingredients, not even pantry staples like salt or oil
    3. If a cooking step requires an ingredient not in the user's list, either:
   - Skip that step entirely if the dish still makes sense without it
   - Substitute with the closest available ingredient from the user's list
   - If neither is possible, acknowledge the limitation honestly and simplify the dish
    3b. If a step normally requires oil or fat (e.g. sautéing, frying) but the user has 
        none listed, do NOT silently omit it. Instead adapt the technique explicitly:
        use a splash of water or broth to prevent sticking, mention using a non-stick 
        pan on low heat, or explicitly say "dry-sauté" so the instructions are physically 
        accurate and won't burn or stick. Never write a sauté/fry step as if fat were 
        present when it wasn't listed.
    4. If the available ingredients are too limited to make any real dish (e.g. only salt 
    and water, or only one or two basic condiments with nothing to cook), do NOT invent 
    a fake recipe. Instead, respond with warmth and light humour — something like 
    "SnapChef works magic with limited ingredients, but even we need something to work 
    with! With just [ingredients], the best dish we can offer is... a glass of water. 
    Head back and add a few more ingredients, even something simple like an egg, some 
    bread, or a vegetable goes a long way."
    Keep the tone friendly and encouraging, not dismissive.
    Only trigger this if there are truly no cookable ingredients — water and salt alone,
    or a single seasoning. Do NOT trigger this if the user has any real food ingredients
    like vegetables, grains, dairy, meat, or fruit.
    5. Try to incorporate as many of the user's ingredients as possible into the recipe,
    but only if they make culinary sense together. Do not force ingredients that would
    ruin the dish. If an ingredient clearly does not belong (e.g. banana in a savory
    pasta), leave it out silently, do not mention it or apologize for not using it.
    6. You may always assume water is available for boiling, cooking, or washing, even if not listed

    Create a recipe for {serving_size} servings within {cooking_time}.

    Format in clean markdown:

    ### 🍽️ [Creative, specific dish name based on the main ingredients]

    **⏱️ Cook time:** X minutes

    ---

    #### 🛒 Ingredients (serves {serving_size})
    - only list ingredients from the user's available list

    ---

    #### 📖 Instructions
    1. Step one
    2. Step two

    ---

    💡 **Tip:** [one practical tip]
    """

# Retrieve recipes and detect missing ingredients 
# On first run the recipe summary is not in the session state - retrieve the recipes 
if "recipe_summary" not in st.session_state:
    with st.spinner("Searching recipes..."):
        query = (
            f"{prompt_text} that can be made with "
            f"{', '.join(ingredients_list)} and takes {cooking_time}."
        )
        # Send the query to FastAPI backend
        backend_url = st.secrets.get("BACKEND_URL", "http://127.0.0.1:8000")
        try:
            response = requests.get(
                f"{backend_url}/search",
                params={"query": query, "n": 10},
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

#  If missing ingredients found, pause and ask user
if st.session_state.get("missing_ingredients") and "recipe_generated" not in st.session_state:
    missing = st.session_state["missing_ingredients"]

    st.info(
        "🔍 The best matching recipes use some ingredients you may have. "
        "Check the dropdown below and select any you actually have to get a better recipe."
    )

    selected = st.multiselect(
        "✅ Which of these do you actually have?",
        options=missing,
        key="missing_multiselect",
        help="Select multiple. All selected items will be added to your ingredient list"
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
            "➡️ Skip & use my original ingredients only",
            use_container_width=True,
        )

    if regenerate_clicked and selected:
        for ing in selected:
            if ing not in st.session_state["ingredients_list"]:
                st.session_state["ingredients_list"].append(ing)
        # Clear only the recipe so retrieval isn't re-run, but generation is
        st.session_state.pop("recipe_generated", None) # clear since we dont want to enter this if and will anyways be generating the recipe again with the added ignredients in consideration
        st.session_state.pop("chat_store", None)
        st.session_state.pop("chat_history", None)
        st.session_state["missing_ingredients"] = []  # clear so we don't show missing ingredients again
        st.rerun()

    if not skip_clicked:
        st.stop()  # Hold here until user clicks one of the two buttons

# Generate recipe
if "recipe_generated" not in st.session_state:
    with st.chat_message("assistant"):
        with st.spinner("Cooking up your recipe..."):
            response_text = st.write_stream(stream_text(build_llm_prompt()))
    st.session_state.recipe_generated = response_text
else: # If no new ongredients were added the original recipe_generated would still be present , so just display that
    with st.chat_message("assistant"):
        st.markdown(st.session_state.recipe_generated)

# Check for appliances used in the recipe
if "appliances_checked" not in st.session_state:
    appliance_check_prompt = f"""
Read this recipe and list ONLY non-trivial kitchen appliances that not everyone owns.
Include: oven, microwave, blender, food processor, stand mixer, hand mixer, 
air fryer, pressure cooker, slow cooker, instant pot, waffle maker, toaster oven.
Do NOT include: pan, pot, bowl, knife, spoon, spatula, cutting board, refrigerator, 
baking tray, whisk — these are basic utensils everyone has.
Reply with a comma-separated list only. If none, reply "none".
Recipe: {st.session_state.recipe_generated}
"""
    appliance_result = llm_classify.invoke(appliance_check_prompt)
    raw = appliance_result.content.strip().lower()
    if raw != "none" and raw:
        st.session_state["appliances_used"] = [a.strip() for a in raw.split(",") if a.strip()]
    else:
        st.session_state["appliances_used"] = []
    st.session_state["appliances_checked"] = True

if st.session_state.get("appliances_used"):
    appliances = ", ".join(st.session_state["appliances_used"])
    st.info(f"💡 This recipe uses: {appliances}. Don't have one? Ask in the follow-up chat to adapt the recipe.")

# Human-in-the-loop feedback 
# Here we collects real user signals, that will be later used as online quality metrics
if "feedback_given" not in st.session_state:
    col_q, col1, col2 = st.columns([3, 1, 1])
    with col_q:
        st.markdown("""
            <div style="
                background: #FFF8F3;
                border: 1px solid #FFD4B8;
                border-radius: 10px;
                padding: 0.6rem 1.2rem;
                height: 100%;
                display: flex;
                align-items: center;
            ">
                <span style="font-size: 1.1rem; font-weight: 600; color: #333;">
                    Was this recipe helpful?
                </span>
            </div>
        """, unsafe_allow_html=True)
    with col1:
        if st.button("👍 Great recipe", use_container_width=True):
            log_feedback(rating=1)
            st.session_state["feedback_given"] = "positive"
            st.rerun()
    with col2:
        if st.button("👎 Not quite", use_container_width=True):
            log_feedback(rating=0)
            st.session_state["feedback_given"] = "negative"
            st.rerun()
else:
    if st.session_state["feedback_given"] == "positive":
        st.success("Thanks for the feedback! Glad you liked it 🎉")
    else:
        st.info("Thanks for the feedback! Try refining it in the chat below.")
        
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
                f"Acknowledge this addition warmly in one sentence, then update the recipe. "
                f"Full ingredient list: {', '.join(st.session_state['ingredients_list'])}. "
                f"Only use ingredients from their list. "
                f"Format ingredients as plain names only — no quantities, no units, no preparation verbs like minced or chopped."
                f"Do not include a Tip section at the end."
            )
        else:
            followup_prompt = (
                f"User message: {user_followup}\n"
                f"Before responding, acknowledge the user's message warmly and naturally in one sentence — "
                f"whether it is a request, a question, a doubt, or a comment. "
                f"Then provide your response or updated recipe.\n"
                f"Remember: only use ingredients from this list: {', '.join(st.session_state['ingredients_list'])}. "
                f"If the user has explicitly mentioned a new ingredient in their message, you may include it, "
                f"BUT you are not obligated to blindly agree to every addition. If an ingredient or combination "
                f"clearly does not belong in the dish (e.g. chocolate in a savory masala stir-fry, edible flowers "
                f"in a quick weeknight dish), say so honestly and with light humour instead of forcing it in. "
                f"You can suggest it might work better as a separate dish, or gently push back and explain why "
                f"it would clash, while still remaining warm and helpful. Use your genuine culinary judgment — "
                f"you do not need to say yes just because the user suggested it.\n"
                f"Format ingredients as plain names only — no quantities, no units, no preparation verbs like minced or chopped. "
                f"Do not include a Tip section at the end."
            )

        with st.chat_message("assistant"):
            followup_response = st.write_stream(stream_text(followup_prompt))

        st.session_state["chat_history"].append((user_followup, followup_response))
        st.session_state.pop("feedback_given", None)  # reset so feedback shows for this new response
        st.rerun()