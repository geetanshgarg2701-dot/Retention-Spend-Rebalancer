# Retention Spend Rebalancer: build guide

This guide explains how the app was built, in the order it was built, so someone else can rebuild it or continue the work. It holds no keys, passwords or personal data. Where a secret is needed, it says where to put one and never shows one.

All sample data in this project is synthetic. Any figure from the sample says nothing about real stores.

## 1. What you are building

A Streamlit web app for business online stores. The owner uploads a CSV of past orders and learns whether to move some ad budget from winning new customers to keeping existing ones, and by how much.

Two rules shape every step:

1. Numbers come from code. The AI only writes words and never calculates a figure.
2. Everything runs free. Stop and ask before any action that could cost money.

## 2. Tools and versions

Use these exact versions, because later steps rely on how they behave.

- Python 3.12
- streamlit 1.65.0
- pandas 3.0.6
- numpy 2.5.3
- altair 6.3.0
- google-genai 2.28.0
- duckdb 1.5.6
- python-dotenv 1.2.4
- For development only: pytest 9.1.1 and pip-audit 2.10.1

Keep runtime pins in `requirements.txt` and development tools in `requirements-dev.txt`, which includes the first file.

## 3. Set up the project

1. Create the project folder and initialize git.
2. Make a virtual environment outside any cloud-synced or redirected folder. On Windows, a redirected AppData folder broke virtual environments, so the environment lives in a local temp folder.
3. Install the requirements.
4. Create `.gitignore` so it covers `.env` and `.streamlit/secrets.toml`. Check this before the first commit.
5. Add `.streamlit/secrets.toml.example` with placeholder values only.
6. Set the git author and committer email to your GitHub noreply address for this repo only.
7. Write `CLAUDE.md` in the project root with the rules, the design rules and the plan.

Project layout:

- `app.py`: the six stages of the interface
- `src/`: parsing, loading, mapper, cleaning, sample_data, metrics, scenario, checker, insights, askdata, aiconfig, ui
- `tests/`: one test file per module, plus `conftest.py`
- `data/`: the synthetic sample file
- `static/fonts/`: bundled fonts and their license files
- `.streamlit/`: `config.toml` and the secrets example
- `scripts/`: live-check scripts, dated, which only call the model when run with `--send`

## 4. Week 1: data foundation

Goal: a messy order export loads, the columns are matched and confirmed, and every cleaning decision is visible.

### Parsing and loading

- Parse money in mixed formats, such as currency symbols and thousands commas.
- Strip time zone suffixes from dates and infer day first or month first.
- Read files as text with blank cells kept as empty strings.
- Validate every upload: CSV only, a 25 MB size cap and a 200,000 row cap. Show a plain message on empty files and parse errors.

The row cap started at 500,000. After measuring memory, it was lowered to 200,000 to fit the free hosting tier. See section 11.

### Column mapper

Canonical fields. Required: customer_id, order_date, order_value. Optional: order_id, order_status, and a quantity that multiplies a unit price.

The rule-based mapper always runs:

- Score each header against each field. A name score is 1.0 for an exact synonym, 0.75 when a synonym is inside the header and 0.5 when the header is inside a synonym. Zero the score when the header holds a negative token such as name, phone, tax, shipping or discount.
- Add a content score from up to 500 non-blank values. Dates score by share matching a date pattern. Values score by share parseable as money, with a penalty for long unique integers that look like ids. Customer ids score by fill rate.
- Total score is 0.6 times the name score plus 0.4 times the content score. Assign greedily from the highest score, one column per field. Required fields need at least 0.38. Customer id is never assigned on content alone.
- Confidence is high at 0.8 and above, medium at 0.55 and above, otherwise low. Return a plain reason for each field.

The AI mapper is optional:

- Send only headers plus up to three masked sample values per column. Mask emails and truncate long values.
- Ask for JSON only. Accept only headers that exist in the file and never reuse one. Fall back to the rules on any failure.
- If the rules and the AI agree, confidence is high. If they disagree, show low confidence and tell the user to check.
- The model call is an injected function, so tests can fake it.
- The user always confirms before anything runs, and there is a switch to turn AI matching off.

