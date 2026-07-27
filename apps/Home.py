# Home.py 

# Import libraries
import base64
import json
import streamlit as st
from streamlit_oauth import OAuth2Component
from streamlit_cookies_manager import EncryptedCookieManager


# The first thing to run at every page load
# Read the browser cookie named snapchef_token
cookies = EncryptedCookieManager(
    prefix="snapchef_",
    password= st.secrets["PASSWORD"]
)

# Remove padding at the top of the main content, so banner starts at level with sidebar buttons
st.markdown("""
    <style>
        .block-container {
            padding-top: 1rem !important;
        }
    </style>
""", unsafe_allow_html=True)

# If the cookie manager is not ready yet/ it is asynchronous, then we will halt the whole page
# Streamlit will retry on the next rerun. This part runs before any UI renders.
if not cookies.ready(): 
    st.stop()

# To improve the font size of context text 
st.markdown("""
    <style>
        .block-container {
            padding-top: 1rem !important;
        }
        .stMarkdown p, .stMarkdown li, .stCaption, label, .stSelectbox, .stTextInput {
            font-size: 1.05rem !important;
        }
        section[data-testid="stSidebar"] {
            font-size: 1.05rem !important;
        }
    </style>
""", unsafe_allow_html=True)


def get_image_base64(image_path):
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode()

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

with st.expander("ℹ️ What is SnapChef and how do I use it?"):
    st.markdown(
        "Ever opened your fridge and had no idea what to cook with what's inside? "
        "SnapChef solves exactly that.\n\n"
        "Tell us what ingredients you have at home and we will generate a custom recipe "
        "just for you, no grocery runs needed.\n\n"
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
    if st.session_state.pop("just_logged_out", False):
        # Skip cookie restore this one time — cookie may still be
        # mid-sync from the logout that just happened
        saved_token_str = None
    else:
        saved_token_str = cookies.get("token")
        if saved_token_str:
            try:
                # We will deserialize the json and restore to session
                st.session_state.token = json.loads(saved_token_str)
            except (json.JSONDecodeError, TypeError):
                # Cookie is corrupted, clear it and force re-login
                cookies["token"] = ""
                cookies.save()
    # Sceanrio 2 - token not in both cookie and current session
    if not saved_token_str:
        # Show the google login button
        # result = oauth2.authorize_button("Log in using Google","http://localhost:8501", "openid email profile")

        redirect_uri = st.secrets.get("REDIRECT_URI", "http://localhost:8501")
        # result = oauth2.authorize_button("Log in using Google", redirect_uri, "openid email profile")
        
        # col1, col2, col3 = st.columns([1, 2, 1])
        # with col2:
        #     result = oauth2.authorize_button(
        #         "Log in using Google", redirect_uri, "openid email profile"
        #     )

        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            result = oauth2.authorize_button(
                "Log in using Google",
                redirect_uri,
                "openid email profile",
                key="google_oauth_button"
            )
        
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

# To render user logged in - obtain user name from JWT payload
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
# def add_ingredient():
#     ingredient = st.session_state.ingredient_input
#     if ingredient and ingredient not in st.session_state["ingredients_list"]:
#         st.session_state.ingredients_list.append(ingredient)
#         st.session_state.ingredient_input = ""

# Text input for ingredient entry 
# st.text_input(
#     "Add an ingredient",
#     key="ingredient_input",
#     on_change=add_ingredient
# )

def add_ingredient():
    ingredient = st.session_state.ingredient_input.strip()
    if ingredient and ingredient not in st.session_state["ingredients_list"]:
        st.session_state.ingredients_list.append(ingredient)
        st.session_state.ingredient_input = ""

# Text input for ingredient entry — quantity is set afterward via stepper
st.text_input(
    "Add an ingredient",
    key="ingredient_input",
    on_change=add_ingredient,
    help="Once you add an ingredient, you'll be able to set a quantity for it. "
         "Add a quantity if the ingredient can be measured (e.g. vegetables). "
         "Leave it as 0 for condiments or liquids that aren't usually counted."
)

# Checkbox to add list of ingredients one by one
# if st.session_state["ingredients_list"]:
#     st.caption("Check ingredients to remove, then click Remove selected")
#     checked = []
#     for i, ing in enumerate(st.session_state["ingredients_list"]):
#         if st.checkbox(ing, key=f"chk_{i}"):
#             checked.append(i)

#     st.success(
#         f"✅ {len(st.session_state['ingredients_list'])} ingredient(s): "
#         f"{', '.join(st.session_state['ingredients_list'])}"
#     )
# Initialize quantity tracking dict if not present
if "ingredient_quantities" not in st.session_state:
    st.session_state["ingredient_quantities"] = {}

# Checkbox to select for removal + quantity stepper for each ingredient
if st.session_state["ingredients_list"]:
    st.caption("Check ingredients to remove, then click Remove selected")
    checked = []
    for i, ing in enumerate(st.session_state["ingredients_list"]):
        col_chk, col_name, col_qty = st.columns([1, 4, 2])
        with col_chk:
            if st.checkbox("", key=f"chk_{i}", label_visibility="collapsed"):
                checked.append(i)
        with col_name:
            st.write(ing)
        with col_qty:
            qty = st.number_input(
                "Qty",
                min_value=0,
                value=st.session_state["ingredient_quantities"].get(ing, 0),
                step=1,
                key=f"qty_{ing}_{i}",  # tied to ingredient name + index for uniqueness
                label_visibility="collapsed",
                help="0 means unspecified — used for things like salt or soy sauce"
            )
            st.session_state["ingredient_quantities"][ing] = qty

    # Build a display string combining ingredient + quantity for the summary
    display_items = []
    for ing in st.session_state["ingredients_list"]:
        qty = st.session_state["ingredient_quantities"].get(ing, 0)
        display_items.append(f"{ing} ({qty})" if qty > 0 else ing)

    st.success(
        f"✅ {len(st.session_state['ingredients_list'])} ingredient(s): "
        f"{', '.join(display_items)}"
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

# if st.session_state["ingredients_list"] and st.button("🍳 Generate Recipe", use_container_width=True):
#     st.session_state.pop("recipe_generated", None)
#     st.session_state.pop("memory", None)
#     st.session_state.pop("chat_history", None)
#     st.session_state.pop("recipe_summary", None)
#     st.session_state.pop("missing_ingredients", None)
#     st.session_state.pop("chat_store", None)
#     st.session_state.pop("feedback_given", None)
#     st.session_state.pop("appliances_checked", None)
#     st.session_state.pop("appliances_used", None)
#     st.session_state["serving_size"] = serving_size
#     st.session_state["cooking_time"] = cooking_time
#     st.session_state["prompt"] = prompt
#     st.switch_page("pages/GenerateRecipe.py")

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

    # Build final ingredient list with quantities included where specified
    final_ingredients = []
    for ing in st.session_state["ingredients_list"]:
        qty = st.session_state["ingredient_quantities"].get(ing, 0)
        final_ingredients.append(f"{ing} ({qty})" if qty > 0 else ing)

    st.session_state["ingredients_list"] = final_ingredients
    st.session_state["serving_size"] = serving_size
    st.session_state["cooking_time"] = cooking_time
    st.session_state["prompt"] = prompt
    st.switch_page("pages/GenerateRecipe.py")

# Logout in sidebar
with st.sidebar:
    st.markdown("<br>" * 20, unsafe_allow_html=True)
    if st.button("Log out", type="secondary", use_container_width=True):
        del st.session_state["token"]
        cookies["token"] = ""
        cookies.save()
        st.session_state["just_logged_out"] = True
        st.rerun()