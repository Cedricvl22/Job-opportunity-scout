# job-opportunity-scout

A Claude Code skill that collects live job postings, filters them in code, has Claude score them against a personal profile, verifies every link, and keeps a tracker (CSV, XLSX and a Google Sheet).

The skill itself lives in [`.claude/skills/job-opportunity-scout/`](.claude/skills/job-opportunity-scout/). Its instructions for Claude are in `SKILL.md`. Claude Code loads it automatically in any session opened in this repo. To use it everywhere, symlink it into your user skills:

```bash
ln -sfn "$PWD/.claude/skills/job-opportunity-scout" ~/.claude/skills/job-opportunity-scout
```

Then say **"scout jobs"** or **"find job opportunities"** in Claude Code.

## How a run works

| Step | Who | What |
|---|---|---|
| 1. Collect | `scripts/collect.py` | Fetches ~85 company feeds plus job boards and APIs, normalises them into one schema, dedupes by URL and company + title (also against `data/jobs.db`), pre-filters by title, location, years required and excluded companies. Logs every source's result. |
| 2. Score | Claude | Reads `config/profile.md` and `candidates.json`, scores fit out of 10 (builds on current role 0-3, aspirations 0-3, pay 0-2, location 0-2), estimates OTE with a confidence label, names the main risk, and writes `scores.json`. |
| 3. Finalize | `scripts/finalize.py` | Validates the scores, enforces the 85K OTE floor, checks each link is still live, caps start-ups/scale-ups at 5, marks jobs as seen, appends to the tracker, and prints the tables. |
| 4. Sync | Claude | Mirrors the tracker to the Google Sheet "Job Opportunities - Cédric", pulling your Status/Notes edits back first. |

## Sources

| Source | Type | Status (checked 2026-11-16) |
|---|---|---|
| Greenhouse, Lever (+EU), Ashby, Recruitee, Workable, Personio, Teamtailor | public ATS JSON/XML/RSS | ✅ working |
| Workday (`/wday/cxs/` endpoints) | public ATS JSON | ⚠️ module works, but every tenant answers Python clients with a Cloudflare bot challenge. Reported as `blocked-bot-protection`; **not bypassed**. |
| SmartRecruiters | public API | ⚠️ `api.smartrecruiters.com/robots.txt` disallows all bots except LinkedIn's, so it's reported as `blocked-robots` and not used |
| StepStone.be | HTML listing pages (path slugs only; query search is disallowed by robots.txt) | ✅ working, JSON-LD descriptions |
| Arbeitnow | free API | ✅ working (mostly DACH/remote) |
| Adzuna (Belgium) | API with key | 🔑 needs keys (see below) |
| Jooble | API with key | 🔑 needs key (see below) |
| Playwright browser fallback | headless browser | ✅ works; SAP careers (its only user so far) sits behind a Cloudflare challenge, reported and not bypassed |
| Remotive | free API | ❌ disabled: robots.txt disallows `/api/` |
| ICTjob.be | HTML | ❌ disabled: keyword search only runs via `/ajax/`, which robots.txt disallows |
| VDAB | (none) | ❌ robots.txt disallows `/api/vindeenjob/`, `/vacatures/` and `/zoeken/` |
| Jobat | (none) | ❌ Cloudflare bot challenge |
| LinkedIn, Indeed, Glassdoor | (none) | ❌ never scraped (login walls / terms) |

## API keys (optional, they add coverage)

Keys are read from environment variables only. They never go in a file in this repo.

**Adzuna**: `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`
1. Go to https://developer.adzuna.com and click **Register**. It's free; the trial tier allows 250 calls/day, and one run uses about 18.
2. Confirm your email and log in. Open **Dashboard → API Access Details**.
3. Copy the **Application ID** into `ADZUNA_APP_ID` and the **Application Key** into `ADZUNA_APP_KEY`.

**Jooble**: `JOOBLE_API_KEY`
1. Go to https://jooble.org/api/about and fill in the form (name, email, website: you can enter "personal use").
2. The key arrives by email, usually within minutes.
3. Put it in `JOOBLE_API_KEY`.

