---
name: job-hunter
description: This skill should be used when the user asks to "find jobs", "search for jobs matching my expectations", "find the best job matching my expectation", "job hunt", "search job platforms", "match jobs to my profile", "find AI engineer jobs", "find ML engineer jobs", "search for senior software engineer roles", "find jobs with visa sponsorship", or mentions job hunting, job matching, career search, or job platform scraping.
version: 1.0.0
---

# Job Hunter

Search job platforms (UK and France), match listings to the candidate's profile, check visa sponsorship (UKVI for UK, Talent Passport for France), calculate financial viability including commute costs, and export ranked results to an Excel workbook (.xlsx).

Powered by **DEB Cloud** — scraping, reference data, and job caching are provided by the DEB Cloud MCP server (`mcp__deb-jobhunter__*` tools).

The `country` field in the expectations JSON drives platform selection, tax/social calculation, visa checking, and currency formatting. Supported countries: `gb` (default), `fr`.

## Context Management — Save Tool Responses to File

**CRITICAL**: MCP tool responses (especially `scrape_jobs` and `scrape_url`) return large payloads that saturate the context window. You MUST save them to disk immediately and reference the file path instead of keeping the content in context.

**Temp directory**: Create a `mcp_jobhunter` subdirectory under the system temp folder. Detect the OS temp path at runtime:
- Linux/macOS: `/tmp/mcp_jobhunter/`
- Windows: `%TEMP%\mcp_jobhunter\` (e.g., `C:\Users\{user}\AppData\Local\Temp\mcp_jobhunter\`)

Use `Bash` to create the directory if it doesn't exist: `mkdir -p /tmp/mcp_jobhunter` (Unix) or equivalent.

**Pattern for every MCP tool call that returns content:**

1. Call the MCP tool (e.g., `scrape_jobs`, `scrape_url`, `get_reputation`, `get_ukvi_sponsors`)
2. **Immediately** use the `Write` tool to save the full response to a JSON file in the temp directory
3. Only retain a **brief summary** in your working memory: status, count, file path
4. When you need the data later, use the `Read` tool to load it from the file

**File naming convention** (inside `mcp_jobhunter/`):
```
scrape_{platform}_{city}_{role_slug}_{YYYYMMDD_HHMMSS}.json
detail_batch{N}_{YYYYMMDD_HHMMSS}.json
reputation_batch{N}_{YYYYMMDD_HHMMSS}.json
ukvi_sponsors_{YYYYMMDD_HHMMSS}.json
```

**Example flow:**
```
# 1. Call tool
result = scrape_jobs(query="AI Engineer", platforms=["reed"], location="London")

# 2. Save full response to temp file immediately
Write("<temp_dir>/mcp_jobhunter/scrape_reed_london_ai_engineer_20260305_143022.json", json(result))

# 3. Only keep summary in context:
#    "reed-london: 12 jobs scraped, saved to <temp_dir>/mcp_jobhunter/scrape_reed_london_ai_engineer_20260305_143022.json"

