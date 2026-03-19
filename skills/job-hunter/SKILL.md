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

1. Call the MCP tool (e.g., `scrape_jobs`, `scrape_url`, `get_reputation`, `get_commute_cost`)
2. **Immediately** use the `Write` tool to save the full response to a JSON file in the temp directory
3. Only retain a **brief summary** in your working memory: status, count, file path
4. When you need the data later, use the `Read` tool to load it from the file

**File naming convention** (inside `mcp_jobhunter/`):
```
scrape_{platform}_{city}_{role_slug}_{YYYYMMDD_HHMMSS}.json
detail_batch{N}_{YYYYMMDD_HHMMSS}.json
reputation_batch{N}_{YYYYMMDD_HHMMSS}.json
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

This saves large payloads to disk immediately to avoid saturating the context window.

## Data Persistence

**CRITICAL**: All intermediate data MUST be saved to disk at each step. This ensures that if the conversation runs out of context, the next invocation can resume from the last checkpoint without re-scraping.

### Working Directory

Create a session working directory in the same folder as the expectations JSON:

```
{expectations_dir}/job-search-{YYYYMMDD_HHMMSS}/
├── state.json                          # Current progress tracker
├── checkpoint-raw-combined.json        # All raw results from pipeline (after Step 3)
├── checkpoint-dedup.json               # After deduplication (after Step 3.5)
├── checkpoint-filtered.json            # After first-layer filter (after Step 3.5)
├── checkpoint-enriched.json            # After JD enrichment (after Step 4)
├── checkpoint-scored.json              # After LLM agent scoring (after Step 5)
├── company-checks.json                 # Company reputation + UKVI + agency (Step 5.5)
├── commute-data.json                   # Commute costs from DEB Cloud (Step 6)
├── checkpoint-final.json               # After financial calc + visa check (after Step 6)
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
  "step_3_batch_id": null,
  "step_3_complete": false,
  "step_3_5_complete": false,
  "step_4_batch_id": null,
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
3. If Step 3 has a `batch_id`: poll for results, then continue from Step 3.5
4. If Step 3 was complete: load `checkpoint-raw-combined.json`, continue to Step 3.5
5. If Step 3.5+ complete: load the latest checkpoint, skip ahead
6. If no working directory found: start fresh from Step 1

---

## Execution Mode

Proceed through all steps without asking for user confirmation between steps. Only pause to ask the user if: (1) DEB Cloud key is missing, (2) an error requires a decision, or (3) the search matrix exceeds 100 queries. All file writes, script executions, and MCP calls should proceed automatically.

## Workflow

Execute these steps in order. Save intermediate data at each step. Log progress to the user after each major step. **After completing each step, update `state.json`** with the step's completion flag and `updated_at` timestamp.

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

### Step 2: Build Search Matrix and Estimate Credits

1. For each target role, get the `search_keywords` array (use first keyword as primary).
2. Combine all roles with all cities from both P1 and P2 groups.
3. **Select platforms** — read `[platforms]` from the shared INI config:
   - `default`: priority-ordered list of 4 platforms (used for paid plans).
   - `free`: smaller list of 2 platforms (used for free plan).
   - If `plan=free` (from ping response): use the `free` list and only the first keyword per role (`free_max_keywords=1`). The user can request more platforms, but warn them about credit impact and show the estimate before proceeding.
   - All other plans: use the `default` list. The user can request additional platforms beyond the default 4; show the estimate so they can decide.
   - **GB (academia)**: use `[platforms_academia]` from country INI instead.
4. Only include platforms that are also enabled (`=1`) in the country INI `[platforms]` section.
5. Build the search matrix as a list of `{query, platforms, location, country, min_salary}` entries.

**Credit estimation (Gate 1):**
Call `mcp__deb-jobhunter__estimate_credits` with the search matrix. This returns a breakdown of estimated credits (scraping, enrichment, scoring, reputation, total). Show the user the estimate and confirm before proceeding.

### Step 3: Scrape Job Listings (Pipeline)

**Requires DEB Cloud key.** If degraded mode, skip this step and instruct the user to provide raw job data.

