# 🧾 SnapSpend - AI Receipt & Expense Tracker

Upload a photo of a receipt and Gemini Vision reads the merchant, date, category
and total, logs it to a live dashboard, and lets you chat about your spending.
One click texts a full expense summary to your WhatsApp.

**Live demo:** _add your Streamlit Community Cloud URL here_

## Features
- Receipt photo -> structured data (Gemini Vision, JSON output)
- Chat about your expenses ("how much did I spend on food?")
- Dashboard: total, expense table, spending by category
- WhatsApp summary via Twilio Content Template

## Tech stack
Python, Streamlit, Google Gemini (`google-genai`), Twilio WhatsApp, pandas

## Setup
1. Python 3.9+; create and activate a venv, then `pip install -r requirements.txt`
2. Get a Gemini API key at aistudio.google.com
3. Twilio: create a free account, join the WhatsApp sandbox
   (Messaging -> Try it out -> Send a WhatsApp message) and create a Content
   Template with `Hi {{1}}, here's your SnapSpend summary:\n\n{{2}}`
4. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`, fill in values
5. Run: `streamlit run app.py`

## Deploy
Push to a public GitHub repo (never commit `secrets.toml`), create the app on
share.streamlit.io, and paste your secrets into Settings -> Secrets.

## Structure
- `app.py` - UI, vision extraction, chat, WhatsApp
- `prompts.py` - AI personality and extraction prompt
