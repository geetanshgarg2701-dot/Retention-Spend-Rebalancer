# Retention Spend Rebalancer

A web app that reads an order export from a business store and shows whether to move ad budget from winning new customers to keeping existing ones.

Status: Weeks 1 and 2 of a six-week build are working. You can load an order export, confirm how its columns match, review every cleaning decision, and see retention results. The budget scenario slider and the AI summary come in later weeks. The project brief and plan are in CLAUDE.md.

## What works today
1. Upload a CSV of past orders, or load the synthetic sample.
2. Confirm the column matches. Each suggestion shows its confidence and the reason for it. A date format option and a line item option are included.
3. Review the cleaning: metrics, a rule-by-rule table of what was removed and why, warnings, a preview, and a download of the clean CSV.
4. See retention results: an overview row with orders per month, how many customers come back the month after, customers by segment and payback progress, then the repeat purchase rate, a funnel of customers by order count, cohort retention by first order month, customer segments, and customer value with payback.

Everything on the results screen is observed in the orders. Nothing is forecast. Payback needs a cost to win one customer that you enter yourself, and there is no default. Margin is optional, and without it payback uses revenue and says so.

Files can have up to 500,000 rows and 25 MB. The app explains in plain words when a file is empty, is not a CSV, or cannot be parsed.

## Look and fonts
The interface uses a dark slate theme with one teal accent, set in .streamlit/config.toml and src/ui.py. Progress is shown as linked hexagon steps. Cards and layers fade in with short, one-time motion that switches off for anyone who has reduced motion turned on in their system. Text and accent colors are tested for at least 4.5 to 1 contrast, and the colors never carry meaning alone, since every confidence level is also written in words. The fonts are DM Sans for body text and Fraunces for headings and large numbers. Both are licensed under the SIL Open Font License 1.1 and are served from this repo in static/fonts, so no font is loaded from another site. The license files are next to the fonts.

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

The tests cover parsing, column matching, the cleaning rules with hand-checked counts, the retention metrics with every figure worked out by hand, the synthetic data, upload validation, and smoke tests of the app on the synthetic sample.

## AI column matching
Column matching works without AI. To add AI suggestions, set GEMINI_API_KEY and GEMINI_MODEL as environment variables before you start the app. The app does not read a .env file. The live check script in scripts does read one, so you can copy .env.example to .env for that script. Check Google's current model list before choosing a model name. Without both values the AI switch stays off. Never commit the .env file.

## Privacy
Files are processed in the session and are not stored. If AI column matching is on, only column names and up to three masked sample values per column go to the Gemini API, with emails and phone-like numbers replaced by placeholders. Columns that look personal, such as names, phones, addresses and notes, send the column name only. Order rows and customer data are never sent. On the free Gemini tier, Google may use what is sent to improve its products, and people may review it, so keep AI matching off for data you consider sensitive. The AI switch can be turned off at any time.

## Data
The demo dataset is synthetic and generated for this project with a fixed random seed. It is not a real business, and every row says so. The repeat buying pattern in it is a modeling choice for the demo, not a statistic. Regenerate it with:

    python -m src.sample_data

The command refuses to overwrite an existing file.

## Project layout
- app.py: the four-stage Streamlit app
- src/loading.py: upload validation
- src/mapper.py: rule-based and optional AI column matching
- src/cleaning.py: the eight cleaning rules, warnings and stats
- src/metrics.py: repeat rate, order count funnel, cohorts, segments, customer value and payback
- src/ui.py: the stepper, confidence pills, funnel and styling helpers
- static/fonts: DM Sans and Fraunces with their licenses
- src/parsing.py: date and money helpers
- src/sample_data.py: the synthetic export generator
- scripts: a one-call live check of the Gemini column matching
- tests: the test suite