**Platform codes** (match INI platform names):
- **GB industry**: `linkedin`, `indeed`, `reed`, `totaljobs`, `cwjobs`, `cvlibrary`, `adzuna`
- **GB academia**: use `mcp__deb-jobhunter__scrape_url` for jobs.ac.uk and EURAXESS with specific URLs from `[platform_urls_academia]` INI section
- **FR**: `linkedin`, `indeed_fr`, `welcometothejungle`, `apec`, `hellowork`, `lesjeudis`

**Launch scrape workers:**

1. Call `mcp__deb-jobhunter__launch_scrape_jobs` with the search matrix and `target_roles` list.
   - Returns `{batch_id, worker_count, estimated_credits}`.
   - Workers run in parallel on the server — scraping, parsing, deduplication, and caching happen automatically.

2. **Wait for completion:**
   Call `mcp__deb-jobhunter__poll_jobs(batch_id=...)` once.
   - The server polls internally and streams progress via MCP progress notifications.
   - Returns when status is `COMPLETE`, `PARTIAL`, `FAILED`, or after timeout.
   - Response: `{status, progress: {total, done, failed}, credits_consumed, tasks: [...]}`.
   - If `timed_out=true` in response, call `poll_jobs` again to continue waiting.

3. **Get results:**
   Call `mcp__deb-jobhunter__get_scrape_results(batch_id=...)`.
   - **If response contains `jobs` key**: use the `Write` tool to save the `jobs` array as JSON to `{working_dir}/checkpoint-raw-combined.json`.
   - **If response contains `download_url` key**: download to disk via curl:
     ```bash
     curl -s --ssl-no-revoke -o "{working_dir}/checkpoint-raw-combined.json" "{download_url}"
     ```
   - Each job includes `listing_score` (0-100) from the parser, used for filtering.
   - **IMPORTANT**: Never try to pipe MCP tool responses through Python stdin. Use `Write` for inline results or `curl` for downloads.

Report progress: "Scraping complete. {N} total listings from {platforms}. Credits used: {credits}."

### Step 3.5: Deduplicate and Filter

1. **Deduplicate** via process_jobs.py:
```bash
python "${PLUGIN_ROOT}/scripts/process_jobs.py" \
  --stage dedup \
  --raw "{working_dir}/checkpoint-raw-combined.json" \
  --output-dir "{working_dir}"
```
Saves `checkpoint-dedup.json`.

2. **First-layer filter** — drop low-relevance jobs before enrichment:
```bash
python "${PLUGIN_ROOT}/scripts/process_jobs.py" \
  --stage filter \
  --dedup "{working_dir}/checkpoint-dedup.json" \
  --expectations "{expectations_path}" \
  --filter-threshold 40 \
  --output-dir "{working_dir}"
```
Uses `listing_score` from the parser + salary floor heuristic. Free — no API calls. Saves `checkpoint-filtered.json`.

Report: "After dedup: {N} unique. After filter: {M} jobs (dropped {K} low-relevance)."

### Step 4: JD Enrichment (Gate 2)

**Requires DEB Cloud key.** Read `[enrichment]` from INI config. If `enabled=0`, skip to Step 5.

1. Prepare UUIDs for enrichment via process_jobs.py:
   - If `plan=free`: use `free_max_enrich` from INI `[enrichment]` section (default 250).
   - All other plans: enrich all filtered jobs (omit `--max-enrich`).
```bash
python "${PLUGIN_ROOT}/scripts/process_jobs.py" \
  --stage enrich-prep \
  --filtered "{working_dir}/checkpoint-filtered.json" \
  --max-enrich {N} \
  --output-dir "{working_dir}"
```
Outputs `enrich-payload.json` — JSON array of UUIDs for top N jobs by listing_score.

2. **If ≤50 UUIDs** (inline mode): read the UUIDs and call directly:
   - `mcp__deb-jobhunter__launch_enrich_jobs(uuids=[...])`
