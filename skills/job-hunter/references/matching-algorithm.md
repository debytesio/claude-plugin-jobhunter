# Matching Algorithm

Jobs are scored on 6 dimensions: role_match, skill_match,
seniority_match, salary_match, location_priority, sponsor_match.

Each dimension scores 0-100. Combined into weighted match_score:
- 0-30: Not relevant (discarded)
- 31-60: Potentially relevant
- 61-100: Highly relevant

Scoring mode is configured in job-hunter.ini:
- `local`: Local heuristic scoring (fast, no credits)
- `remote`: Server-side scoring via `score_jobs` MCP tool

Output per job:
{match_score, role_match, skill_match, seniority_match,
 salary_match, location_priority, sponsor_match}

Composite score (in excel stage):
composite_score = match_score × 0.60 + financial_score × 0.40
