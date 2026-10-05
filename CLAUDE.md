# Retention Spend Rebalancer: project brief for Claude Code

Read this file first. It holds the plan, the rules, and the exact Week 1 spec.

## What this is
A Streamlit web app for business online stores. The owner uploads a CSV of past orders and gets an answer to one question: should we move some ad budget from winning new customers to keeping existing ones, and how much?

Evidence behind the idea: The CMO Survey, Spring 2026, from Duke Fuqua, found acquisition budgets about 26% larger than retention budgets, while retention was the strongest performance driver. Few tools give a business online store a plain budget answer with the assumptions visible.

The builder is an MBA marketing student. This is a portfolio project that must read as a real marketing tool, not a class demo.

## Non-negotiable rules
1. Numbers come from code. Words come from AI. The AI never calculates a figure.
2. Everything runs free. Before any action that could cost real money, stop and ask for a go-ahead. Do this every time.
3. Plan first. For any multi-step task, outline the plan and wait for approval. After each major step, summarize what was done and what is next.
4. Never delete, overwrite, or rename an existing file without showing the change and getting confirmation. Stay inside this project folder.
5. New files use the format YYYY-MM-DD-descriptive-name where a dated name makes sense. At the end of every task, list every file created or modified.
6. No invented statistics. Label every scenario output as an estimate. Label demo data honestly.
7. In all user-facing text and docs, use US English, no em dashes, and no parentheses. Use commas, periods, or colons.
8. Send the updated file after every single change when iterating on a document.

## Stack
Python, Streamlit, pandas, DuckDB from Week 4, and the Gemini API free tier through the google-genai package. Deploy on Streamlit Community Cloud from GitHub.

Verify before relying on them: the current Gemini free-tier limits, the current default model name, and the Streamlit Community Cloud limits. The model name in .env.example is a placeholder from memory.

## Design rules for the interface
Restrained and readable. Sentence case, plain verbs, no emojis, no all-caps labels, no gradients, no drop-shadow card grids, no pure white background, no purple and black scheme, no Inter, Geist, or Space Grotesk. Errors say what went wrong and how to fix it, and never apologize. The theme is already set in .streamlit/config.toml.

## Security rules, apply before any deploy
Keep API keys out of the repo and out of logs. Read the key from an environment variable or Streamlit secrets only. Validate every upload: CSV only, size cap, row cap. Never send raw customer data to the model. The mapper may send only column headers plus up to three masked sample values per column, with emails replaced by a placeholder. Offer a switch to turn AI matching off. Add a privacy note in the UI. Scan dependencies before deploy.

## Status
Weeks 1 to 5 are built, tested, pushed to GitHub and deployed. Week 6 is not started. The app is live at https://retention-spend-rebalancer-jq2rgyelyae7dspdcpv7te.streamlit.app

Built: src/parsing.py, src/loading.py, src/mapper.py, src/cleaning.py, src/sample_data.py, src/metrics.py, src/scenario.py, src/checker.py, src/insights.py, src/askdata.py, src/aiconfig.py, src/ui.py, app.py, the tests and the README. The live Gemini features were tried with real calls on the synthetic sample, and the AI summary passed the figure checker on five different synthetic datasets.

Done on 2026-10-04: exact dependency versions are pinned and a scan found no known vulnerabilities. Memory was measured on large files, and the row cap was lowered from 500,000 to 200,000 to fit the free hosting tier. The app is deployed on Streamlit Community Cloud with the Gemini key in Streamlit secrets, and the live app matched the local numbers exactly.

Still open: a live test of uploading a real file, and Week 6, which is running the tool on three real businesses, getting two reviewers to rate it, and writing the case study, the LinkedIn post and the interview story.

## Week 1 spec: data foundation
Goal: a messy order export loads cleanly and the user can see every cleaning decision.

### src/mapper.py
Canonical fields. Required: customer_id, order_date, order_value. Optional: order_id, order_status.

