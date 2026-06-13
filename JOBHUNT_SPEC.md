# Jobhunt v2 — Project Brief

Build spec for a personal job search tool. Single user (Pranav), runs locally.
Read this entire file before writing code. Build one module at a time, in the
order given in "Build Order." Stop at each checkpoint for review.

## Purpose

Four capabilities:
1. Fetch open roles from multiple job sources into one normalized database.
2. Score each job against the user's resume with a transparent breakdown.
3. Flag resume content that isn't earning its space for a given job, including
   ATS parse risks and missing terminology, with concrete suggestions.
4. For high-scoring jobs, suggest who to contact (by role title) and draft a
   short intro message.

Explicit non-goals (do not build these):
- No "acceptance probability." Scores measure resume-to-JD fit only.
- No LinkedIn scraping or automated contact discovery. The user finds the
  person manually; the tool drafts the message.
- No auto-apply. This tool informs decisions; the user acts.

## Stack

- Backend: Python 3.11+, FastAPI, SQLAlchemy 2.x, SQLite, httpx, APScheduler
- Frontend: React + Vite + TypeScript, Tailwind
- LLM: Anthropic API (claude-sonnet), key in `.env`, never committed
- Repo hygiene: git from the first commit, GitHub remote before Module 1 starts,
  `.env` and `*.db` in `.gitignore`

## Database Schema

```sql
companies (
  id INTEGER PK,
  name TEXT NOT NULL,
  source TEXT NOT NULL,            -- 'greenhouse' | 'lever' | 'ashby' | 'adzuna'
  board_token TEXT,                -- slug used by the source API
  url TEXT,
  created_at DATETIME
)

jobs (
  id INTEGER PK,
  company_id INTEGER FK -> companies,
  external_id TEXT NOT NULL,       -- source's job id, unique per (source, external_id)
  title TEXT NOT NULL,
  location TEXT,
  remote BOOLEAN,
  description TEXT,                -- full JD, HTML stripped to plain text
  url TEXT NOT NULL,
  posted_at DATETIME,
  fetched_at DATETIME,
  status TEXT DEFAULT 'new'        -- 'new' | 'shortlisted' | 'applied' | 'rejected' | 'archived'
)

resumes (
  id INTEGER PK,
  label TEXT,                      -- e.g. 'spatial-ux-v3'
  raw_text TEXT NOT NULL,          -- plain text extraction
  file_path TEXT,                  -- original PDF location
  is_active BOOLEAN DEFAULT 0,
  created_at DATETIME
)

scores (
  id INTEGER PK,
  job_id INTEGER FK -> jobs,
  resume_id INTEGER FK -> resumes,
  total REAL,                      -- 0-100
  skills_overlap REAL,             -- 0-100 component
  seniority_match REAL,            -- 0-100 component
  domain_match REAL,               -- 0-100 component
  rationale TEXT,                  -- 2-3 sentence LLM explanation
  scored_at DATETIME,
  UNIQUE(job_id, resume_id)
)

flags (
  id INTEGER PK,
  job_id INTEGER FK -> jobs,
  resume_id INTEGER FK -> resumes,
  flag_type TEXT,                  -- 'weak_content' | 'parse_risk' | 'missing_keyword' | 'irrelevant_content'
  severity TEXT,                   -- 'high' | 'medium' | 'low'
  target_text TEXT,                -- the resume text being flagged (verbatim excerpt)
  suggestion TEXT,                 -- concrete rewrite or action
  created_at DATETIME
)

intros (
  id INTEGER PK,
  job_id INTEGER FK -> jobs,
  target_role_title TEXT,          -- e.g. 'Head of Design', 'Design Recruiter'
  contact_name TEXT,               -- user fills in after manual search
  contact_url TEXT,                -- user fills in
  draft TEXT,                      -- LLM-drafted intro message
  status TEXT DEFAULT 'draft',     -- 'draft' | 'sent' | 'replied'
  created_at DATETIME
)
```