3. **If >50 UUIDs** (batch mode):
   a. Get file size: `wc -c < "{working_dir}/enrich-payload.json"`
   b. Call `mcp__deb-jobhunter__init_enrichment(uuid_count=N, file_size=BYTES)`
   c. Upload the file:
      ```bash
      curl -s --ssl-no-revoke -X PUT -H "Content-Type: application/json" \
        -H "Content-Length: BYTES" \
        --data-binary @"{working_dir}/enrich-payload.json" "{upload_url}"
      ```
   d. Call `mcp__deb-jobhunter__launch_enrich_jobs(batch_id="...")`
4. Returns `{batch_id, worker_count, jobs_to_enrich}`.
4. **Wait for completion** using `mcp__deb-jobhunter__poll_jobs(batch_id=...)` — single call, server streams progress.
5. **Get results** via `mcp__deb-jobhunter__get_enrich_results(batch_id=...)`.
   - **If response contains `descriptions` key**: JD data returned inline. Use `Write` to save to `{working_dir}/checkpoint-enrich-raw.json`.
   - **If response contains `download_url` key**: download via curl:
     ```bash
     curl -s --ssl-no-revoke -o "{working_dir}/checkpoint-enrich-raw.json" "{download_url}"
     ```
   - Each JD has: `responsibilities`, `requirements_hard`, `requirements_soft`, `tech_stack`, `seniority_signals`, `yoe_required`, `education`.
6. Merge JD data back into the filtered jobs. For each enriched job, set:
   - `jd_fetched: true`, `jd_status: "enriched"`
   - JD fields populated from the enrichment response
7. For jobs not enriched (unavailable, failed), set `jd_fetched: false`, `jd_status: "unavailable"` or `"failed"`.
8. Save merged result as `checkpoint-enriched.json`.

Report: "Enriched {N} of {M} jobs. {unavailable} JDs unavailable. Credits used: {credits}."

### Step 5: Job Scoring (8 Dimensions)

Read `scoring_mode` from `[scoring]` in the INI config.

**If `scoring_mode = remote`** (requires DEB Cloud key):

1. Read the candidate document (resume/profile from Step 1).
2. Build profile text: concatenate resume content + candidate skills from `[candidate_skills]` in INI (max 8000 chars — summarize if needed).
3. Build expectations context from the expectations JSON:
   `{target_roles, p1_cities, p2_cities, requires_visa, country, sector}`
4. Read jobs from `checkpoint-enriched.json` (or `checkpoint-filtered.json` if enrichment was skipped).
5. **If ≤15 jobs** (inline mode):
   - Call `mcp__deb-jobhunter__launch_score_jobs(jobs=[...], expectations={...}, profile="...")`.
6. **If >15 jobs** (batch mode via GCS):
   a. Get file size: `wc -c < checkpoint-enriched.json`
   b. Call `mcp__deb-jobhunter__init_scoring(job_count=N, file_size=BYTES, expectations={...}, profile="...")`
   c. Upload the file:
      ```bash
      curl -s --ssl-no-revoke -X PUT -H "Content-Type: application/json" \
        -H "Content-Length: BYTES" \
        --data-binary @"{working_dir}/checkpoint-enriched.json" "{upload_url}"
      ```
   d. Call `mcp__deb-jobhunter__launch_score_jobs(batch_id="...")`
7. **Wait for completion** using `mcp__deb-jobhunter__poll_jobs(batch_id=...)`.
8. **Get results** via `mcp__deb-jobhunter__get_score_results(batch_id=...)`.
   - **If response contains `scored_jobs`**: use `Write` to save to `{working_dir}/checkpoint-scored.json`.
   - **If response contains `download_url`**: download via curl:
     ```bash
     curl -s --ssl-no-revoke -o "{working_dir}/checkpoint-scored.json" "{download_url}"
     ```
7. Scoring returns 8 dimensions: `skill_match`, `requirements_match`, `role_match`, `experience_match`, `seniority_match`, `salary_match`, `location_priority`, `sponsor_match`.
   - For enriched jobs: all 8 dimensions scored.
   - For non-enriched jobs: `requirements_match` and `experience_match` are null, `skill_match` defaults to 50.
