# Scraping Strategy — Platform-Specific Instructions

## Key Tools

### `mcp__deb-jobhunter__scrape_jobs` — Search Results

Primary tool for scraping job listings. Handles platform URL construction and proxy routing server-side:

```
mcp__deb-jobhunter__scrape_jobs(
  query="AI Engineer",
  platforms=["indeed"],  # 1 per call
  country="GB",          # or "FR"
  location="London"
)
```

Returns parsed job listings from all requested platforms in a single call. Platforms are scraped in parallel server-side.

**Context management**: Save the full response to a temp file immediately after each call (see SKILL.md Context Management section). Only keep a brief summary (platform, job count, file path) in context. Read the file back when you need to parse/extract jobs.

### `mcp__deb-jobhunter__scrape_url` — Detail Pages & Custom URLs

For scraping individual job detail pages or academic platforms. Supports batch mode — up to 5 URLs per call, scraped in parallel:

```
mcp__deb-jobhunter__scrape_url(
  urls=[
    "https://www.reed.co.uk/jobs/ai-engineer/12345",
    "https://www.jobs.ac.uk/job/ABC123",
    "https://www.cv-library.co.uk/job/12345/ai-engineer"
  ],
  use_javascript=true,
  output="markdown",
  geo="gb",
  locale="en-gb"
)
```

**Context management**: Same as `scrape_jobs` — save the full response to a temp file immediately and Read back when parsing.

**Country-specific settings**: Set `geo` and `locale` based on the expectations JSON `country` field:
- `gb`: `geo="gb"`, `locale="en-gb"`
- `fr`: `geo="fr"`, `locale="fr-fr"`

---

## Pagination

The INI config specifies `max_pages_per_platform = 2` (default). This value is passed as `max_pages` to `launch_scrape_jobs` and `estimate_credits`. The MCP server handles pagination internally. Users can increase `max_pages_per_platform` in the INI for broader results (more pages = more credits).

---

## Platform Priority Order — by Country

Platforms are loaded from the country-specific INI file (`country-{code}.ini`). Only scrape platforms where `[platforms]` has value `1`.

### UK Platforms (`country=gb`)

Available platform codes for `mcp__deb-jobhunter__scrape_jobs`: `linkedin`, `indeed`, `reed`, `totaljobs`, `cwjobs`, `cvlibrary`, `adzuna`

Scrape platforms in this order. Skip any that fail and continue to the next.

### 1. LinkedIn (Via DEB Cloud)

- Use `mcp__deb-jobhunter__scrape_jobs` with `platforms=["linkedin"]`
- If a login wall is returned instead of job listings, skip gracefully and note the failure
- No salary parameter available — all salary data must be parsed from description

### 2. Indeed UK (High anti-bot — attempt with caution)

- Use `mcp__deb-jobhunter__scrape_jobs` with `platforms=["indeed"]`
- No salary URL parameter — must filter results post-scrape by parsing salary text
- If scraping fails (bot detection), log failure and skip

### 3. Reed (Structured data, salary filter)

**With API key** (if `api_keys.reed` is set in expectations JSON):
- Endpoint: `https://www.reed.co.uk/api/1.0/search`
- Auth: HTTP Basic — API key as username, empty password
- Parameters: `keywords={keyword}&locationName={location}&minimumSalary={min_salary}&fullTime=true&distanceFromLocation=25&resultsToTake=25`
- Response: JSON with `results[]` containing `jobId`, `jobTitle`, `employerName`, `locationName`, `minimumSalary`, `maximumSalary`, `jobUrl`, `date`
- Use `WebFetch` with the constructed URL and Basic auth header

**Without API key** (via DEB Cloud):
- Use `mcp__deb-jobhunter__scrape_jobs` with `platforms=["reed"]`
- The server handles URL construction and pagination
- Parse job cards from the returned content

### 4. Totaljobs (Medium reliability)

- Use `mcp__deb-jobhunter__scrape_jobs` with `platforms=["totaljobs"]`
- Parse job cards from results: title, company, salary, location, posted date, URL