### Cleaning

`clean_orders` takes the raw frame, the confirmed mapping, a day-first option and a line-item mode of sum or first. It returns the clean frame, a steps log, warnings and stats. Rules run in this order:

1. Drop unreadable dates. If numeric dates are ambiguous, assume month first and warn.
2. Drop unreadable order values.
3. Drop refunded, voided, cancelled, failed, returned and chargeback statuses. Keep partial refunds.
4. Drop negative values.
5. Drop zero-value orders.
6. Drop missing or placeholder customer ids, such as guest. Lowercase emails.
7. If an order id is mapped, combine repeated rows into one order, by summing line values or taking the first value.
8. Keep exact duplicate rows that have no order id, and warn, because identical orders can be real.

Warnings fire for fewer than 200 orders, fewer than 50 customers, a span under 90 days, no repeat customers, and more than 30 percent of rows removed.

### Synthetic sample

Write a seeded generator for about 1,500 customers over 24 months with repeat decay and a loyal group. Make it messy on purpose: mixed date formats, currency symbols, refund and void statuses, blank emails, a few unreadable dates, zero-value orders and noise columns. Save it to `data/synthetic_orders_messy.csv`. Label it synthetic everywhere it appears.

### Interface and tests

- Stage 1 uploads a file or loads the sample. Stage 2 confirms columns. Stage 3 reviews cleaning with metrics, the steps table, warnings, a preview and a clean CSV download.
- Store state per dataset so a new file resets the flow.
- Test parsing, the mapper with Shopify, WooCommerce and UCI style headers, a faked AI response, a malformed response and a disagreement, and cleaning with a small frame whose counts can be checked by hand. Add a smoke test with Streamlit AppTest.

## 5. Week 2: metrics

Add `src/metrics.py`:

- Cohorts by calendar month of first order, with a retention table.
- Repeat purchase rate.
- RFM scores by percent rank, which feed six segments: New, Champions, Loyal, At risk, Lapsed and Occasional.
- A customer value curve and a payback month, margin aware.

Check at least one result by hand in a test. Compute the expected value on paper first, then compare.

## 6. Interface redesign

The first version looked plain, so the interface was restyled while keeping the design rules: sentence case, no emojis, no all-caps labels, no gradients, no drop-shadow cards, no pure white background, no purple and black scheme, and no Inter, Geist or Space Grotesk.

1. Bundle DM Sans and Fraunces in `static/fonts` with their license files, so nothing loads from a font service at runtime. Get approval before downloading.
2. Set the theme, fonts and `enableStaticServing` in `.streamlit/config.toml`. Also set the viewer toolbar mode, hide error details and set the upload cap.
3. Put reusable HTML and CSS helpers in `src/ui.py`. Escape any text that comes from the user, because file names and headers are untrusted.
4. Add a stepper, headline cards and confidence pills that also say their level in words.
5. Use native `st.metric` sparklines and altair charts. Streamlit strips inline SVG, so SVG sparklines disappear.
6. Check text and background contrast against a 4.5 to 1 minimum with a small script.

## 7. Week 3: budget scenario

Add `src/scenario.py`.

- Customers from a channel equal reference spend divided by cost, times the ratio of spend to reference spend raised to an exponent. The exponent models diminishing returns. Reference spend is today's spend on that channel, or 10 percent of the budget when today's spend is zero.
- New customers are worth the observed cumulative value at the chosen horizon. Brought-back customers are worth extra orders times order value.
- Gain equals total value after the shift minus total value today.
- A simulation draws the cost to win, cost to bring back, extra orders and exponent from triangular ranges, by default plus or minus 25 percent. Use 2,000 draws and a fixed seed of 42. Report the 10th percentile, median, 90th percentile, the chance of a gain and the best shift.
- Warn when the best shift sits at the edge of the allowed range.
- Label every output as an estimate and show an assumptions panel with editable values.
- Hand-check two cases: a 10 percent shift adds 100 on a baseline of 2,200 with exponent 1, and the best shift is exactly 16 percent with exponent 0.5.

## 8. Week 4: AI insights

### Number checker

`src/checker.py` checks every AI sentence before it is shown.

