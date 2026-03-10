---
description: Search job platforms and find best matches for candidate expectations
argument-hint: <path-to-expectations-json>
allowed-tools: [Read, Write, Bash, Glob, Grep, WebSearch, WebFetch, mcp__deb-jobhunter__scrape_jobs, mcp__deb-jobhunter__scrape_url, mcp__deb-jobhunter__get_ukvi_sponsors, mcp__deb-jobhunter__get_agencies, mcp__deb-jobhunter__get_reputation, mcp__deb-jobhunter__ping]
---

# Find Jobs

Search job platforms for roles matching the candidate profile and financial expectations. Powered by DEB Cloud.

## Arguments

The user provided this expectations file path: $ARGUMENTS

If no path was provided, ask the user for the path to their expectations JSON file. An example file is available at `${PLUGIN_ROOT}/examples/job-expectations-example.json`.

## Instructions

Execute the full job-hunter skill workflow:

0. **Validate DEB Cloud API key** — Read `DEB_CLOUD_API_KEY` from environment. Call `mcp__deb-jobhunter__ping` to validate. If invalid or missing, warn the user: "DEB Cloud API key not configured. Register at debytes.io/products/cloud to get a key. Running in degraded mode (no scraping, limited data)."

1. **Read the expectations JSON** from the path argument. Validate it has the required sections: `candidate`, `target_roles`, `locations`, `current_situation`.

2. **Read the configuration** from `${PLUGIN_ROOT}/config/job-hunter.ini`.

3. **Resolve the candidate document** from the expectations JSON: use `resume_path` (primary) or `profile_path` (fallback). For `.docx`/`.doc` formats, run the extraction utility first (see Step 1 in the skill).

4. **Check for existing working directory** (`job-search-*` in the expectations folder) with a `state.json`. If found, resume from the last checkpoint instead of starting fresh.

5. **Follow the full workflow** of the job-hunter skill:
   - Load inputs and validate
   - Build the search matrix (roles x locations x platforms)
   - Scrape job listings using DEB Cloud MCP tools — **save each query result immediately to disk**
   - After scraping, combine all per-query JSONs into `checkpoint-raw-combined.json`
   - Deduplicate via process_jobs.py
   - LLM agent scoring
   - Reputation lookup via DEB Cloud
   - Financial viability, visa check, agency detection, and Excel export via process_jobs.py

6. **Report results** to the user with summary statistics, top matches, and Excel file path.

## Reference Files

All skill references are at `${PLUGIN_ROOT}/skills/job-hunter/references/`:
- `scraping-strategy.md` — Platform-specific scraping instructions
- `matching-algorithm.md` — Scoring rubric and weights
- `financial-viability.md` — Tax, NI, and commute cost formulas
- `csv-output-spec.md` — Excel output column definitions and formatting
