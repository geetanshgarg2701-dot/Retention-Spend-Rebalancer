# Retention Spend Rebalancer

A web app that reads an order export from a business store and shows whether to move ad budget from winning new customers to keeping existing ones.

Status: Weeks 1 to 4 of a six-week build are working. You can load an order export, confirm how its columns match, review every cleaning decision, see retention results, try a budget scenario, and get a plain-English summary, ideas for each customer group and answers to your own questions. The project brief and plan are in CLAUDE.md.

## What works today
1. Upload a CSV of past orders, or load the synthetic sample.
2. Confirm the column matches. Each suggestion shows its confidence and the reason for it. A date format option and a line item option are included.
3. Review the cleaning: metrics, a rule-by-rule table of what was removed and why, warnings, a preview, and a download of the clean CSV.
4. See retention results: an overview row with orders per month, how many customers come back the month after, customers by segment and payback progress, then the repeat purchase rate, a funnel of customers by order count, cohort retention by first order month, customer segments, and customer value with payback.
5. Try a budget scenario: enter your budget, your current split and what it costs to win and to bring back a customer, then move a slider to see the estimated change in value, the chance the move beats your current split, and the customers won and brought back. A simulation of 2,000 draws gives a range instead of one number, and an assumptions table lists every input and where it came from.
6. Open the insights screen for a summary, ideas for each customer group and a way to ask questions of your orders.

Files can have up to 500,000 rows and 25 MB. The app explains in plain words when a file is empty, is not a CSV, or cannot be parsed.

## How the numbers and the AI fit together
Numbers come from code. Words can come from AI, and the AI never calculates a figure.

- The results screen is observed in your orders. Nothing there is forecast. Payback needs a cost to win one customer that you enter yourself, and there is no default. Margin is optional, and without it payback uses revenue and says so.
- The scenario screen is an estimate, not a forecast. Customer value comes from your orders. The cost to bring a customer back is your own figure, because orders cannot show whether retention spend works. The diminishing returns setting is an illustrative assumption you can change, and the screen warns when the best move sits at the edge of the range it tests. The default for extra orders comes from customers who returned on their own, so it may overstate what a customer you pay to bring back is worth.
- The insights screen sends the AI only figures the code already calculated. Every figure in the AI's text is checked against those figures. If it contains a figure that is not there, a spelled-out number or a claim that is too certain, the text is thrown away and the app's own text is shown. The summary asks the AI to reword sentences the app wrote itself, shows it shares as percentages so it has no raw decimals to copy, and gives it one retry with the reason if a check fails. On five different synthetic datasets with retries off, all five summaries passed on the first try. The checker lives in src/checker.py and is tested by hand.
- Ask your data lets the AI write one query from the column names and types alone. The app checks that it is a single SELECT on the orders table, runs it locally with DuckDB, and shows you the query and the result. The result is never sent back to the AI. Ready-made questions need no AI at all.

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

The tests cover parsing, column matching, the cleaning rules with hand-checked counts, the retention metrics and the scenario model with every figure worked out by hand, the number checker, the database guard with a long list of attack queries, the synthetic data, upload validation, and smoke tests of the app on the synthetic sample. No test can reach a real key or call the model, even when a real .env exists.

## AI features
Everything works without AI. To turn it on, give the app a Gemini key and a model name. The app looks in this order: environment variables, then a .env file in the project folder, then Streamlit secrets. Copy .env.example to .env for local runs, and use Streamlit secrets when you deploy. Check Google's current model list before choosing a model name. Without both values the AI switches stay off. Never commit the .env file, which is already ignored by git.

The free Gemini tier has daily limits that are shared by everyone using the app, so each session is capped at 10 AI calls on the insights screen. When the limit is reached or a call fails, the app shows its own text and tells you why.

## Privacy
Files are processed in the session and are not stored.

- Column matching, if AI is on: only column names and up to three masked sample values per column go to the Gemini API, with emails and phone-like numbers replaced by placeholders. Columns that look personal, such as names, phones, addresses and notes, send the column name only. Order rows and customer data are never sent.
- Summary and ideas: only calculated figures go to the Gemini API. The insights screen shows them under Exactly what is sent. No customer id, email, order row or order value from your file is included.
- Ask your data: your question and the column names and types go to the Gemini API. The result is never sent back.
- On the free Gemini tier, Google may use what is sent to improve its products, and people may review it, so keep AI off for data you consider sensitive, and do not type customer names or emails into a question.

## Data
The demo dataset is synthetic and generated for this project with a fixed random seed. It is not a real business, and every row says so. The repeat buying pattern in it is a modeling choice for the demo, not a statistic. Regenerate it with:

    python -m src.sample_data

The command refuses to overwrite an existing file.

## Project layout
- app.py: the six-stage Streamlit app
- src/loading.py: upload validation
- src/mapper.py: rule-based and optional AI column matching
- src/cleaning.py: the eight cleaning rules, warnings and stats
- src/metrics.py: repeat rate, order count funnel, cohorts, segments, customer value and payback
- src/scenario.py: the budget scenario model, simulation, sentences and assumptions table
- src/checker.py: checks AI text against the calculated figures
- src/insights.py: what is sent to the AI, the prompts, the summary and the segment ideas
- src/askdata.py: the DuckDB sandbox, the query guard and the ready-made questions
- src/aiconfig.py: where the key and model name come from
- src/ui.py: the stepper, confidence pills, funnel and styling helpers
- src/parsing.py: date and money helpers
- src/sample_data.py: the synthetic export generator
- static/fonts: DM Sans and Fraunces with their licenses
- scripts: live checks of the Gemini features, which print what they send before calling anything
- tests: the test suite
