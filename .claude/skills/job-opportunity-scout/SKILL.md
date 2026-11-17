---
name: job-opportunity-scout
description: Scouts live job postings for Cédric (enterprise sales, Antwerp/Belgium). It collects jobs from company career feeds (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Personio, Teamtailor, Workday), job APIs (Adzuna, Jooble, Arbeitnow, Remotive) and selected career sites, then pre-filters, scores fit out of 10, verifies links, prints ranked Fortune 500 and start-up/scale-up tables, and updates the jobs.csv / jobs.xlsx / Google Sheet tracker. Use when the user says "scout jobs", "find job opportunities", "job search run", "any new sales roles?", "look for Account Executive / Account Manager / Partner Manager jobs", or asks to update the job tracker.
---

# Job Opportunity Scout

You collect real, open postings with code, then do the judgement part yourself: scoring, the pay estimate and the main risk.
You never apply, never contact recruiters and never send anything on the user's behalf. You never invent a job, a link or a salary.

`SKILL` below means the directory that holds this file: `~/.claude/skills/job-opportunity-scout`, or
`.claude/skills/job-opportunity-scout` inside the `job-opportunity-scout` repo.

## 0. Setup (each fresh machine)
```bash
cd "$SKILL" && python3 -c "import yaml, requests, openpyxl, playwright" 2>/dev/null || pip install -q -r requirements.txt
```
Playwright uses the system Chromium if one exists (`PW_CHROMIUM_PATH`, default `/opt/pw-browsers/chromium`). Otherwise run `python3 -m playwright install chromium` once.
API keys come from environment variables (`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `JOOBLE_API_KEY`). If one is missing, that source is reported as `skipped-no-key`. That is not an error.

## 1. Collect (code)
```bash
cd "$SKILL" && python3 scripts/collect.py
```
This fetches every source, normalises the jobs, dedupes them (by URL and by company + title, also against the SQLite history in `data/jobs.db`) and pre-filters them by title, location, years required and excluded companies. It writes `data/runs/<today>/candidates.json`.
Read the printed report. **Every source listed under "Sources with problems" must be mentioned to the user** in the final output; the finalize step prints them too.

## 2. Score (you)
Read `config/profile.md` (the profile and rubric) and `data/runs/<today>/candidates.json`. Score **every** candidate. For more than ~40 candidates, work in batches, appending to the same list.
Write `data/runs/<today>/scores.json`: a JSON list with one object per candidate:

```json
{"id": "<id from candidates.json>", "keep": true, "drop_reason": "",
 "bucket": "A", "role_type": "Enterprise AE",
 "scores": {"builds": 2, "aspirations": 2, "pay": 2, "location": 2},
 "ote_low": 110000, "ote_high": 140000, "pay_confidence": "good estimate",
 "why": "Named enterprise accounts in BeLux selling cloud infrastructure, a direct extension of the HPE hybrid-cloud quota record.",
 "risk": "Posting hints at 6+ years; may be pitched one level above current seniority."}
```

Rules for scoring:
- `role_type` is one of: `Enterprise AE`, `Strategic/Named/Global Account Manager`, `Partner/Channel/Alliance Manager`, or a close variant you name.
- `bucket`: `A` only if the company is on the Fortune 500 or Fortune Global 500 (`config/fortune500.txt` helps, but use your knowledge). `B` only for **tech/IT** start-ups or scale-ups that are viable: Series A or later, or clearly profitable, with a real enterprise or mid-market sales motion and a credible path to 85K OTE. Public tech companies that are not on the Fortune lists also go in `B`. Anything else gets `keep: false`.
- Set `keep: false` (with `drop_reason`) for any of these: SDR/BDR, inside sales, pure renewals, pure customer success, people manager, 8+ years required, HPE or an HPE brand, not really in Belgium or open to Belgium-based candidates, 85K OTE implausible, a duplicate of another candidate, or a description too thin to judge that you cannot confirm.
- Pay: use stated pay when present (`pay_confidence: "stated"`). Otherwise estimate from the reference points in `profile.md` and label it `good estimate` or `rough guess`. Never present an estimate as stated.
- Location score: Belgium-based within commuting distance of Antwerp = 2. Heavy French, Wallonia commute, or Belgium eligibility unconfirmed = 1. Remote roles that do not name Belgium score at most 1 (`location_class: remote-unconfirmed` in the candidate data), and lower still when the region is vague.
- Be critical. The fit total is the sum of the four parts. A 9 or 10 should be rare. Every kept role needs a concrete main risk.
- When `description_missing` is true, judge from the title, company and location only, and say so in the risk.

## 3. Finalize (code)
```bash
cd "$SKILL" && python3 scripts/finalize.py data/runs/<today>/scores.json
```
This validates your scores, enforces the 85K floor, verifies that each kept link is still live (it uses the ATS API where possible), caps Bucket B at 5, marks the jobs in the database so they are never suggested again, and appends the new rows to `data/jobs.csv` and `data/jobs.xlsx`. The user's Status and Notes edits are preserved. It prints the report and saves it as `report.md`.
If it prints "scores.json problems", fix the listed entries and run it again.

## 4. Present
Show the user the printed report as is: the first line (date, collected, after filtering, shown), the warning about failed sources, the **Fortune 500** table, the **Start-ups/Scale-ups (max 5)** table, and the closing single best match. You may rewrite the best-match line into one sharper sentence. Do not add roles that are not in the tables.

## 5. Google Sheet sync
The tracker is mirrored to a Google Sheet named **"Job Opportunities - Cédric"** in the user's Drive. Its ID and tab are stored in `data/sheet.json` (`{"spreadsheetId": "...", "tab": "Jobs"}`). Before the first Google call, load the `google-workspace` skill if it is available.
- If the Google Sheets/Drive tools are available and `data/sheet.json` exists:
  1. Read the sheet (`get_values` on `<tab>!A1:N`) and save them to `data/runs/<today>/sheet_values.json`.
  2. Run `python3 scripts/tracker.py merge-sheet data/runs/<today>/sheet_values.json`. This pulls the user's Status/Notes edits from the sheet into the local files.
  3. Run `python3 scripts/tracker.py sheet-rows data/runs/<today>/sheet_values.json` and append the returned `rows` to the sheet with `append_values` on `<tab>!A1`. Send Fit score as a number and everything else as text. If `sheet_has_header` is false, write `header` first.
- If `data/sheet.json` does not exist, **offer** to create the sheet. On yes, create it in the user's Drive, write the header and all rows from `sheet-rows`, and save its ID to `data/sheet.json`.
- Never delete or reorder rows in the sheet, and never overwrite Status or Notes there.

## 6. Persist (cloud sessions / git checkout)
If `$SKILL` is inside a git repository, commit `data/` (DB, tracker, run folder) with message `scout run <today>` and push to the current branch. Otherwise the job history is lost when a cloud container is reclaimed.

## 7. Notify by email (scheduled runs, or when the user asks)
If a Gmail tool is available, send ONE email from the user's own Gmail to the user's own address (never to anyone else):
- Subject: `Job scout: <N> new jobs found (<date>)` where N is the number of roles shown this run (`0 new jobs` when none).
- Body: the link to the Google Sheet (`https://docs.google.com/spreadsheets/d/<spreadsheetId from data/sheet.json>/edit`), then one line per shown role (title, company, fit score, link), then one line listing sources that failed.
- Send it even when N is 0, so a silent failure is never mistaken for "nothing new". If collection itself failed, say so in the subject.

## Maintenance
- Add a company: `python3 scripts/discover.py "Company" --bucket B --industry "SaaS" --add`, or `--url <job board link>`.
- Health check of all feeds: `python3 scripts/discover.py --check`.
- Title and location rules: `config/filters.yaml`. Aggregator queries: `config/sources.yaml`.
- Offline tests: `python3 -m pytest -q tests` (or `python3 tests/test_offline.py`).

## Hard rules
- Only real, currently open postings with verified links. Never invent jobs, links or salaries.
- Never apply, contact anyone or submit forms. Do not scrape LinkedIn, Indeed, Glassdoor, or any site that needs a login or forbids it in robots.txt.
- Keep the user's pay and personal details out of every outbound request. `profile.md` is for your scoring only.