### 5. CW Jobs (IT/tech specialist)

- Use `mcp__deb-jobhunter__scrape_jobs` with `platforms=["cwjobs"]`
- Parse results for: job title, company, salary range, location, description snippet, job URL

### 6. CV-Library (Salary sorting available)

- Use `mcp__deb-jobhunter__scrape_jobs` with `platforms=["cvlibrary"]`
- Parse results for: job title, company, salary range, location, description snippet, job URL

### 7. Adzuna (Structured API-like results)

- Use `mcp__deb-jobhunter__scrape_jobs` with `platforms=["adzuna"]`
- Good salary data availability
- Parse results for: job title, company, salary range, location, job URL

---

### French Platforms (`country=fr`)

Available platform codes: `linkedin`, `indeed_fr`, `welcometothejungle`, `apec`, `hellowork`, `lesjeudis`

Scrape platforms in this order. Skip any that fail and continue to the next.

#### 1. LinkedIn France (Via DEB Cloud)

- Use `mcp__deb-jobhunter__scrape_jobs` with `platforms=["linkedin"]`, `country="FR"`
- Same approach as UK LinkedIn — public job search pages, no login required
- If login wall returned, skip gracefully

#### 2. Indeed.fr (Good coverage — high anti-bot)

- Use `mcp__deb-jobhunter__scrape_jobs` with `platforms=["indeed_fr"]`, `country="FR"`
- No salary URL parameter — filter results post-scrape
- If bot detection, skip gracefully

#### 3. Welcome to the Jungle (Tech/startup focus)

- Use `mcp__deb-jobhunter__scrape_jobs` with `platforms=["welcometothejungle"]`, `country="FR"`
- English interface available — good for international tech companies in France
- Strong startup and tech company focus

#### 4. APEC (Cadres/executives — medium anti-bot)

- Use `mcp__deb-jobhunter__scrape_jobs` with `platforms=["apec"]`, `country="FR"`
- Focused on cadres (managers/professionals) — good for senior roles
- Parse results for: job title, company, salary range, location, contract type

#### 5. HelloWork (Broad coverage)

- Use `mcp__deb-jobhunter__scrape_jobs` with `platforms=["hellowork"]`, `country="FR"`
- Formerly RegionsJob — broad French job market coverage
- Parse results for: job title, company, salary, location, description

#### 6. LesJeudis (IT specialist — low anti-bot)

- Use `mcp__deb-jobhunter__scrape_jobs` with `platforms=["lesjeudis"]`, `country="FR"`
- IT/tech specialist board — good for developer and engineering roles
- Parse results for: job title, company, salary, location, tech stack

---

## Academic Platforms (UK) — `sector=academia`

When the expectations JSON has `"sector": "academia"`, use the `[platforms_academia]` and `[platform_urls_academia]` sections from the INI instead of the standard `[platforms]` / `[platform_urls]`.

### 1. jobs.ac.uk (Priority 1 — Primary UK academic board)

- **Anti-bot**: Low — public listings, no login required
- **Page 1**: `https://www.jobs.ac.uk/search/?keywords={keyword}&distance=250&sortOrder=1&pageSize=25&startIndex=1`
- **Page 2**: `https://www.jobs.ac.uk/search/?keywords={keyword}&distance=250&sortOrder=1&pageSize=25&startIndex=26`
- URL-encode keyword (spaces become `+`)
- Use `mcp__deb-jobhunter__scrape_url` with both pages batched, `use_javascript=true`, `geo="gb"`, `locale="en-gb"`
- **Field extraction**: title, employer (university name), department, location, salary text, closing date, job URL
- **Salary parsing**: Look for "Grade X" patterns → map via `[academic_salary_grades]` in INI. Also look for explicit £ ranges.
- **Notes**: Nearly ALL UK university positions are posted here. This is the single most important academic platform.

### 2. EURAXESS (Priority 2 — European research portal)