- Every number must match a known fact, as given or rounded to 0, 1 or 2 places.
- A number written with a percent sign or the word percent may also match a share times 100. A plain number may not. This closed a hole where "30 days" passed because a share was 30.12 percent.
- Reject spelled-out numbers other than "one", overclaim phrases, and text over a word limit.

### Summary and segment ideas

- Send the model only aggregate facts. Never send raw customer rows.
- Include the app's own verified sentences in the prompt so the model rephrases rather than computes.
- On a rejection, retry once and pass the checker's reason. If it still fails, show the app's own text.
- Segment ideas return as strict JSON, each idea is checked, and any failure falls back to built-in ideas.
- Cap usage at 10 calls per session and 150 per day across the whole app. Keep the daily cap thread safe and refund the session when the day cap blocks a call.

### Ask your data

`src/askdata.py` lets a user ask a question that the model turns into SQL. Treat that SQL as untrusted and use several layers:

1. Allow exactly one statement of type SELECT whose first word is select, with or from. DuckDB classifies DESCRIBE, SHOW and SUMMARIZE as SELECT, so the first word check is required.
2. Inspect DuckDB's own parse tree. Reject table functions, allow only the orders table and its own CTE names, and deny file and settings functions.
3. Run each query on a fresh in-memory connection with external access off, a locked configuration, a 5 second timeout, a 1,000 row cap and a memory limit. Early testing showed DROP TABLE succeeding on a locked connection, so the data lives in a view on a throwaway connection and nothing persists.

## 9. Keys and configuration

Read the Gemini key from an environment variable, then a local `.env` file, then Streamlit secrets. Never commit it, never log it and never paste it in chat or a screenshot.

- Local: put `GEMINI_API_KEY` and `GEMINI_MODEL` in `.env`.
- Hosted: paste the same names as TOML in the app's Secrets box, plus `AI_DAILY_LIMIT`.
- Use a separate key for the hosted app. If a key is ever exposed, delete it in the provider's console and make a new one.
- The default model is a small flash-lite model. Check the provider's current free-tier limits and model names before relying on them, because they change.
- In `tests/conftest.py`, clear the key, model and limit variables before every test, so no test can use a real key. Set a flag that makes the app's error handler re-raise during tests.

## 10. Test discipline

- Run `python -m pytest` after every change. The suite reached 516 passing tests.
- Test AI guards with real model output as well as fakes. Two checker flaws only showed up in live calls.
- Read a passing AI output for quality, not only for number matches.
- Live-check scripts default to a dry run and call the model only with `--send`.
- Read tests back after writing them. Remove placeholder assertions and contorted conditions, and work out expected values on paper.

## 11. Week 5: hardening and deploy

1. Pin exact dependency versions and run `pip-audit`. It found no known vulnerabilities in the pinned set.
2. Measure memory on large synthetic files. A file with 150,000 wide rows peaked near 382 MB, and 500,000 narrow rows peaked near 529 MB. The free host offers a minimum of 690 MB, so the row cap was set to 200,000.
3. Add a main-level error handler that shows a plain message and logs only the error type and screen.
4. Add a privacy section to the README that says what is and is not sent to the model, and note that the hosting platform makes its own outside requests.
5. Push to GitHub.
6. On Streamlit Community Cloud, create the app from the repo, choose Python 3.12, and paste the secrets in TOML. A private repo did not connect, so the repo was made public. Review the repo for secrets before making it public.
7. Open the live app and confirm the numbers match the local run exactly.

## 12. Still open

- Test a real file upload on the live app.
- Verify the CMO Survey figure cited in the brief against its source.
- Week 6: run the tool on three real businesses, get two reviewers to rate the result 4 out of 5 or higher, and write the case study, the LinkedIn post and the interview story.

## 13. Limits to state honestly

- Orders alone cannot show whether retention spend works. The cost to bring a customer back and the diminishing returns exponent are assumptions.
- Default extra orders come from customers who returned on their own, so they may overstate brought-back customers.
- The checker verifies figures, not every misleading phrase.
- The daily AI cap lives in server memory, so a restart resets it.
- All testing so far used synthetic data.