Where to set them:
- **Claude Code on the web (cloud sessions):** open the environment menu in the session title bar → **Default** → **Edit** → **Environment variables**, and add the three lines `ADZUNA_APP_ID=...`, `ADZUNA_APP_KEY=...`, `JOOBLE_API_KEY=...`. Values stored there are visible to anyone who can edit that environment, so keep it personal. They take effect in the next session.
- **Local machine:** add `export ADZUNA_APP_ID=...` (and so on) to `~/.zshrc` or `~/.bashrc`, or to a `.env` file you `source` before running.

Without keys, those two sources show up in every report as `skipped-no-key`.

## Network allowlist (cloud environment)

The cloud environment must allow these hosts (Settings → environment → Network access → Allowed domains):

```
boards-api.greenhouse.io
api.lever.co
api.eu.lever.co
api.ashbyhq.com
apply.workable.com
*.recruitee.com
*.jobs.personio.de
*.jobs.personio.com
*.teamtailor.com
*.myworkdayjobs.com
api.smartrecruiters.com
api.adzuna.com
www.adzuna.be           # only needed to verify Adzuna links (else they show as unverified)
jooble.org
www.arbeitnow.com
www.stepstone.be
jobs.sap.com
```

Company career domains that Greenhouse links point to (for example `stripe.com`, `www.netskope.com`, `jobs.elastic.co`) don't need to be allowed: Greenhouse, Lever, Ashby, Workday and SmartRecruiters links are verified through their APIs instead.

## Running manually

```bash
cd .claude/skills/job-opportunity-scout
./setup.sh                                   # once per machine: deps + offline tests
python3 scripts/collect.py                   # step 1
#   ... Claude writes data/runs/<date>/scores.json (step 2) ...
python3 scripts/finalize.py data/runs/<date>/scores.json   # step 3
```

The normal way is simply to tell Claude Code **"scout jobs"**. It follows `SKILL.md` and runs all steps.

Useful extras:

```bash
python3 scripts/collect.py --only stripe,netskope     # a few sources
python3 scripts/discover.py "Company name" --bucket B --industry SaaS --add
python3 scripts/discover.py --url https://jobs.lever.co/company --name "Company" --bucket B --add
python3 scripts/discover.py --check                   # health check of every feed
python3 scripts/tracker.py show                       # print the tracker
```

## Scheduling a weekly run

**Option A: Claude Code scheduled task (cloud, no computer needed).** This is set up: the task "Job scout" runs every Tuesday and Saturday at 07:43 Europe/Brussels. Each run starts a fresh cloud session on this repo, scouts, syncs the Google Sheet, commits `data/` to `main`, sends a push notification, and emails you (from your own Gmail, to yourself) with the number of new jobs in the subject and a link to the sheet. Ask Claude to "list my scheduled tasks" to change or pause it.

**Option B: cron on your own computer** (needs the Claude Code CLI, logged in):

```bash
crontab -e
```

then add:

```
40 7 * * 1 cd ~/job-opportunity-scout && claude -p "scout jobs" --allowedTools "Bash,Read,Write,Edit" >> ~/job-scout.log 2>&1
```

On macOS, `launchd` or the Shortcuts app works too; cron is the simplest.

## Tracker

`data/jobs.csv` and `data/jobs.xlsx` have the columns *Date found, Date posted, Job Title, Company, Bucket, Role type, Location, Link, Fit score, Est. OTE range, Pay confidence, Why it fits, Main risk, Status, Notes*. Rows are only ever appended. You can edit **Status** and **Notes** in the CSV, the XLSX or the Google Sheet: every run reads your edits back first and never overwrites them. If two places hold different edits, the sheet wins, then the XLSX, then the CSV.

## Privacy and safety

- Requests carry a neutral User-Agent and no personal data. `config/profile.md` (including pay) is read only by Claude locally and is never sent to any website.
- robots.txt is checked before every request (RFC 9309 semantics), with at most one request per second per host. Bot-protection challenges are reported, never bypassed.
- The skill never applies, never contacts recruiters and never submits forms.
- This repo contains your profile and pay. **Keep it private.**