## Module 1 — Multi-Board Fetcher

Sources, in priority order:

1. **Greenhouse**: `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true`
   No auth. Returns all open jobs for a company.
2. **Lever**: `GET https://api.lever.co/v0/postings/{company}?mode=json`
   No auth.
3. **Ashby**: `GET https://api.ashbyhq.com/posting-api/job-board/{board_name}`
   No auth. Many YC startups use this.
4. **Adzuna** (aggregator, fills the gap for companies not tracked individually):
   `GET https://api.adzuna.com/v1/api/jobs/us/search/{page}` with `app_id`,
   `app_key`, `what`, `where` params. Free tier. Keys in `.env`.

Design requirements:
- One fetcher class per source implementing a common interface:
  `fetch(company) -> list[NormalizedJob]`.
- Companies table seeds from a `companies.yaml` the user maintains (name +
  source + board_token). Adzuna runs on keyword queries instead
  (`ux designer`, `product designer`, `interaction designer`, `haptics`,
  `spatial computing` — make the query list configurable).
- Dedupe on `(source, external_id)`. Re-fetch updates `fetched_at`; jobs that
  disappear from a source get status `archived`.
- Strip HTML from descriptions at ingest. Store plain text.
- Rate limit politely: max 1 request/second per source. Handle 429 with backoff.
- APScheduler job runs the full fetch daily; also expose `POST /api/fetch` for
  manual trigger.
- Log fetch results per source (jobs found / new / archived) so failures are
  visible, not silent.

Checkpoint 1: fetch from at least one real Greenhouse board and one Lever
board, rows visible in SQLite, dedupe proven by running fetch twice.

## Module 2 — Fit Scoring

Hybrid approach. Do not make this a single opaque LLM call.

Deterministic layer (runs first, free, fast):
- Extract a skill/keyword set from the JD (simple noun-phrase + curated
  vocabulary matching; maintain a `skills_vocab.yaml` seeded with UX/design/
  spatial/haptics terms).
- Compute raw overlap between JD keywords and resume keywords.

LLM layer (one call per job-resume pair):
- Input: resume text, JD text, raw overlap data.
- Output: strict JSON — `skills_overlap`, `seniority_match`, `domain_match`
  (each 0-100), `rationale` (2-3 sentences). System prompt must demand JSON
  only, no markdown fences.
- `total = 0.45 * skills_overlap + 0.25 * seniority_match + 0.30 * domain_match`
  Weights live in config, not hardcoded.

Rules:
- Score only jobs with status `new` or `shortlisted` against the active resume.
- Cache: never re-score an unchanged (job, resume) pair. Re-score when the
  active resume changes.
- Batch endpoint: `POST /api/score/run` scores all unscored jobs; show
  progress. Estimate and log API cost per run.

Checkpoint 2: 20+ real jobs scored, sorted list in the UI with the three
component scores visible per job, and at least one score the user can
sanity-check and agree with.

## Module 3 — Resume Flagging

One LLM call per (job, resume) pair, triggered on demand from the job detail
view, not automatically for every job (cost control). Only meaningful for jobs
the user shortlists.

System prompt requirements (write this prompt carefully, it is the core of the
feature):

- Role: a blunt resume reviewer for a specific job application. Not a
  cheerleader.
- Produce a JSON array of flags. Each flag:
  `{ "flag_type": ..., "severity": ..., "target_text": "<verbatim excerpt from resume>", "suggestion": "<concrete rewrite or action>" }`
