# Home.py 

# Import libraries
# import os
import base64
import json
import streamlit as st
from streamlit_oauth import OAuth2Component
from streamlit_cookies_manager import EncryptedCookieManager


# The first thing to run at every page load
# Read the browser cookie names snapchef_token
cookies = EncryptedCookieManager(
    prefix="snapchef_",
    password= st.secrets["PASSWORD"]
)
# If the cookie manager is not ready yet/ it is asynchronous, then we will halt the whole page
# Streamlit will retry on the next rerun. This part runs before any UI renders.
if not cookies.ready(): 
    st.stop()

def get_image_base64(image_path):
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode()

# st.title("🍳 SnapChef: Recipe Suggestion RAG")
# st.title("🍳 SnapChef")

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

with st.expander("ℹ️ What is SnapChef and how do I use it?"):
    st.markdown(
        "Ever opened your fridge and had no idea what to cook with what's inside? "
        "SnapChef solves exactly that.\n\n"
        "Tell us what ingredients you have at home and we will generate a custom recipe "
        "just for you — no grocery runs needed.\n\n"
        "How to use it:\n"
        "1. Type in the ingredients you currently have at home\n"
        "2. Choose how much time you have to cook\n"
        "3. Optionally describe what kind of dish you are in the mood for\n"
        "4. Click Generate Recipe\n\n"
        "SnapChef is perfect for reducing food waste, cooking on a budget, "
        "or simply figuring out dinner with whatever is in your kitchen."
    )

# Load OAuth credentials from secrets 
client_id = st.secrets["GOOGLE_CLIENT_ID"]
client_secret = st.secrets["GOOGLE_CLIENT_SECRET"]
redirect_uri = "http://localhost:8501"  

# Initialize OAuth2Component for Google login
oauth2 = OAuth2Component(
    client_id=client_id,
    client_secret=client_secret,
    authorize_endpoint="https://accounts.google.com/o/oauth2/auth",
    token_endpoint="https://oauth2.googleapis.com/token"
)

# Handle login flow - 3 scenarios
if 'token' not in st.session_state:
    saved_token_str = cookies.get("token")
    # Sceanrio 1 - token already in cookie but not current session
    if saved_token_str:
        try: 
            # We will deserialize the json and restore to session
            st.session_state.token = json.loads(saved_token_str)
        except (json.JSONDecodeError, TypeError):
            # Cookie is corrupted — clear it and force re-login
            cookies["token"] = ""
            cookies.save()
    # Sceanrio 2 - token not in both cookie and current session
    else:
        # Show the google login button
        # result = oauth2.authorize_button("Log in using Google","http://localhost:8501", "openid email profile")

        redirect_uri = st.secrets.get("REDIRECT_URI", "http://localhost:8501")
        result = oauth2.authorize_button("Log in using Google", redirect_uri, "openid email profile")

        # If and when login is successful, result["token"] is and OAuth2Token object
        if result and 'token' in result:
            # If authorization successful, save token in session state
            st.session_state.token = result.get('token')
            # Convert the token to a format cookie manager can store
            cookies["token"] = json.dumps(dict(result["token"]))
            cookies.save()
            st.rerun()
else:
    # Sceanrio 3 - token already in session/ user is already logged in current session
    token = st.session_state['token']

# Update token regardless of what scenario ran 
token = st.session_state.get("token") 
if not token:
    st.stop()   # don't render the form until logged in

# try:
#     user_info = jwt.decode(token["id_token"], options={"verify_signature": False})
#     user_name = user_info.get("name", user_info.get("email", "User"))
#     st.caption(f"👤 Logged in as {user_name}")
# except Exception:
#     pass

try:
    id_token = token.get("id_token", "") if isinstance(token, dict) else ""
    if id_token:
        payload = id_token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        user_info = json.loads(base64.b64decode(payload).decode("utf-8"))
        user_name = user_info.get("name", user_info.get("email", ""))
        if user_name:
            st.caption(f"👤 Logged in as {user_name}")
except Exception:
    pass

# In the below section we are using different streamlit widgets 
# Servings Input
st.markdown("### Servings")
serving_size = st.number_input(
    "Enter servings", min_value=1, max_value=15, value=2
)

# Cooking Time Input
st.markdown("### Cooking Time")
cooking_time = st.selectbox(
    "Select approximate cooking time",
    ["< 30 minutes", "30-60 minutes", "> 60 minutes"]
)

# Ingredients Input
st.markdown("### Ingredients")

# Initialize ingredients list in session state if not already present
if "ingredients_list" not in st.session_state:
    st.session_state["ingredients_list"] = []

# Define helper function to add ingredient to list when input changes
def add_ingredient():
    ingredient = st.session_state.ingredient_input
    if ingredient and ingredient not in st.session_state["ingredients_list"]:
        st.session_state.ingredients_list.append(ingredient)
        st.session_state.ingredient_input = ""

# Text input for ingredient entry
st.text_input(
    "Add an ingredient",
    key="ingredient_input",
    on_change=add_ingredient
)

# Checkbox pattern — avoids Streamlit double-click bug on individual delete buttons
if st.session_state["ingredients_list"]:
    st.caption("Check ingredients to remove, then click Remove selected")
    checked = []
    for i, ing in enumerate(st.session_state["ingredients_list"]):
        if st.checkbox(ing, key=f"chk_{i}"):
            checked.append(i)
    
    st.success(
        f"✅ {len(st.session_state['ingredients_list'])} ingredient(s): "
        f"{', '.join(st.session_state['ingredients_list'])}"
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Remove selected", disabled=not checked):
            for i in sorted(checked, reverse=True):
                st.session_state["ingredients_list"].pop(i)
            st.rerun()
    with col2:
        if st.button("✖️ Clear all"):
            st.session_state["ingredients_list"] = []
            st.rerun()

# User Prompt / Preferences
st.markdown("### Preferences")
prompt = st.text_area("Describe preferences", placeholder="e.g., I want a spicy, low-oil recipe")

# Generate
if not st.session_state["ingredients_list"]:
    st.info("Add at least one ingredient to generate a recipe.")

if st.session_state["ingredients_list"] and st.button("🍳 Generate Recipe", use_container_width=True):
    st.session_state.pop("recipe_generated", None)
    st.session_state.pop("memory", None)
    st.session_state.pop("chat_history", None)
    st.session_state.pop("recipe_summary", None)
    st.session_state.pop("missing_ingredients", None)
    st.session_state.pop("chat_store", None)
    st.session_state.pop("feedback_given", None)
    st.session_state.pop("appliances_checked", None)
    st.session_state.pop("appliances_used", None)
    st.session_state["serving_size"] = serving_size
    st.session_state["cooking_time"] = cooking_time
    st.session_state["prompt"] = prompt
    st.switch_page("pages/GenerateRecipe.py")

st.divider()

# Logout
# if st.button("Log out"):
#     del st.session_state["token"]
#     cookies["token"] = ""
#     cookies.save()
#     st.rerun()

# Logout in sidebar
with st.sidebar:
    st.divider()
    if st.button("Log out", type="secondary", use_container_width=True):
        del st.session_state["token"]
        cookies["token"] = ""
        cookies.save()
        st.rerun()