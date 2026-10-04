# Retention Spend Rebalancer

A web app that reads an order export from a small online store and shows whether to move ad budget from winning new customers to keeping existing ones.

Status: Week 1 of a six-week build. Project brief and plan are in CLAUDE.md.

## Run locally
    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    streamlit run app.py

## Privacy
Files are processed in the session and are not stored. If AI column matching is on, only column names and a few masked sample values go to the Gemini API. The switch is off when no key is set.

## Data
The demo dataset is synthetic and generated for this project. It is not a real business.