- Flag types and what qualifies:
  - `weak_content`: bullets that state duties instead of outcomes, vague
    claims with no evidence, filler ("team player", "passionate about").
  - `irrelevant_content`: content consuming space that does nothing for THIS
    job. Be aggressive here; a one-page resume has no room for neutral lines.
  - `missing_keyword`: terminology the JD uses that the resume doesn't, where
    the user plausibly has the experience and could legitimately add it. Never
    suggest fabricating experience.
  - `parse_risk`: structural risks for ATS parsing. Note: the LLM sees plain
    text, so parse_risk detection is limited — detect symptoms like fragmented
    lines, garbled section ordering, tables flattened into noise. Also run a
    deterministic pre-check in Python: warn if the PDF text extraction yields
    out-of-order sections, very short total text (image-heavy resume), or
    missing standard section headers (Experience, Education, Skills).
- Suggestions must be specific rewrites, not advice-shaped advice. Bad:
  "quantify your impact." Good: a rewritten bullet using only facts present
  elsewhere in the resume.
- Cap at 12 flags, ordered by severity. A wall of 40 flags is noise.

Checkpoint 3: run flagging on the real resume against 3 shortlisted jobs;
user judges whether flags are accurate and suggestions are usable as-is.

## Module 4 — Contact Targeting + Intro Draft

No scraping. Two steps:

1. **Target role suggestion** (deterministic + LLM-light): given company size
   signal (job count on their board is a rough proxy) and the JD, suggest 2-3
   role titles to search for on LinkedIn. Heuristics: <20 open roles →
   founder/CEO or Head of Design; larger → hiring manager title inferred from
   the JD ("reports to X" lines) plus a recruiter title. Store in
   `intros.target_role_title`.
2. **Intro draft** (LLM call): inputs are resume, JD, and optionally the
   contact's name/title once the user pastes it in. Output one message,
   90-130 words.

Intro prompt constraints (non-negotiable, encode in the system prompt):
- Plain, direct sentences. No em dashes. No corporate buzzwords ("synergy",
  "passionate", "leverage"). No AI-sounding phrasing ("I hope this message
  finds you well", "I came across your profile"). No flattery openers.
- Structure: one line of specific connection to the company's actual work,
  one line of the sender's most relevant proof point, one concrete ask
  (15-minute call or feedback on application).
- The draft is a starting point; the UI shows it in an editable textarea.

Checkpoint 4: full flow on one real job — score, flag, target suggestion,
intro draft, user edits and sends manually.

## API Surface (FastAPI)

```
POST /api/fetch                      manual fetch trigger
GET  /api/jobs?status=&sort=score    job list with scores joined
GET  /api/jobs/{id}                  job detail + score + flags + intro
PATCH /api/jobs/{id}                 update status
POST /api/resumes                    upload PDF, extract text (pdfplumber)
PATCH /api/resumes/{id}/activate     set active resume
POST /api/score/run                  score all unscored jobs
POST /api/jobs/{id}/flags            run flagging for this job
POST /api/jobs/{id}/intro            generate target roles + draft
PATCH /api/intros/{id}               save contact info / edited draft / status
```

## Frontend Views

1. **Job board**: table sorted by total score desc. Columns: title, company,
   location, total score with the three components on hover/expand, status,
   posted date. Status filters. Row click → detail.
2. **Job detail**: JD on the left; right panel tabs for Score (breakdown +
   rationale), Flags (severity-sorted, each flag shows target_text and
   suggestion with a copy button), Outreach (target roles, contact fields,
   editable draft).
3. **Resume manager**: upload, view extracted text (so parse problems are
   visible immediately), set active.

Keep the UI plain and fast. No dashboard decoration, no charts in v1.

## Build Order

1. Repo setup: git init, GitHub remote, .gitignore, scaffold backend +
   frontend, schema migration, companies.yaml with 10 seed companies
   (include ANORIA, Vassar Robotics, Mentra if their boards are findable;
   fill the rest with Greenhouse/Lever/Ashby companies hiring designers).
2. Module 1 → Checkpoint 1
3. Module 2 → Checkpoint 2
4. Frontend job board view (read-only is fine at this stage)
5. Module 3 → Checkpoint 3
6. Module 4 + job detail view → Checkpoint 4
7. Resume manager view, polish, README

At each checkpoint, stop and wait for review before continuing.