8. Filter out jobs with `match_score < 30`.

**If `scoring_mode = local`**:

1. Run the full pipeline locally which includes scoring:
   ```bash
   python "${PLUGIN_ROOT}/scripts/process_jobs.py" \
     --stage all \
     --raw "{working_dir}/checkpoint-raw-combined.json" \
     --expectations "{expectations_path}" \
     --config "${PLUGIN_ROOT}/config/job-hunter.ini" \
     --output-dir "{working_dir}"
   ```
2. This runs dedup + local heuristic scoring + financial calc + Excel in one pass.
3. Output: `checkpoint-scored.json` and Excel workbook.
4. Skip Steps 5.5 and 6 (already included in `--stage all`).

**Update state.json**: Set `step_5_complete: true`, `current_step: 5.5`, `updated_at: <now>`.

Report: "Scored {N} jobs. {kept} with match_score >= 30, {removed} discarded."

### Step 5.5: Company Checks (Reputation + UKVI)

Enrich scored jobs with employee review ratings AND visa sponsor status in one step.

**Requires DEB Cloud key.** If degraded mode, skip this step.

1. **Launch company checks** using the scoring batch ID:
   - Call `mcp__deb-jobhunter__launch_company_checks(score_batch_id="...")`.
   - The server extracts unique companies from scored jobs (match_score >= 30), runs reputation lookup + UKVI sponsor check in batches of 15.
   - Returns `{batch_id, worker_count, companies_count}`.

2. **Wait for completion** using `mcp__deb-jobhunter__poll_jobs(batch_id=...)`.

3. **Get results** via `mcp__deb-jobhunter__get_company_check_results(batch_id=...)`.
   - **If response contains `companies`**: save to `{working_dir}/company-checks.json`.
   - **If response contains `download_url`**: download via curl.
   - Each entry has: `company`, `rating`, `review_count`, `source`, `reputation_status`, `is_sponsor`, `sponsor_route`.

4. **Merge into scored jobs** via process_jobs.py:
```bash
python "${PLUGIN_ROOT}/scripts/process_jobs.py" \
  --stage reputation-merge \
  --scored "{working_dir}/checkpoint-scored.json" \
  --reputation-data "{working_dir}/company-checks.json" \
  --output-dir "{working_dir}"
```
Adds `company_rating`, `rating_reviews`, `rating_source`, `is_sponsor`, `sponsor_route` to each job.

**Update state.json**: Set `step_5_5_complete: true`, `current_step: 6`, `updated_at: <now>`.

Report: "Company checks complete. {rated} companies rated, {sponsors} sponsors found."

### Step 6: Financial Viability and Excel Export

Before running the processing script, fetch commute cost data:

1. **Commute cost data** (dynamic, replaces INI commute tables):
   - Extract unique city names from `checkpoint-scored.json` `location` field
   - **Normalize cities**: strip postcodes, "England, United Kingdom", "Area" suffixes. E.g. "London EC2A 2AP" → "London", "Manchester, England, United Kingdom" → "Manchester". Deduplicate after normalizing.
   - Skip the candidate's home city (commute = 0)
   - Read origin from expectations JSON: `candidate.home_city`
   - Call `mcp__deb-jobhunter__get_commute_cost` in batches of 5 destinations
   - Merge all batch results into `{working_dir}/commute-data.json`
   - Pass `--commute-data` flag to process_jobs.py (overrides INI commute tables)

2. **Run the excel stage** of the processing script. The `checkpoint-scored.json` MUST be a flat JSON array of jobs (not wrapped in `scored_jobs`/`stats`). Each job must have ALL fields from dedup + score fields from scoring. If it's a dict with `scored_jobs` key, the merge step (Step 5f) was skipped — go back and fix it.

```bash
python "${PLUGIN_ROOT}/scripts/process_jobs.py" \
  --stage excel \
  --scored "{working_dir}/checkpoint-scored.json" \
  --expectations "{expectations_path}" \
  --config "${PLUGIN_ROOT}/config/job-hunter.ini" \
  --commute-data "{working_dir}/commute-data.json" \
  --output-dir "{working_dir}"
```

