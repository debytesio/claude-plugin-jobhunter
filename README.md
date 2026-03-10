# Job Hunter — Claude Code Plugin

Search job platforms (UK and France), match jobs to your profile, check visa sponsorship (UKVI for UK, Talent Passport for France), calculate financial viability (including commute costs), and export ranked results to an Excel workbook (.xlsx).

Powered by [DEB Cloud](https://debytes.io/products/cloud).

## Quick Start

### 1. Get a DEB Cloud API Key

Register at [debytes.io/products/cloud](https://debytes.io/products/cloud) and create an API key.

### 2. Set the Environment Variable

```bash
export DEB_CLOUD_API_KEY=deb_your_key_here
```

Add to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.) for persistence.

### 3. Install the Plugin

```
/plugin marketplace add debytesio/claude-plugins
/plugin install job-hunter@debytes
```

That's it. The plugin connects to DEB Cloud automatically — no MCP server setup required.

## Usage

### Natural language
```
find the best job matching my expectation C:\path\to\job-expectations.json
```

### Slash command
```
/find-jobs C:\path\to\job-expectations.json
```

## Input: Expectations JSON

Create a JSON file with your job search criteria. See `examples/job-expectations-example.json` for the full schema.

**Required sections:**
- `candidate` — name, profile path, home location
- `target_roles` — roles to search with min salary and priority
- `locations` — P1 (income priority) and P2 (commute priority) city groups
- `current_situation` — current gross salary and net monthly take-home

**Optional sections:**
- `visa` — set `requires_visa: true` to enable UKVI sponsor checking
- `preferences` — work mode, contract type, hybrid days, improvement threshold
- `api_keys` — Reed.co.uk API key for structured API access

## Output: Excel Workbook (.xlsx)

Saved to a session working directory (`job-search-{timestamp}/`) alongside the expectations JSON.

**4 sheets:**
1. **P1 - Income Priority** — Top 20 results for P1 cities
2. **P2 - Commute Priority** — Top 20 results for P2 cities
3. **All Results** — Every scored listing (uncapped)
4. **Summary** — Search statistics and financial parameters

**30 columns** including: job title, company, UKVI sponsor status, location, salary, match score (6 sub-scores), financial viability, commute costs, platform, URL, and notes.

## Data Persistence

All intermediate data is saved to disk at each step. If a conversation runs out of context, the next invocation detects existing checkpoints and resumes from where it left off.

## Degraded Mode (No API Key)

When `DEB_CLOUD_API_KEY` is not set:
- **Scraping**: Unavailable
- **UKVI check**: Falls back to local CSV if provided
- **Agency detection**: Falls back to bundled data files
- **Reputation**: Skipped
- **Dedup, Financial, Scoring, Excel**: All work normally

## Platforms

**UK:** Reed, CV-Library, CW Jobs, Totaljobs, Indeed, LinkedIn, Adzuna

**France:** Indeed.fr, Welcome to the Jungle, LinkedIn, Adzuna

## Scoring

**Match score (0-100):** role alignment, skill overlap, seniority fit, salary threshold, location priority, UKVI sponsor match.

**Financial score (0-100):** based on `new_take_home - commute_costs >= current_take_home * improvement_threshold`.

**Composite score:** `match * 0.60 + financial * 0.40` — used for final ranking.

## Requirements

- Python 3.10+
- openpyxl
- Windows (macOS and Linux support coming soon)

## License

Apache-2.0

---

Built by [Franck Fotso](https://github.com/franckfotso) at [DeBytes](https://debytes.io)

[LinkedIn](https://linkedin.com/company/debytes) | [GitHub](https://github.com/debytesio) | [X](https://x.com/debytesio)
