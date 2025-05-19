import streamlit as st
import pandas as pd
import os
import requests
from dotenv import load_dotenv
from groq import Groq

# Load environment variables from .env file
load_dotenv()

# Function to get configuration (tries secrets first, then env vars)
def get_config(key, default=None):
    # Try to get from Streamlit secrets (for deployment)
    if hasattr(st, 'secrets') and key in st.secrets:
        return st.secrets[key]
    # Fall back to environment variables (for local development with .env)
    return os.getenv(key, default)

# Get API configuration
api_key = get_config("GROQ_API_KEY")
client = Groq(api_key=api_key)

# --- Config ---
BASE_URL = get_config("BASE_URL", "http://10.10.0.106:8001")
USER_ID = get_config("USER_ID", "f772dc7d-7b53-4bec-9929-7f9774be00ff")
PORTFOLIO_API = f"{BASE_URL}/user_portfolio/list/get_by_user_id/{USER_ID}"
STOCK_PREDICTIONS_API = f"{BASE_URL}/stock_predictions/list/get_by_portfolio_id"

# --- Timeout-safe request ---
def safe_get(url, timeout=10):
    try:
        response = requests.get(url, timeout=timeout)
        if response.ok:
            return response.json()
    except Exception as e:
        st.error(f"Failed to fetch data: {e}")
    return []

@st.cache_data(ttl=300)  # Cache data for 5 minutes
def fetch_portfolio_data():
    # --- Fetch portfolios ---
    portfolios = safe_get(PORTFOLIO_API)
    
    # --- Accumulate predictions ---
    all_predictions = []
    for p in portfolios:
        portfolio_id = p["portfolio"]["portfolio_id"]
        portfolio_name = p["portfolio"]["name"]
        predictions_url = f"{STOCK_PREDICTIONS_API}/{portfolio_id}"
        predictions = safe_get(predictions_url)
        for entry in predictions:
            entry["portfolio_id"] = portfolio_id
            entry["portfolio_name"] = portfolio_name
        all_predictions.extend(predictions)
    
    # Convert to DataFrame
    return pd.DataFrame(all_predictions)

def summarize_portfolio(df: pd.DataFrame):
    df["total_purchase"] = df["purchase_price"] * df["quantity"]
    df["total_current"] = df["current_price"] * df["quantity"]
    return round(df["total_purchase"].sum(), 2), round(df["total_current"].sum(), 2)

def create_prompt(df: pd.DataFrame, portfolio_name: str, user_query: str) -> str:
    total_purchase, total_current = summarize_portfolio(df)
    preview = df.to_csv(index=False)
    return f"""
You are a professional financial analyst. You are given all stock-level data for the portfolio named "{portfolio_name}". Use this complete information to answer the user's question intelligently.
Now respond to the user's question politely. Keep it conversational, concise, and helpful — like you're chatting with them directly. Avoid over-explaining, and skip any redundant analysis unless asked.
If the user just greets you (e.g., says "hello", "how are you", etc.), feel free to respond casually — like "Hi there! How can I help you with your portfolio today?"

Avoid repeating data unless asked. Just be helpful, human-like, and straight to the point.
Here is the full portfolio data:
{preview}


- Total Purchase Value (quantity × purchase_price): ${total_purchase}
- Total Current Value (quantity × current_price): ${total_current}

Now answer the question below clearly and accurately based ONLY on the data above:

User's Question:
{user_query}
Respond in a structured manner.
"""

def query_llm(prompt: str) -> str:
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        st.error(f"LLM API error: {e}")
        return "Sorry, I encountered an error processing your request. Please try again later."

# --- Streamlit UI Setup ---
st.set_page_config(page_title="PacRobo Portfolio Chat", layout="wide")

# Dark ChatGPT-style sticky header and background
st.markdown("""
<style>
/* Dark background for entire app */
body, .stApp {
    background-color: #1e1e1e;
    color: #f0f0f0;
}

/* Sticky header */
.sticky-header {
    position: sticky;
    top: 0;
    background: linear-gradient(to right, #121212, #1e1e1e); /* dark gradient */
    padding: 20px;
    z-index: 999;
    border-bottom: 1px solid #333;
    box-shadow: 0 2px 10px rgba(0, 255, 204, 0.2); /* subtle glow */
    text-align: center;
}

.chat-title {
    font-size: 28px;
    font-weight: 700;
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    color: #00ffcc; /* your existing vibrant color */
    letter-spacing: 1px;
    text-shadow: 0 0 6px rgba(0, 255, 204, 0.5);
    display: inline-block;
    padding: 5px 20px;
    border-radius: 12px;
}

/* WhatsApp-style user bubble */
.user-bubble {
    background-color: #dcf8c6 !important;
    color: black !important;
    padding: 10px 15px;
    border-radius: 18px;
    max-width: 80%;
    display: inline-block;
    line-height: 1.4;
    word-wrap: break-word;
    box-shadow: 0 0 5px rgba(0,0,0,0.2);
}

/* AI bubble */
.ai-bubble {
    background-color: #2d2d2d;
    color: #e0e0e0;
    padding: 10px 15px;
    border-radius: 18px;
    max-width: 80%;
    display: inline-block;
    line-height: 1.4;
    word-wrap: break-word;
    box-shadow: 0 0 5px rgba(0,0,0,0.2);
}
</style>

<!-- Sticky header -->
<div class='sticky-header'>
    <div class='chat-title'>🤖 PacRobo AI Chatbot</div>
</div>
""", unsafe_allow_html=True)

# Session state
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# Fetch data
with st.spinner("Fetching portfolio data..."):
    df = fetch_portfolio_data()

# Check if data was fetched successfully
if df.empty:
    st.error("No portfolio data available. Please check your API configuration.")
else:
    unique_portfolios = df["portfolio_name"].dropna().unique().tolist()

    st.markdown(
        "<h4 style='color:#00ffcc; margin-top: 30px;'>📁 Select a Portfolio</h4>",
        unsafe_allow_html=True
    )
    selected_portfolio = st.selectbox("", options=unique_portfolios)

    # Filter portfolio-specific data
    filtered_df = df[df["portfolio_name"] == selected_portfolio]

    def render_chat_message(role: str, content: str):
        if role == "user":
            st.markdown(
                f"""
                <div style='display: flex; justify-content: flex-end;'>
                    <div class='user-bubble'>
                        <strong>You</strong><br>{content}
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f"""
                <div style='display: flex; justify-content: flex-start;'>
                    <div class='ai-bubble'>
                        <strong>PacRobo Analyst</strong><br>{content}
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )

    # Render message history
    for msg in st.session_state.chat_history:
        render_chat_message(msg["role"], msg["content"])

    # User message input
    user_input = st.chat_input("Ask your question about this portfolio...")

    if user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})

        with st.spinner("Thinking..."):
            prompt = create_prompt(filtered_df, selected_portfolio, user_input)
            response = query_llm(prompt)

        st.session_state.chat_history.append({"role": "assistant", "content": response})
        st.rerun()