# 4. Later, when parsing:
#    Read("<temp_dir>/mcp_jobhunter/scrape_reed_london_ai_engineer_20260305_143022.json")
```

This mirrors the Decodo MCP `save_to_file` pattern but done client-side since the job hunter MCP runs on Cloud Run.

## Data Persistence

**CRITICAL**: All intermediate data MUST be saved to disk at each step. This ensures that if the conversation runs out of context, the next invocation can resume from the last checkpoint without re-scraping.

### Working Directory

Create a session working directory in the same folder as the expectations JSON:

```
{expectations_dir}/job-search-{YYYYMMDD_HHMMSS}/
├── state.json                          # Current progress tracker
├── scrape-{platform}-{city}-{role}.json  # Per-query scrape results
├── checkpoint-raw-combined.json        # All raw results combined (after Step 3)
├── checkpoint-dedup.json               # After deduplication (after Step 4)
├── checkpoint-scored.json              # After LLM agent scoring (after Step 5)
├── ukvi-sponsor-data.json              # UKVI data from DEB Cloud (Step 6)
├── agency-data.json                    # Agency data from DEB Cloud (Step 6)
├── checkpoint-final.json               # After financial calc + visa + agency (after Step 6)
└── jobs-{YYYYMMDD_HHMMSS}.xlsx        # Final Excel output (after Step 6)
```

### State File (`state.json`)

Track progress so interrupted sessions can resume:

```json
{
  "session_id": "20260211_143022",
  "expectations_path": "path/to/expectations.json",
  "working_dir": "path/to/job-search-20260211_143022/",
  "deb_cloud_key_valid": true,
  "current_step": 3,
  "step_3_progress": {
    "completed_queries": ["reed-london-ai_engineer", "reed-london-ml_engineer"],
    "total_queries": 32,
    "total_jobs_scraped": 42
  },
  "step_3_complete": false,
  "step_4_complete": false,
  "step_5_complete": false,
  "step_5_5_complete": false,
  "step_6_complete": false,
  "started_at": "2026-02-11T14:30:22",
  "updated_at": "2026-02-11T14:45:12"
}
```

### Resume Logic

At the start of the workflow, check if a working directory exists with matching expectations file:

1. Look for `job-search-*` directories in the expectations folder
2. If found with a `state.json`, read it to determine where to resume
3. If Step 3 was in progress: load existing scrape JSONs, only scrape missing queries
4. If Step 3 was complete: load `checkpoint-raw-combined.json`, skip to Step 4
5. If Step 4+ complete: load the latest checkpoint, skip ahead
6. If no working directory found: start fresh from Step 1

---

## Workflow

Execute these steps in order. Save intermediate data at each step. Log progress to the user after each major step.

### Step 0: Validate DEB Cloud API Key

1. Read the `DEB_CLOUD_API_KEY` environment variable.
2. If set, call `mcp__deb-jobhunter__ping` to validate:
   - On success: store `deb_cloud_key_valid: true` in state. Note the plan and available platforms.
   - On failure: warn user, store `deb_cloud_key_valid: false`.
3. If not set: warn the user: "DEB Cloud API key not configured. Register at debytes.io/products/cloud to get a key. Running in degraded mode — scraping and data lookups are unavailable."
4. In degraded mode: the user can provide their own raw job data files. Dedup, scoring, financial calc, and Excel export still work locally.

### Step 1: Load and Validate Inputs

1. Read the expectations JSON file from the path provided by the user.
2. Validate required fields: `candidate`, `target_roles`, `locations`, `current_situation`.
3. Determine country: read `country` from expectations JSON (default: `"gb"` if absent).
4. Determine sector: read `sector` from expectations JSON (default: `"industry"` if absent). Valid values: `"industry"`, `"academia"`.
5. Read the shared INI config from `${PLUGIN_ROOT}/config/job-hunter.ini`.
6. Read the country-specific INI from `${PLUGIN_ROOT}/config/country-{country}.ini` (overlays shared config).
7. If `sector=academia`: load `[platforms_academia]` and `[platform_urls_academia]` sections instead of `[platforms]`. Also load `[academic_salary_grades]` for salary parsing.
8. **Resolve candidate document** for scoring context:
   a. If `candidate.resume_path` is provided:
      - Detect format from extension: `.tex`, `.pdf`, `.md`, `.txt`, `.docx`, `.doc`
      - For `.tex`, `.pdf`, `.md`, `.txt`: read directly with the Read tool (plain text or native PDF support).
      - For `.docx` or `.doc`: run the extraction utility first:
        ```bash
        python "${PLUGIN_ROOT}/scripts/process_jobs.py" \
          --stage extract-resume \
          --resume "{resume_path}" \
          --output-dir "{working_dir}"
        ```
        Then read the resulting `-extracted.txt` file with the Read tool.
   b. If `candidate.profile_path` is also provided AND the file exists: read it as supplementary context (backward compatible).
   c. If neither path is provided or files don't exist: WARN the user and proceed with skills-only matching (from `candidate.skills` or INI `[candidate_skills]`).
   d. Store the resolved readable path in `state.json` as `"candidate_document_path"`.
9. Load candidate skills from `candidate.skills` in the expectations JSON (fallback to INI `[candidate_skills]` for backward compat).
10. Create the working directory and initialize `state.json`.
11. Report to user: "Country: {country}. Sector: {sector}. Found N target roles, M locations. DEB Cloud: {connected/degraded}. Working directory: {path}. Proceeding."

### Step 2: Build Search Matrix

1. For each target role, get the `search_keywords` array (use first keyword as primary).
2. Combine all roles with all cities from both P1 and P2 groups.
3. Group queries by platform, ordered by reliability:
   - **GB (industry)**: LinkedIn, Indeed, Reed, Totaljobs, CW Jobs, CV-Library, Adzuna.
   - **GB (academia)**: jobs.ac.uk, EURAXESS, Indeed, LinkedIn.
   - **FR**: LinkedIn, Indeed.fr, Welcome to the Jungle, APEC, HelloWork, LesJeudis.
4. Only include platforms where `[platforms]` (or `[platforms_academia]` when `sector=academia`) section in the country INI has value `1`.
5. Total queries = roles * locations * enabled platforms (capped by max_pages setting).

### Step 3: Scrape Job Listings

**Requires DEB Cloud key.** If degraded mode, skip this step and instruct the user to provide raw job data.

For each search query, call `mcp__deb-jobhunter__scrape_jobs` with:
- `query`: the search keyword
- `platforms`: single platform code (1 per call)
- `country`: country code (`GB` or `FR`)
- `location`: city name
- `min_salary`: minimum salary from target role expectations (optional)

The DEB Cloud server handles platform URL construction, proxy routing, anti-bot handling, and JavaScript rendering internally. Results are returned as markdown content per platform.

**Platform codes** (match INI platform names):
- **GB industry**: `linkedin`, `indeed`, `reed`, `totaljobs`, `cwjobs`, `cvlibrary`, `adzuna`
- **GB academia**: use `mcp__deb-jobhunter__scrape_url` for jobs.ac.uk and EURAXESS with specific URLs from `[platform_urls_academia]` INI section
- **FR**: `linkedin`, `indeed_fr`, `welcometothejungle`, `apec`, `hellowork`, `lesjeudis`

**IMPORTANT — Save raw response to temp file immediately:**
After each `scrape_jobs` call, **immediately Write the full MCP response** to the temp directory (see Context Management above). Do NOT keep the raw response in context. Then Read the file back to extract jobs into the normalized structure.

Save extracted jobs to a per-query file in the **working directory**:
```
scrape-{platform}-{city}-{role_slug}.json
```
Each file contains an array of extracted job objects. Update `state.json` with the completed query.

For each result, extract into the normalized structure:
```json
{
  "title": "Senior AI Engineer",
  "company": "Acme Corp",
  "location": "London",
  "salary_text": "90,000 - 110,000",
  "salary_min": 90000,
  "salary_max": 110000,
  "salary_unlisted": false,
  "work_mode": "hybrid",
  "url": "https://...",
  "description": "snippet...",
  "platform": "reed",
  "posted_date": "2026-02-08",
  "target_role": "AI Engineer",
  "region_group": "P1"
}
```

Parse salary text using the rules in `references/scraping-strategy.md` (handle ranges, k-notation, daily rates, "Competitive"/"Selon profil"). Use the country-specific parsing rules (GBP for UK, EUR for France).

After ALL queries complete, combine all per-query JSONs into `checkpoint-raw-combined.json`. Update `state.json` with `step_3_complete: true`.

Report progress: "Scraping complete. {N} total listings from {platforms}."

### Step 3.5: Enrich — Conditional Detail Scraping

For listings that are **missing key data** (salary unlisted, no description, no work mode), scrape the individual job detail page to fill gaps:

1. Identify listings where `salary_unlisted=true` OR `description` is empty.
2. Group their URLs into batches of 5.
3. Use `mcp__deb-jobhunter__scrape_url` to fetch each batch (`urls=[...]`, `use_javascript=true`). Max 5 URLs per call.
4. **Save each batch response** to temp file immediately (see Context Management): `detail_batch{N}_{timestamp}.json`. Read back when parsing.
4. Parse the detail page to extract: full description, salary if shown, work mode, tech requirements.
5. Update the listing with any newly found data (salary, description, work_mode).
6. Re-save the per-query scrape files with enriched data.

**Skip** this step if the user requests speed over completeness, or if there are too many listings to enrich (>500).

### Step 4: Deduplicate and Checkpoint

**Run the dedup stage** of the processing script:

```bash
python "${PLUGIN_ROOT}/scripts/process_jobs.py" \
  --stage dedup \
  --raw "{working_dir}/checkpoint-raw-combined.json" \
  --expectations "{expectations_path}" \
  --config "${PLUGIN_ROOT}/config/job-hunter.ini" \
  --output-dir "{working_dir}"