- **Anti-bot**: Low — EU public portal
- **Page 1**: `https://euraxess.ec.europa.eu/jobs/search?keywords={keyword}&location%5B%5D=United+Kingdom`
- **Page 2**: `https://euraxess.ec.europa.eu/jobs/search?keywords={keyword}&location%5B%5D=United+Kingdom&page=1`
- Use `mcp__deb-jobhunter__scrape_url` with both pages batched, `use_javascript=true`, `geo="gb"`, `locale="en-gb"`
- **Salary parsing**: Often lists salary bands or "competitive". Parse £ ranges where available.
- **Notes**: Covers UK + European positions. Good for funded research posts.

### 3. Indeed UK & LinkedIn (reuse existing platforms)

Same approach as the industry UK platforms above — use `mcp__deb-jobhunter__scrape_jobs` with academic search keywords from `target_roles[].search_keywords`.

---

### Academic Salary Text Parsing (UK)

In addition to the standard UK salary parsing rules above, academic roles use "Grade X" notation:

| Pattern | Example | Interpretation |
|---------|---------|----------------|
| Grade with range | "Grade 7, £38,205 - £45,585 per annum" | min=38205, max=45585 |
| Grade only | "Grade 7" or "Grade 7/8" | Look up `[academic_salary_grades]` from INI: grade_7_min=38205, grade_7_max=45585 |
| Spine points | "Spine point 31-37" | Cannot parse — mark salary_unlisted=true |
| "Competitive" | "Competitive salary" | salary_unlisted=true |

**Parsing priority**: Try explicit £ range first, then Grade lookup, then mark as unlisted.

---

## Batching Strategy

Use `mcp__deb-jobhunter__scrape_jobs` with 1 platform per call. Content is truncated at 30k chars to keep responses manageable.

**Per query** — one platform per call:
```
Call 1: scrape_jobs(query="AI Engineer", platforms=["linkedin"], location="London")
Call 2: scrape_jobs(query="AI Engineer", platforms=["indeed"], location="London")
Call 3: scrape_jobs(query="AI Engineer", platforms=["reed"], location="London")
Call 4: scrape_jobs(query="AI Engineer", platforms=["totaljobs"], location="London")
```

For detail page enrichment, batch up to 5 URLs per `scrape_url` call:
```
Call 1: scrape_url(urls=["url1", "url2", "url3", "url4", "url5"])
Call 2: scrape_url(urls=["url6", "url7", "url8", "url9", "url10"])
```

---

## Query Construction Rules

For each `(role, location)` combination:
1. Use the first `search_keywords` entry for the role as the primary keyword
2. If the primary keyword returns fewer than 5 results on a platform, try the second keyword
3. Apply `min_salary` from the role's expectations where the platform supports it
4. The MCP server handles pagination (page 1 and page 2) automatically

**Example for AI Engineer in London:**
```
mcp__deb-jobhunter__scrape_jobs(
  query="AI Engineer",
  platforms=["reed", "cvlibrary"],
  country="GB",
  location="London"
)
```

---

## Salary Text Parsing

Parse salary based on the country. Extract and normalize to annual integers in the local currency.

### UK Salary Parsing (GBP)

Extract salary from scraped text and normalize to annual GBP integers:

| Pattern | Example | Interpretation |
|---------|---------|----------------|
| Range with numbers | "£45,000 - £60,000" | min=45000, max=60000 |
| Range with k notation | "45k - 60k" | min=45000, max=60000 |
| "Up to" | "Up to £70,000" | min=59500 (85%), max=70000 |
| "From" | "From £65,000" | min=65000, max=69875 (107.5%) |
| Single value | "£55,000" | min=55000, max=55000 |
| Per day (contract) | "£500 - £600 per day" | Convert: multiply by 230 working days |
| "Competitive" | "Competitive salary" | salary_unlisted=true |
| "Negotiable" | "Negotiable" | salary_unlisted=true |
| Not mentioned | (no salary text found) | salary_unlisted=true |

