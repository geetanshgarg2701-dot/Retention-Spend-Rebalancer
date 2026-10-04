# Retention Spend Rebalancer

A web app that reads an order export from a small online store and shows whether to move ad budget from winning new customers to keeping existing ones.

Status: Week 1 of a six-week build is working. You can load an order export, confirm how its columns match, and review every cleaning decision. Retention analysis, the budget scenario slider and the AI summary come in later weeks. The project brief and plan are in CLAUDE.md.

## What works today
1. Upload a CSV of past orders, or load the synthetic sample.
2. Confirm the column matches. Each suggestion shows its confidence and the reason for it. A date format option and a line item option are included.
3. Review the cleaning: metrics, a rule-by-rule table of what was removed and why, warnings, a preview, and a download of the clean CSV.

Files can have up to 500,000 rows and 25 MB. The app explains in plain words when a file is empty, is not a CSV, or cannot be parsed.

## Run locally
Windows PowerShell:

    python -m venv .venv
    .venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    streamlit run app.py

macOS or Linux:

    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    streamlit run app.py

## Run the tests
    python -m pytest

The tests cover parsing, column matching, the cleaning rules with hand-checked counts, the synthetic data, upload validation, and a smoke test of the app on the synthetic sample.

## AI column matching
Column matching works without AI. To add AI suggestions, copy .env.example to .env and set GEMINI_API_KEY and GEMINI_MODEL, or set them as environment variables. Check Google's current model list before choosing a model name. Without both values the AI switch stays off. Never commit the .env file.

## Privacy
Files are processed in the session and are not stored. If AI column matching is on, only column names and up to three masked sample values per column go to the Gemini API, with emails replaced by a placeholder. Order rows and customer data are never sent. The AI switch can be turned off at any time.

## Data
The demo dataset is synthetic and generated for this project with a fixed random seed. It is not a real business, and every row says so. The repeat buying pattern in it is a modeling choice for the demo, not a statistic. Regenerate it with:

    python -m src.sample_data

The command refuses to overwrite an existing file.

## Project layout
- app.py: the three-stage Streamlit app
- src/loading.py: upload validation
- src/mapper.py: rule-based and optional AI column matching
- src/cleaning.py: the eight cleaning rules, warnings and stats
- src/parsing.py: date and money helpers
- src/sample_data.py: the synthetic export generator
- tests: the test suite