```

This deduplicates by (title, company, location), merges platform names, prefers richer data, and saves `checkpoint-dedup.json`.

### Step 5: Job Scoring

Read `scoring_mode` from `[scoring]` in the INI config.

**If `scoring_mode = remote`** (requires DEB Cloud key):

1. Read the candidate document (resume/profile from Step 1).
2. Build profile text: concatenate resume content + candidate skills from `[candidate_skills]` in INI (max 8000 chars — summarize if needed).
3. Build expectations context from the expectations JSON:
   `{target_roles, p1_cities, p2_cities, requires_visa, country, sector}`
4. If job count <= 15 (inline mode):
   - Call `mcp__deb-jobhunter__score_jobs` with `jobs=[...]`, `expectations={...}`, `profile="..."`.
   - Save result to `checkpoint-scored.json`.
5. If job count > 15 (batch mode via GCS):
   a. Get file size: `wc -c < checkpoint-deduplicated.json`
   b. Call `mcp__deb-jobhunter__init_scoring(job_count=N, file_size=BYTES, expectations={...}, profile="...")`
   c. Upload the file to the returned URL:
      ```bash
      curl -s --ssl-no-revoke -X PUT -H "Content-Type: application/json" \
        -H "Content-Length: BYTES" \
        --data-binary @"{working_dir}/checkpoint-deduplicated.json" "{upload_url}"
      ```
   d. Call `mcp__deb-jobhunter__score_jobs(batch_id="...")`
   e. Download results:
      ```bash
      curl -s --ssl-no-revoke -o "{working_dir}/checkpoint-scored-raw.json" "{download_url}"
      ```
   f. Read downloaded results and save as `checkpoint-scored.json`.
6. Filter out jobs with `match_score < 30`.

**If `scoring_mode = local`** (default):

1. Run `process_jobs.py` with `--stage score`:
   ```bash
   python "${PLUGIN_ROOT}/scripts/process_jobs.py" \
     --stage score \
     --deduped "{working_dir}/checkpoint-dedup.json" \
     --expectations "{expectations_path}" \
     --config "${PLUGIN_ROOT}/config/job-hunter.ini" \
     --output-dir "{working_dir}"
   ```
2. This uses local heuristic scoring internally.
3. Output: `checkpoint-scored.json`

Report: "Scored {N} jobs. {kept} with match_score >= 30, {removed} discarded."

### Step 5.5: Company Reputation Lookup

Enrich scored jobs with employee review ratings. Reputation data is **informational only** — it appears as separate Excel columns and is NOT blended into composite_score.

**Requires DEB Cloud key.** If degraded mode, skip this step.

1. **Extract unique companies** from `checkpoint-scored.json`. Build a list of company names.

2. **Call `mcp__deb-jobhunter__get_reputation`** with the company names list, `mode="light"`, and country. Max 15 companies per call — split into batches if needed. **Save each batch response** to temp file immediately: `reputation_batch{N}_{timestamp}.json`.

3. **Enrich checkpoint-scored.json** — Read the saved reputation files back, then for each job: — for each job in the scored checkpoint, add:
   - `company_rating`: float 0.0-5.0, or `null` if not found
   - `rating_reviews`: integer review count, or `0` if not found
   - `rating_source`: string — `"glassdoor"`, `"indeed"`, `"trustpilot"`, or `"not_found"`

4. Save the enriched data back to `checkpoint-scored.json`. Update `state.json` with `step_5_5_complete: true`.

Report: "Reputation lookup complete. {found} companies with ratings, {not_found} not found. Average rating: {avg}."

### Step 6: Financial Viability and Excel Export

Before running the processing script, fetch reference data from DEB Cloud:

1. **UKVI sponsor data** (if `requires_visa=true` and `country=gb`):
   - Extract all unique company names from `checkpoint-scored.json`
   - Call `mcp__deb-jobhunter__get_ukvi_sponsors` with the company names
   - **Save raw response** to temp file: `ukvi_sponsors_{timestamp}.json`
   - Copy/move to `{working_dir}/ukvi-sponsor-data.json` for the processing script

2. **Agency data** (cached locally, refreshed only when DEB Cloud sends signals):

   The agency list is cached at `~/.debytes/cache/agencies-{country}.json`. To check freshness:

   a. Call `mcp__deb-jobhunter__get_agencies_info` with country code → returns `{count, last_updated}`
   b. Read `~/.debytes/cache/agencies-{country}.json` — check the `_last_updated` field in the file
   c. If the file doesn't exist, or `last_updated` differs → re-fetch:
      - Fetch in batches of 100: `mcp__deb-jobhunter__get_agencies(country, offset=0, limit=100)`, then `offset=100`, etc.
      - **Save each batch** to temp file: `agencies_batch{N}_{timestamp}.json` (do NOT keep in context)
      - The first batch (offset=0) includes `keywords` and `keyword_exceptions` (global detection config)
      - Merge all batches into a single file and save to `~/.debytes/cache/agencies-{country}.json` with format:
        ```json
        {"_last_updated": "<from info call>", "agencies": ["Name1", ...], "keywords": [...], "keyword_exceptions": [...]}
        ```
   d. If file exists and `_last_updated` matches → skip re-fetch, use cached file

3. **Run the excel stage** of the processing script:

```bash
python "${PLUGIN_ROOT}/scripts/process_jobs.py" \
  --stage excel \
  --scored "{working_dir}/checkpoint-scored.json" \
  --expectations "{expectations_path}" \
  --config "${PLUGIN_ROOT}/config/job-hunter.ini" \
  --ukvi-data "{working_dir}/ukvi-sponsor-data.json" \
  --agencies "~/.debytes/cache/agencies-{country}.json" \
  --output-dir "{working_dir}"