Rule-based mapper, always runs:
- Score every header against every field. Name score: exact match with a known synonym is 1.0, a synonym contained in the header is 0.75, a header contained in a synonym is 0.5. Zero the score when the header holds a negative token, for example name, phone, tax, shipping, discount, quantity for the wrong field.
- Content score from a sample of up to 500 non-blank values. Dates: share matching a date pattern. Values: share parseable as money, with a penalty when values look like long unique integers, which means ids. Customer id: fill rate, with a lower score when every value is unique. Order id: uniqueness. Status: low cardinality text.
- Total score is 0.6 times name plus 0.4 times content. Assign greedily from the highest score, one column per field. Required fields need at least 0.38. Customer id must never be assigned on content alone.
- Confidence: high at 0.8 and above, medium at 0.55 and above, otherwise low. Return a plain-language reason per field.

AI mapper, optional:
- Send only headers plus up to three masked sample values per column. Mask emails as a placeholder and truncate long values.
- Ask for JSON only, with one header or null per field.
- Parse strictly. Accept only headers that exist in the file, never reuse a header, and fall back to the rules on any failure.
- Merge with the rules. If both agree, confidence is high. If they disagree, show low confidence and tell the user to check. The user always confirms before anything runs.
- Take the model call as an injected function so tests can fake it. Read the model name from the GEMINI_MODEL environment variable.

### src/cleaning.py
Function clean_orders takes the raw frame, the confirmed mapping, an optional day-first setting, and a line-item mode of sum or first. It returns the clean frame, a list of steps, warnings, and stats. Each step records the rule, rows removed, and why. Rules in order:
1. Unreadable dates are dropped. If numeric dates are ambiguous, assume month first and warn.
2. Unreadable order values are dropped.
3. Refunded, voided, cancelled, failed, returned, and chargeback statuses are dropped. Partial refunds are kept.
4. Negative values are dropped.
5. Zero-value orders are dropped.
6. Missing or placeholder customer ids, such as guest, are dropped. Emails are lowercased.
7. If order_id is mapped, combine repeated rows into one order. Sum the line values, or take the first value when each line repeats the order total.
8. Exact duplicate rows without an order id are kept and reported as a warning, because identical orders can be real.
Warnings: fewer than 200 orders, fewer than 50 customers, a span under 90 days, no repeat customers, and more than 30% of rows removed.
Stats: orders, customers, first and last date, repeat customer share, total revenue.

### src/sample_data.py
A seeded generator for a synthetic export of about 1,500 customers over 24 months, with realistic repeat decay and a loyal group. Make it messy on purpose: mixed date formats and time zone suffixes, currency symbols and thousands commas, refund and void statuses, blank customer emails, a few unreadable dates, a few zero-value orders, and extra noise columns. Write it to data/synthetic_orders_messy.csv. Every place it appears must say it is synthetic.

### app.py
Streamlit flow in three stages. 1: upload a CSV or load the synthetic sample. 2: confirm columns, with suggestions, confidence, reasons, and a date-format and line-item options panel. 3: review the cleaning, with metrics, the steps table, warnings, a preview, and a download of the clean CSV. Store state per dataset so a new file resets the flow. Read files as text with blank cells kept as empty strings. Fail with a plain message on empty files, parse errors, and files over 200,000 rows. The cap was lowered from 500,000 on 2026-10-04 after measuring memory on a large file.

### tests
- Parsing: money formats, time zone stripping, day or month inference.
- Mapper: Shopify-style, WooCommerce-style, and UCI-style headers, plus a faked AI response, a malformed AI response, and a disagreement case.
- Cleaning: a small frame built so every rule's count can be checked by hand.
- App: a smoke test with Streamlit AppTest on the synthetic sample.
Run with python -m pytest.

### Definition of done for Week 1
A messy export loads, the columns are matched and confirmed, every cleaning decision is visible, tests pass, and the live Gemini mapping has been tried once with a real key.

## Known limitation, resolved
The UCI Online Retail data has unit price and quantity, not a line total. Resolved by adding an optional quantity field that multiplies a unit price, which you chose on 2026-10-03.

## Later weeks
Week 2: cohort retention, repeat purchase rate, RFM segments, lifetime value and payback, with a hand-checked test.
Week 3: scenario slider, editable assumptions, a simulated range, and an assumptions panel.
Week 4: AI summary, number checker, segment action plans, ask your data with DuckDB.
Week 5: repeat purchase prediction if on schedule, polish, deploy.
Week 6: three datasets, reviewer ratings, case study, LinkedIn post, interview story.
Success metric: run the tool on 3 businesses, produce a reallocation recommendation for each, and get 2 reviewers to rate it 4 or higher out of 5.
