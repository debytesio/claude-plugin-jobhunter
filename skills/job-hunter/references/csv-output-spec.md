# Output Specification — Excel (.xlsx)

## File Naming and Location

- **Path**: Same folder as the input expectations JSON file
- **Filename**: `jobs-YYYY-MM-DD_HHmmss.xlsx` (e.g., `jobs-2026-02-09_143022.xlsx`)
- **Format**: Excel workbook (.xlsx) via openpyxl

---

## Workbook Structure

The output workbook contains 4 sheets:

| Sheet | Name | Contents |
|-------|------|----------|
| 1 | P1 - Income Priority | Top N results for P1 cities, ranked by composite_score |
| 2 | P2 - Commute Priority | Top N results for P2 cities, ranked by composite_score |
| 3 | All Results | All scored results (no cap), ranked by composite_score |
| 4 | Summary | Search statistics, financial parameters, metadata |

---

## Column Definitions (34 columns — Sheets 1-3)

| # | Column Key | Header Label | Type | Description |
|---|-----------|-------------|------|-------------|
| 1 | `rank` | Rank | int | Rank within the sheet (1 = best) |
| 2 | `region_group` | Region | string | "P1" or "P2" |
| 3 | `job_title` | Job Title | string | Job title as scraped |
| 4 | `company` | Company | string | Company/employer name |
| 5 | `is_ukvi_sponsor` | UKVI Sponsor | string | "TRUE" / "UNKNOWN" |
| 6 | `sponsor_route` | Sponsor Route | string | e.g. "Skilled Worker" or blank |
| 7 | `company_rating` | Rating | float | Employee rating 0.0-5.0 (from Glassdoor/Indeed) |
| 8 | `rating_reviews` | Reviews | int | Number of employee reviews |
| 9 | `rating_source` | Rat. Source | string | Source: glassdoor, indeed, web, not_found |
| 10 | `is_agency` | Agency | string | "TRUE" / "FALSE" — recruitment agency flag |
| 11 | `location` | Location | string | Job location (city) |
| 12 | `work_mode` | Mode | string | "remote", "hybrid", or "onsite" |
| 13 | `salary_min` | Salary Min | int | Annual salary min (blank if unlisted) |
| 14 | `salary_max` | Salary Max | int | Annual salary max (blank if unlisted) |
| 15 | `salary_text` | Salary Text | string | Original salary text as scraped |
| 16 | `match_score` | Match | float | Overall match score (0-100, 1dp) |
| 17 | `role_match` | Role | float | Role alignment sub-score (0-100) |
| 18 | `skill_match` | Skill | float | Skill overlap sub-score (0-100) |
| 19 | `seniority_match` | Senior. | float | Seniority alignment sub-score (0-100) |
| 20 | `salary_match` | Sal. | float | Salary threshold sub-score (0-100) |
| 21 | `location_priority` | Loc. | float | Location priority sub-score (0-100) |
| 22 | `sponsor_match` | Spons. | float | UKVI sponsor sub-score (0-100) |
| 23 | `financial_score` | Financial | float | Financial viability score (0-100) |
| 24 | `composite_score` | Composite | float | Final ranking: match*0.6 + financial*0.4 |
| 25 | `gross_annual` | Gross Annual | int | Estimated gross annual salary |
| 26 | `net_monthly` | Net Monthly | float | Estimated net monthly take-home |
| 27 | `commute_monthly` | Commute/mo | float | Estimated monthly commute cost |
| 28 | `net_after_commute` | Net After | float | Net monthly after commute deduction |
| 29 | `viable` | Viable | string | "TRUE" / "FALSE" / blank |
| 30 | `platform` | Platform | string | Source: reed, cv-library, totaljobs, indeed, etc. |
| 31 | `job_url` | Job URL | hyperlink | Clickable link to listing |
| 32 | `posted_date` | Posted | string | ISO date (YYYY-MM-DD) |
| 33 | `scraped_date` | Scraped | string | ISO date (YYYY-MM-DD) |
| 34 | `notes` | Notes | string | Semicolon-separated flags |

---

## Excel Formatting

| Element | Style |
|---------|-------|
| Header row | Bold, white text, dark blue fill (#2F5496), centered, wrap text |
| Data font | Calibri 10pt |
| Alternating rows | Light blue fill (#D6E4F0) on even rows |
| Viable = TRUE | Green fill (#C6EFCE) |
| Viable = FALSE | Red fill (#FFC7CE) |
| UKVI Sponsor = TRUE | Green fill (#C6EFCE) |
| UKVI Sponsor = UNKNOWN | Yellow fill (#FFE699) |
| Rating >= 4.0 | Green fill (#C6EFCE) |
| Rating 3.0-3.9 | Yellow fill (#FFE699) |
| Rating < 3.0 | Red fill (#FFC7CE) |
| Rating N/A | Grey fill (#D9D9D9) |
| Currency columns | `#,##0` format |
| Score columns | `0.0` format |
| Job URL | Hyperlink (blue, underlined), display text "Link" |
| Freeze panes | Top row frozen |
| Auto-filter | Enabled on all data columns |
| Column widths | Auto-sized per column definition |

---

## Summary Sheet (Sheet 4)

Structured summary with sections:

**Search Statistics:**
- Search Date, Expectations File
- Total Scraped, After Dedup, After Scoring, Financially Viable
- Platforms Used, Platforms Failed

**Results Breakdown:**
- P1 count, P2 count, Total in Output

**Company Reputation:**
- Companies with rating, Companies without rating
- Average rating, Primary source (glassdoor/indeed)

**Financial Parameters:**
- Current Net Monthly, Improvement Threshold, Target Net Monthly
- Visa Sponsorship Required

---

## Notes Column Values

| Flag | Meaning |
|------|---------|
| `salary_unlisted` | No salary information found |
| `salary_estimated` | Salary inferred from partial info |
| `commute_estimated` | Commute cost used fallback values |
| `sponsor_partial_match` | UKVI match was fuzzy, not exact |
| `scrape_partial` | Description was partially scraped |
| `platform_fallback` | Used fallback scraping method |

---

## Sorting and Grouping

1. **P1 sheet**: sorted by `composite_score` descending, rank 1-N
2. **P2 sheet**: sorted by `composite_score` descending, rank 1-N
3. **All Results sheet**: all scored jobs merged, sorted by `composite_score` descending
4. Maximum `results_per_group` entries per P1/P2 sheet (default 20)