**Parsing steps:**
1. Strip currency symbols (£), commas, whitespace
2. Detect "k"/"K" suffix and multiply by 1000
3. Detect "per day"/"daily" and multiply by 230
4. Detect "per hour"/"hourly" and multiply by 1840 (230 days * 8 hours)
5. Store both `salary_min` and `salary_max` as integers
6. If unparseable, mark as `salary_unlisted`

---

## Rate Limiting

- The MCP server handles rate limiting internally
- Pages per platform per query controlled by `max_pages_per_platform` INI setting (default 2)
- If a platform returns an error or blocks, do NOT retry — skip and move on
- Log all platform failures in the output notes column

---

## Result Extraction Template

For each scraped job listing, extract into this normalized structure:

```
{
  "title": "Job title as displayed",
  "company": "Company name",
  "location": "City name",
  "salary_text": "Original salary string",
  "salary_min": 75000,
  "salary_max": 85000,
  "salary_unlisted": false,
  "work_mode": "hybrid|remote|onsite",
  "url": "Direct link to job listing",
  "description": "First 200 words of description if available",
  "platform": "reed|cvlibrary|cwjobs|totaljobs|indeed|linkedin|adzuna",
  "posted_date": "2026-02-09"
}
```

**Work mode detection** from description text:
- Contains "remote" or "work from home" or "WFH" or "télétravail" or "full remote" → "remote"
- Contains "hybrid" or "X days in office" or "hybride" or "X jours au bureau" → "hybrid"
- Contains "on-site" or "office-based" or "sur site" or "présentiel" or no remote mention → "onsite"

---

### French Salary Parsing (EUR)

Extract salary from scraped text and normalize to annual EUR integers:

| Pattern | Example | Interpretation |
|---------|---------|----------------|
| Range with spaces | "45 000 € - 60 000 €" | min=45000, max=60000 |
| Range compact | "45 000 - 60 000 €/an" | min=45000, max=60000 |
| Range with k notation | "45K€ - 60K€" or "45k-60k€" | min=45000, max=60000 |
| "Jusqu'à" / "Up to" | "Jusqu'à 70 000 €" | min=59500 (85%), max=70000 |
| "À partir de" / "From" | "À partir de 65 000 €" | min=65000, max=69875 (107.5%) |
| Single value | "55 000 €" | min=55000, max=55000 |
| Monthly salary | "4 500 €/mois" or "4500€ brut/mois" | Multiply by 12 (annual=54000) |
| "Selon profil" | "Selon profil et expérience" | salary_unlisted=true |
| "À négocier" | "Salaire à négocier" | salary_unlisted=true |
| Not mentioned | (no salary text found) | salary_unlisted=true |

**French-specific parsing steps:**
1. Strip currency symbols (€), dots, and trailing text ("/an", "/mois", "brut", "net")
2. Replace space-separated thousands: `"45 000"` → `45000`
3. Detect comma as decimal separator: `"45 000,00"` → `45000`
4. Detect "k"/"K" suffix and multiply by 1000
5. Detect "/mois" or "mensuel" — multiply by 12 to annualize (if value < 10000, likely monthly)
6. Detect "net" — multiply by 1.28 to estimate gross (inverse of ~22% social contributions)
7. Store both `salary_min` and `salary_max` as integers
8. If unparseable, mark as `salary_unlisted`

---

## Company Reputation (Step 5.5)

```
mcp__deb-jobhunter__get_reputation(
  company_names=["Google", "Amazon", "Meta", "DeepMind", "Arm", ...],
  mode="light",
  country="GB"
)
```

**Always use `mode="light"`** (default). Only use `mode="deep"` if the user explicitly requests detailed insights — deep mode is slower and incurs +1 credit surcharge per call.

| Mode | Max companies per call | Notes |
|------|----------------------|-------|
| `light` | 15 | Fast, recommended for batch lookups |
| `deep` | 5 | Slower, richer insights, +1 credit |

For more than the per-mode limit, split into multiple calls.