```

If DEB Cloud is unavailable (degraded mode), omit `--ukvi-data` and `--agencies` flags. The script will fall back to bundled data files.

The script reads the LLM-scored checkpoint and:
1. Filters out remaining jobs with `match_score < 30`
2. For jobs with listed salary: calculates tax, social contributions (NI for UK / cotisations for FR), net monthly, commute costs, financial viability — using country-specific formulas
3. Computes `composite_score = match_score × 0.60 + financial_score × 0.40`
4. Visa sponsor check:
   - **GB**: Cross-references company against UKVI sponsor data from DEB Cloud
   - **FR**: Checks salary against Talent Passport thresholds (any company can sponsor if salary qualifies)
5. Detects recruitment agencies using cached agency data from DEB Cloud
6. Generates formatted Excel workbook with role-based tabs (currency from expectations: GBP/EUR)

The Excel workbook contains:
- **One tab per target role** (sorted by priority): P1 jobs first, then P2, ranked by composite_score
- **All Results**: Every scored listing (uncapped)
- **Summary**: Statistics and metadata

Update `state.json` with `step_6_complete: true`.

Report to user:
- Total scored / after filtering / viable counts
- Platforms used and any that failed
- Top 5 results per role (title, company, salary, composite_score, viable, is_sponsor)
- Excel file path

---

## Important Constraints

- Respect rate limits: wait `request_delay_seconds` between requests to the same platform.
- If a platform blocks or errors, skip it and note the failure — do NOT retry.
- If salary is unlisted, still include the listing but flag it and skip financial calculation.
- For cities not in the INI config commute tables, use the nearest configured city as a fallback and note "commute_estimated".
- UKVI data is fetched via DEB Cloud MCP. Agency data is cached locally and refreshed only when DEB Cloud signals a change.
- If DEB Cloud key is missing or invalid, scraping and data lookups are unavailable. The user can provide their own raw job data for local processing.
- **FR**: Talent Passport visa checking is salary-threshold based — no sponsor list needed.
- **Always save intermediate data** — never rely on conversation context for preserving scraped results.

## Reference Files

- `references/scraping-strategy.md` — Platform scraping instructions and parsing rules
- `references/matching-algorithm.md` — Scoring overview (local vs remote modes)
- `references/csv-output-spec.md` — Output column definitions and Excel formatting
- `${PLUGIN_ROOT}/config/job-hunter.ini` — Shared configuration (general settings)
- `${PLUGIN_ROOT}/config/country-gb.ini` — UK-specific: tax, NI, platforms, visa, commute
- `${PLUGIN_ROOT}/config/country-fr.ini` — FR-specific: tax, social, platforms, visa, commute
- `${PLUGIN_ROOT}/scripts/process_jobs.py` — Processing script (dedup, financial, Excel export)
- `${PLUGIN_ROOT}/examples/job-expectations-example.json` — UK example input schema
- `${PLUGIN_ROOT}/examples/job-expectations-fr.json` — French example input schema