If DEB Cloud is unavailable (degraded mode), omit `--commute-data` flag. The script will fall back to INI commute tables.

The script reads the LLM-scored checkpoint and:
1. Filters out remaining jobs with `match_score < 30`
2. For jobs with listed salary: calculates tax, social contributions (NI for UK / cotisations for FR), net monthly, commute costs, financial viability — using country-specific formulas
3. Computes `composite_score = match_score × 0.60 + financial_score × 0.40`
4. Visa sponsor and agency status already set on jobs by company checks MCP (Step 5.5)
5. Generates formatted Excel workbook with role-based tabs (currency from expectations: GBP/EUR)

The Excel workbook contains:
- **One tab per target role** (sorted by priority): P1 jobs first, then P2, ranked by composite_score
- **All Results**: Every scored listing (uncapped)
- **Summary**: Statistics and metadata

**Update state.json**: Set `step_6_complete: true`, `updated_at: <now>`.

Report to user:
- Total scored / after filtering / viable counts
- Platforms used and any that failed
- Top 5 results per role (title, company, salary, composite_score, viable, is_sponsor)
- Excel file path

---

## Terminal Output

Read `terminal_mode` from `[output]` in the INI config. If `pipeline` (default), follow the exact formatting below. If `standard`, skip this section entirely and use your normal output style.

**When `terminal_mode = pipeline`**: Follow this exact output format to give users a polished pipeline experience. Print each block as markdown text between tool calls. Use Unicode block characters for progress bars and emoji for status icons.

**Progress bar helper** — use this pattern for all bars:
```
filled = "█" * int(pct / 5)    # 20 chars = 100%
empty  = "░" * (20 - len(filled))
bar = f"[{filled}{empty}]"
```

### After Step 2 (estimate_credits):
```
🔍 Search matrix: {roles} roles × {cities} cities × {platforms} platforms = {workers} parallel workers
🔥 Estimated cost: ~{total} credits  |  Quota: {remaining} remaining ✅
```
Where `remaining = ping.monthly_credits - ping.credits_used`. Show ✅ if remaining > total, ⚠️ if remaining < total * 1.2, ❌ if remaining < total.

### Step 3 (scraping):
Print before calling `poll_jobs(batch_id)`:
```
🔄 Scraping [{bar}] {pct}%  |  {done}/{total} workers
  {platform} / {location}  {icon}  {result_count} jobs    {credits} cr
  {platform} / {location}  {icon}  {result_count} jobs    {credits} cr
  Credits consumed: {credits_consumed}
```
The server streams progress via MCP notifications — the progress bar updates as workers complete.
When `poll_jobs` returns, render the final state with all tasks showing ✅/❌.

Where:
- `pct = int(done / total * 100)`
- Per-task icon: ✅ if COMPLETE, ⏳ if RUNNING, ❌ if FAILED, ⬜ if QUEUED
- Per-task data comes from `poll_jobs.tasks[]`: `result_count`, `credits` fields

### After Step 3 + 3.5 (scraping + dedup + filter complete):
```
🔍 Scraping complete in {elapsed}  →  {raw_total} jobs raw  |  dedup: {dedup_count}  |  filter: {filter_count}
```
Where `elapsed` = time since `launch_scrape_jobs` call (format: `42s`, `1m 23s`, `2m 05s`).

### Step 4 (enrichment):
Print before calling `poll_jobs(batch_id)`:
```
🔬 Enriching [{bar}] {pct}%  |  {done}/{total} workers
  Worker 1  {icon}  {result_count} JDs    {credits} cr
  Worker 2  {icon}  {result_count} JDs    {credits} cr
  Worker 3  {icon}  {result_count} JDs    {credits} cr
  Credits consumed: {credits_consumed}
```
When `poll_jobs` returns, render the final state with all workers showing ✅/❌:
```
🔬 Enriching [████████████████████] 100%  |  {done}/{total} workers
  Worker 1  ✅  {result_count} JDs    {credits} cr
  Worker 2  ✅  {result_count} JDs    {credits} cr
  Worker 3  ✅  {result_count} JDs    {credits} cr
  Credits consumed: {credits_consumed}

🔬 Enrichment complete in {elapsed}  →  {enriched}/{total} JDs fetched  ({unavailable} unavailable)
```

