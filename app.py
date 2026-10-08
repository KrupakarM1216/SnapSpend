import json
import time

import pandas as pd
import streamlit as st
from google import genai
from google.genai import types
from twilio.rest import Client as TwilioClient

from prompts import EXTRACT_PROMPT, SYSTEM_PROMPT, WELCOME_MESSAGE_TEMPLATE

st.set_page_config(page_title="SnapSpend", page_icon="🧾", layout="wide")

# ---------- config ----------
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
MODEL_NAME = st.secrets.get("GEMINI_MODEL", "gemini-2.5-flash")
FALLBACK_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
TWILIO_ACCOUNT_SID = st.secrets["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = st.secrets["TWILIO_AUTH_TOKEN"]
TWILIO_WHATSAPP_FROM = st.secrets["TWILIO_WHATSAPP_FROM"]
TWILIO_CONTENT_SID = st.secrets["TWILIO_CONTENT_SID"]


@st.cache_resource
def get_gemini_client():
    return genai.Client(api_key=GEMINI_API_KEY)


@st.cache_resource
def get_twilio_client():
    return TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


gemini_client = get_gemini_client()
twilio_client = get_twilio_client()


# ---------- helpers ----------
def is_busy_error(error):
    text = str(error)
    return "503" in text or "UNAVAILABLE" in text or "429" in text or "RESOURCE_EXHAUSTED" in text


def render_message(message):
    with st.chat_message(message["role"]):
        if message["kind"] == "text":
            st.write(message["content"])
        elif message["kind"] == "image":
            st.image(message["content"], width=260)


def add_message(role, kind, content):
    st.session_state.messages.append({"role": role, "kind": kind, "content": content})
    render_message(st.session_state.messages[-1])


def ask_gemini(parts):
    """Chat call with retries when Gemini is busy."""
    for attempt in range(4):
        try:
            return st.session_state.chat.send_message(parts).text
        except Exception as error:
            if is_busy_error(error) and attempt < 3:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
                continue
            if is_busy_error(error):
                return "Gemini is very busy right now. Please try again in a minute."
            return f"Sorry, something went wrong: {error}"


def generate_with_retry(**kwargs):
    """One-shot call with retries, falling back to other models when busy."""
    last_error = None
    for model in dict.fromkeys([MODEL_NAME] + FALLBACK_MODELS):
        for attempt in range(3):
            try:
                return gemini_client.models.generate_content(model=model, **kwargs)
            except Exception as error:
                last_error = error
                if is_busy_error(error):
                    time.sleep(2 ** attempt)
                    continue
                raise
    raise last_error


def extract_receipt(photo_bytes, mime_type):
    """Vision step: receipt photo -> structured dict (or None + error message)."""
    try:
        response = generate_with_retry(
            contents=[
                types.Part.from_bytes(data=photo_bytes, mime_type=mime_type),
                EXTRACT_PROMPT,
            ],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        data = json.loads(response.text)
        if isinstance(data, list):
            data = data[0] if data else {"error": "empty"}
        if "error" in data:
            return None, "That doesn't look like a receipt. Try a clearer photo."
        data["total"] = float(data.get("total") or 0)
        data["merchant"] = data.get("merchant") or "Unknown"
        data["category"] = data.get("category") or "Other"
        data["date"] = data.get("date") or ""
        return data, None
    except Exception as error:
        return None, f"I couldn't read that receipt: {error}"


def build_summary():
    expenses = st.session_state.expenses
    total = sum(e["total"] for e in expenses)
    by_cat = {}
    for e in expenses:
        by_cat[e["category"]] = by_cat.get(e["category"], 0) + e["total"]
    lines = [f"🧾 {e['merchant']} ({e['category']}): ₹{e['total']:.2f}" for e in expenses]
    cats = ", ".join(f"{c} ₹{v:.0f}" for c, v in sorted(by_cat.items(), key=lambda x: -x[1]))
    return " | ".join(lines) + f" | 💰 Total: ₹{total:.2f} | By category: {cats}"


def clean_whatsapp_text(text):
    if not text:
        return "No expense summary available."
    text = " ".join(text.split())
    return text[:1500] + "..." if len(text) > 1500 else text


def send_whatsapp(to_number, user_name, summary):
    # Content template expects {{1}} = name, {{2}} = summary.
    try:
        content_variables = json.dumps(
            {"1": user_name, "2": clean_whatsapp_text(summary)}, ensure_ascii=False
        )
        message = twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=f"whatsapp:{to_number}",
            content_sid=TWILIO_CONTENT_SID,
            content_variables=content_variables,
        )
        return True, message.sid
    except Exception as error:
        return False, str(error)


# ---------- onboarding ----------
if "onboarded" not in st.session_state:
    st.title("🧾 SnapSpend")
    st.caption("Snap a receipt. Track every rupee. Text yourself the summary.")
    with st.form("onboarding_form"):
        name = st.text_input("Your name")
        whatsapp_number = st.text_input(
            "WhatsApp number (with country code)",
            placeholder="+91XXXXXXXXXX",
            help="This is the number SnapSpend will text your summary to.",
        )
        submitted = st.form_submit_button("Let's go 🚀")
    if submitted:
        if not name.strip() or not whatsapp_number.strip():
            st.warning("Please fill in both your name and WhatsApp number.")
        else:
            st.session_state.name = name.strip()
            st.session_state.whatsapp_number = whatsapp_number.strip().replace(" ", "")
            st.session_state.chat = gemini_client.chats.create(
                model=MODEL_NAME,
                config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
            )
            st.session_state.messages = []
            st.session_state.expenses = []
            st.session_state.onboarded = True
            st.rerun()
    st.stop()

# ---------- header ----------
header_col, button_col = st.columns([5, 2], vertical_alignment="center")
with header_col:
    st.title("🧾 SnapSpend")
with button_col:
    if st.button(
        "📤 Send to WhatsApp",
        disabled=len(st.session_state.expenses) == 0,
        width="stretch",
    ):
        with st.spinner("Sending..."):
            success, info = send_whatsapp(
                st.session_state.whatsapp_number, st.session_state.name, build_summary()
            )
        if success:
            st.success("Sent! Check your WhatsApp 📲")
        else:
            st.error(f"Couldn't send that: {info}")

st.caption(f"Logged in as {st.session_state.name} - summaries go to {st.session_state.whatsapp_number}")

chat_col, dash_col = st.columns([3, 2], gap="large")

# ---------- dashboard ----------
with dash_col:
    st.subheader("Your expenses")
    expenses = st.session_state.expenses
    if expenses:
        df = pd.DataFrame(expenses)[["date", "merchant", "category", "total"]]
        st.metric("Total spent", f"₹{df['total'].sum():,.2f}")
        st.dataframe(df, width="stretch", hide_index=True)
        st.bar_chart(df.groupby("category")["total"].sum())
        if st.button("🗑️ Clear expenses"):
            st.session_state.expenses = []
            st.rerun()
    else:
        st.info("No receipts yet. Attach a photo in the chat to log your first one.")

# ---------- chat history ----------
with chat_col:
    if not st.session_state.messages:
        add_message("assistant", "text", WELCOME_MESSAGE_TEMPLATE.format(name=st.session_state.name))
    else:
        for message in st.session_state.messages:
            render_message(message)

# ---------- input ----------
user_input = st.chat_input(
    "Attach a receipt photo, or ask about your spending",
    accept_file=True,
    file_type=["jpg", "jpeg", "png"],
)

if user_input:
    photo = user_input.files[0] if user_input.files else None
    text = user_input.text
    needs_rerun = False

    with chat_col:
        if photo is not None:
            photo_bytes = photo.getvalue()
            add_message("user", "image", photo_bytes)
            with st.spinner("Reading your receipt..."):
                data, error = extract_receipt(photo_bytes, photo.type)
            if data:
                st.session_state.expenses.append(data)
                add_message(
                    "assistant",
                    "text",
                    f"Logged! {data['merchant']} - ₹{data['total']:.2f} ({data['category']})"
                    + (f", dated {data['date']}." if data["date"] else "."),
                )
                needs_rerun = True
            else:
                add_message("assistant", "text", error)

        if text:
            add_message("user", "text", text)
            context = json.dumps(st.session_state.expenses, ensure_ascii=False)
            with st.spinner("Thinking..."):
                answer = ask_gemini(f"Logged expenses (JSON): {context}\n\nUser: {text}")
            add_message("assistant", "text", answer)

    if needs_rerun:
        st.rerun()