### Step 5 (scoring):
Print before calling `poll_jobs(batch_id)`:
```
📊 Scoring [{bar}] {pct}%  |  {done}/{total} workers
  Batch 1  {icon}  {result_count} jobs    {credits} cr
  Batch 2  {icon}  {result_count} jobs    {credits} cr
  Credits consumed: {credits_consumed}
```
When `poll_jobs` returns, render final state:
```
📊 Scoring [████████████████████] 100%  |  {done}/{total} workers
  Batch 1  ✅  {result_count} jobs    {credits} cr
  Batch 2  ✅  {result_count} jobs    {credits} cr
  Credits consumed: {credits_consumed}

📊 Scoring complete in {elapsed}  →  {scored}/{total} jobs scored
```

### Step 5.5 (company checks):
Print before calling `poll_jobs(batch_id)`:
```
🏢 Company checks [{bar}] {pct}%  |  {done}/{total} workers
  Batch 1  {icon}  {result_count} companies    {credits} cr
  Batch 2  {icon}  {result_count} companies    {credits} cr
  Credits consumed: {credits_consumed}
```
When `poll_jobs` returns, render final state:
```
🏢 Company checks [████████████████████] 100%  |  {done}/{total} workers
  Batch 1  ✅  {result_count} companies    {credits} cr
  Batch 2  ✅  {result_count} companies    {credits} cr
  Credits consumed: {credits_consumed}

🏢 Company checks complete in {elapsed}  →  {rated} rated, {sponsors} sponsors, {agencies} agencies
```

### Step 6 (financial + Excel):
```
🚗 Commute costs...                    {credits} cr
```

### Final summary (after Step 6):
```
✅ Done in {total_elapsed}  |  Total: {total_credits} credits  |  Remaining: {remaining}

📊 {excel_full_path}
   P1: {p1_count} jobs  |  P2: {p2_count} jobs  |  All: {all_count} jobs

🏆 Top 5:
   1. {title} @ {company} — score {composite_score}  ({salary_text}, {location})
   2. {title} @ {company} — score {composite_score}  ({salary_text}, {location})
   3. {title} @ {company} — score {composite_score}  ({salary_text}, {location})
   4. {title} @ {company} — score {composite_score}  ({salary_text}, {location})
   5. {title} @ {company} — score {composite_score}  ({salary_text}, {location})
```
Where:
- `total_elapsed`: wall-clock time from session start
- `total_credits`: sum of all credits charged across all tools
- `remaining`: updated quota after all charges
- `excel_full_path`: full absolute path to the Excel file (from process_jobs.py output)
- P1/P2 counts from process_jobs.py output
- Top 5: highest `composite_score` jobs from results, with salary and location

---

## Important Constraints

- **Windows encoding**: On Windows, always use `encoding='utf-8'` when opening JSON files with Python (`open(path, encoding='utf-8')`). The default `cp1252` encoding will fail on special characters in job data. When chaining `curl` download with Python verification in Bash, use separate commands.
- Respect rate limits: wait `request_delay_seconds` between requests to the same platform.
- If a platform blocks or errors, skip it and note the failure — do NOT retry.
- If salary is unlisted, still include the listing but flag it and skip financial calculation.
- Commute costs are dynamically fetched via `get_commute_cost` MCP tool. If the tool is unavailable, the script falls back to INI config values.
- UKVI sponsor and agency status are set by company checks MCP tool (Step 5.5).
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
- `${PLUGIN_ROOT}/scripts/process_jobs.py` — Processing script (dedup, filter, financial, Excel export)
- `${PLUGIN_ROOT}/examples/job-expectations-example.json` — UK example input schema
- `${PLUGIN_ROOT}/examples/job-expectations-fr.json` — French example input schema
