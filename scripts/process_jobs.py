#!/usr/bin/env python3
"""Process scraped job listings: deduplicate, score, calculate financial viability, export Excel.

Usage:
    python process_jobs.py --raw RAW_JSON --expectations EXPECTATIONS_JSON --config INI_FILE [options]

Options:
    --ukvi-data JSON    UKVI sponsor data from DEB Cloud MCP (preferred)
    --agencies JSON     Agency list from DEB Cloud MCP
    --ukvi CSV          UKVI sponsor CSV (fallback if --ukvi-data not provided)
    --output-dir DIR    Output directory

Requires: _jh_core compiled C++ module for core algorithms.
"""

import argparse
import configparser
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import _jh_core
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side, numbers
from openpyxl.utils import get_column_letter


# ── Operational defaults (overridden by INI) ──
DEFAULTS = {
    "hybrid_days_per_week": 2,
    "weeks_per_month": 4.33,
    "food_daily": 17.50,
}

# ── Commute cost tables (populated from country INI) ──
COMMUTE_COSTS = {}
LOCAL_TRANSPORT = {}
ACCOMMODATION = {}
OVERNIGHT_NEEDED = {}

# ── Currency formatting per country ──
CURRENCY_FORMATS = {
    "gb": {"symbol": "GBP", "fmt": "GBP {amount:,.0f}"},
    "fr": {"symbol": "EUR", "fmt": "EUR {amount:,.0f}"},
}


# ═══════════════════════════════════════════════════════════════════
# Data loading (I/O only — no algorithms)
# ═══════════════════════════════════════════════════════════════════

def _load_agency_data(country="gb", agencies_path=None):
    """Load known agencies, keywords, and exceptions.

    If agencies_path is provided, loads MCP-provided agency data (from DEB Cloud).
    Otherwise falls back to bundled JSON data files.
    """
    if agencies_path and Path(agencies_path).exists():
        with open(agencies_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            agencies = {item["name"].lower() for item in data if "name" in item}
            keywords = []
            exceptions = []
            for item in data:
                keywords.extend(item.get("keywords", []))
            return agencies, keywords, exceptions
        agencies = {s.lower() for s in data.get("agencies", [])}
        return agencies, data.get("keywords", []), data.get("keyword_exceptions", [])

    filename = f"known-agencies-{country}.json" if country != "gb" else "known-agencies.json"
    agency_json = Path(__file__).resolve().parent.parent / "data" / filename
    if agency_json.exists():
        with open(agency_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        agencies = {s.lower() for s in data.get("agencies", [])}
        keywords = data.get("keywords", [])
        exceptions = data.get("keyword_exceptions", [])
    else:
        agencies = set()
        keywords = []
        exceptions = []
    return agencies, keywords, exceptions


KNOWN_AGENCIES, AGENCY_KEYWORDS, AGENCY_KEYWORD_EXCEPTIONS = _load_agency_data()


# ═══════════════════════════════════════════════════════════════════
# Resume text extraction (for .docx/.doc formats)
# ═══════════════════════════════════════════════════════════════════

def extract_resume_text(resume_path, output_dir=None):
    """Extract plain text from a resume file for LLM consumption.

    Supports: .tex, .pdf, .md, .txt (pass-through), .docx (python-docx), .doc (PowerShell COM).
    Returns the path to a readable text file.
    """
    path = Path(resume_path)
    ext = path.suffix.lower()
    if not path.exists():
        print(f"ERROR: Resume file not found: {resume_path}", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(output_dir) if output_dir else path.parent

    if ext in (".txt", ".md", ".tex"):
        return str(path)

    if ext == ".pdf":
        try:
            import pymupdf
            doc = pymupdf.open(str(path))
            text = "\n\n".join(page.get_text() for page in doc)
            out_path = out_dir / f"{path.stem}-extracted.txt"
            out_path.write_text(text, encoding="utf-8")
            print(f"Extracted PDF text -> {out_path}")
            return str(out_path)
        except ImportError:
            print("ERROR: pymupdf not installed. Run: pip install pymupdf", file=sys.stderr)
            sys.exit(1)

    if ext == ".docx":
        try:
            from docx import Document
            doc = Document(str(path))
            text = "\n".join(p.text for p in doc.paragraphs)
            out_path = out_dir / f"{path.stem}-extracted.txt"
            out_path.write_text(text, encoding="utf-8")
            print(f"Extracted .docx text -> {out_path}")
            return str(out_path)
        except ImportError:
            print("ERROR: python-docx not installed. Run: pip install python-docx", file=sys.stderr)
            sys.exit(1)

    if ext == ".doc":
        import subprocess
        out_path = out_dir / f"{path.stem}-extracted.txt"
        ps_script = (
            f'$w=New-Object -ComObject Word.Application;$w.Visible=$false;'
            f'$d=$w.Documents.Open("{path.resolve()}");'
            f'$d.SaveAs("{out_path.resolve()}",2);$d.Close();$w.Quit()'
        )
        try:
            result = subprocess.run(
                ['powershell', '-Command', ps_script],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0 and out_path.exists():
                print(f"Extracted .doc via PowerShell COM -> {out_path}")
                return str(out_path)
            else:
                print(f"ERROR: PowerShell COM extraction failed: {result.stderr}", file=sys.stderr)
                sys.exit(1)
        except FileNotFoundError:
            print("ERROR: PowerShell not available. Cannot convert .doc files.", file=sys.stderr)
            sys.exit(1)
        except subprocess.TimeoutExpired:
            print("ERROR: PowerShell COM extraction timed out.", file=sys.stderr)
            sys.exit(1)

    print(f"ERROR: Unsupported resume format: {ext}", file=sys.stderr)
    print("Supported formats: .tex .pdf .docx .doc .txt .md", file=sys.stderr)
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════
# Company reputation cache management (I/O only)
# ═══════════════════════════════════════════════════════════════════

REPUTATION_CACHE_TTL_DAYS = 90


def _reputation_cache_path(country="gb"):
    """Return path to the persistent reputation cache file for a country."""
    return Path(__file__).resolve().parent.parent / "data" / f"company-reputation-cache-{country}.json"


def load_reputation_cache(country="gb"):
    """Load the persistent reputation cache from disk, filtering expired entries."""
    cache_path = _reputation_cache_path(country)
    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=REPUTATION_CACHE_TTL_DAYS)).strftime("%Y-%m-%d")
        valid = {k: v for k, v in cache.items() if v.get("scraped_date", "") >= cutoff}
        return valid
    return {}


def save_reputation_cache(country, new_data, merge=True):
    """Save reputation data to the persistent cache file."""
    cache_path = _reputation_cache_path(country)
    existing = {}
    if merge and cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    existing.update(new_data)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(existing)} entries to reputation cache: {cache_path}")
    return str(cache_path)


def export_cache_snapshot(country, output_dir):
    """Export current valid cache entries to a snapshot file for the LLM agent."""
    cache = load_reputation_cache(country)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    snapshot_path = Path(output_dir) / "reputation-cache-snapshot.json"
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    print(f"Exported {len(cache)} cached reputation entries to {snapshot_path}")
    return str(snapshot_path)


def import_reputation_data(country, data_path):
    """Import newly scraped reputation data and merge into persistent cache."""
    with open(data_path, "r", encoding="utf-8") as f:
        new_data = json.load(f)
    cache_path = save_reputation_cache(country, new_data, merge=True)
    print(f"Merged {len(new_data)} new reputation entries into cache at {cache_path}")
    return cache_path


# ═══════════════════════════════════════════════════════════════════
# Configuration loading
# ═══════════════════════════════════════════════════════════════════

def load_config(ini_path, country="gb"):
    """Load shared INI + country-specific INI. Returns (dict, ConfigParser)."""
    cfg = configparser.ConfigParser()
    cfg.read(ini_path, encoding="utf-8")

    country_ini = Path(ini_path).parent / f"country-{country}.ini"
    if country_ini.exists():
        cfg.read(str(country_ini), encoding="utf-8")

    d = dict(DEFAULTS)
    d["country"] = country

    if cfg.has_section("tax"):
        for key in cfg.options("tax"):
            try:
                d[f"tax_{key}"] = cfg.getfloat("tax", key)
            except ValueError:
                d[f"tax_{key}"] = cfg.get("tax", key)

    if cfg.has_section("social"):
        for key in cfg.options("social"):
            try:
                d[f"social_{key}"] = cfg.getfloat("social", key)
            except ValueError:
                d[f"social_{key}"] = cfg.get("social", key)

    if cfg.has_section("commute_costs"):
        for k, v in cfg.items("commute_costs"):
            COMMUTE_COSTS[k] = float(v)
    if cfg.has_section("local_transport"):
        for k, v in cfg.items("local_transport"):
            LOCAL_TRANSPORT[k] = float(v)
    if cfg.has_section("accommodation_per_night"):
        for k, v in cfg.items("accommodation_per_night"):
            ACCOMMODATION[k] = float(v)
    if cfg.has_section("overnight_needed"):
        for k, v in cfg.items("overnight_needed"):
            OVERNIGHT_NEEDED[k] = v.strip() == "1"
    if cfg.has_section("food_daily"):
        d["food_daily"] = cfg.getfloat("food_daily", "default", fallback=d["food_daily"])

    if cfg.has_section("visa"):
        for key in cfg.options("visa"):
            try:
                d[f"visa_{key}"] = cfg.getfloat("visa", key)
            except ValueError:
                d[f"visa_{key}"] = cfg.get("visa", key)

    return d, cfg


def load_candidate_skills(expectations, cfg_parser=None):
    """Load candidate skills from expectations JSON, fallback to INI [candidate_skills]."""
    skills = set()
    skill_data = expectations.get("candidate", {}).get("skills", {})
    if skill_data:
        for category in skill_data.values():
            if isinstance(category, list):
                skills.update(s.strip().lower() for s in category if s.strip())
    elif cfg_parser and cfg_parser.has_section("candidate_skills"):
        for _, val in cfg_parser.items("candidate_skills"):
            skills.update(s.strip().lower() for s in val.split(";") if s.strip())
    return skills


def load_ukvi_sponsors(csv_path):
    """Load UKVI Skilled Worker sponsor list from CSV into a lookup dict."""
    sponsors = {}
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            org = row.get("Organisation Name", "").strip()
            route = row.get("Route", "").strip()
            rating = row.get("Type & Rating", "").strip()
            if "Skilled Worker" in route:
                key = _jh_core.normalize_company(org)
                if key:
                    sponsors[key] = {
                        "org_name": org,
                        "route": route,
                        "rating": rating,
                    }
    return sponsors


def load_ukvi_data(json_path):
    """Load UKVI sponsor data from MCP-provided JSON (DEB Cloud).

    MCP returns: {"Company Name": {"is_sponsor": true, "licenses": [...]}}
    Converts to: {normalized_name: {org_name, route, rating}}
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    sponsors = {}
    for company_name, info in data.items():
        if not info.get("is_sponsor"):
            continue
        licenses = info.get("licenses", [])
        for lic in licenses:
            route = lic.get("route", "")
            if "Skilled Worker" in route:
                key = _jh_core.normalize_company(company_name)
                if key:
                    sponsors[key] = {
                        "org_name": company_name,
                        "route": route,
                        "rating": lic.get("type_rating", ""),
                    }
                break
    return sponsors


def _build_role_keywords(expectations):
    """Build role keyword sets from expectations JSON.

    Returns dict: {role_title: {"primary": [...], "related": [...]}}
    """
    generic_words = {
        "senior", "junior", "lead", "principal", "staff", "head",
        "director", "manager", "engineer", "developer", "architect",
        "consultant", "analyst", "specialist", "associate", "intern",
        "team", "of", "the", "and", "a", "an", "in", "for",
    }
    role_kw = {}
    for role in expectations.get("target_roles", []):
        title = role["title"]
        primary = [title.lower().strip()]
        for kw in role.get("search_keywords", []):
            primary.append(kw.lower().strip())
        related = set()
        for kw in primary:
            for word in kw.split():
                if word not in generic_words and len(word) >= 2:
                    related.add(word)
        role_kw[title] = {"primary": primary, "related": sorted(related)}
    return role_kw


def get_min_salary_for_role(target_role, expectations):
    """Get minimum target salary for a role from expectations."""
    for role in expectations.get("target_roles", []):
        if role["title"] == target_role:
            return role.get("min_salary", 70000)
    return 70000


def parse_academic_grade_salary(salary_text, cfg_parser):
    """Parse 'Grade X' salary patterns from academic job listings."""
    import re
    if not salary_text or not cfg_parser or not cfg_parser.has_section("academic_salary_grades"):
        return None, None

    grade_match = re.search(r'grade\s*(\d+)(?:\s*/\s*(\d+))?', salary_text, re.IGNORECASE)
    if grade_match:
        grade_low = int(grade_match.group(1))
        grade_high = int(grade_match.group(2)) if grade_match.group(2) else grade_low
        try:
            sal_min = cfg_parser.getfloat("academic_salary_grades", f"grade_{grade_low}_min")
            sal_max = cfg_parser.getfloat("academic_salary_grades", f"grade_{grade_high}_max")
            return int(sal_min), int(sal_max)
        except (configparser.NoOptionError, ValueError):
            pass

    if re.search(r'\bprofessor\b', salary_text, re.IGNORECASE):
        try:
            sal_min = cfg_parser.getfloat("academic_salary_grades", "professor_min")
            sal_max = cfg_parser.getfloat("academic_salary_grades", "professor_max")
            return int(sal_min), int(sal_max)
        except (configparser.NoOptionError, ValueError):
            pass

    return None, None


# ═══════════════════════════════════════════════════════════════════
# Excel output
# ═══════════════════════════════════════════════════════════════════

# Styles
HEADER_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
HEADER_FILL = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
HEADER_ALIGNMENT = Alignment(horizontal="center", vertical="center", wrap_text=True)

DATA_FONT = Font(name="Calibri", size=10)
VIABLE_TRUE_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
VIABLE_FALSE_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
SPONSOR_TRUE_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
SPONSOR_UNKNOWN_FILL = PatternFill(start_color="FFE699", end_color="FFE699", fill_type="solid")
AGENCY_TRUE_FILL = PatternFill(start_color="FFE699", end_color="FFE699", fill_type="solid")
AGENCY_FALSE_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
RATING_HIGH_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
RATING_MED_FILL = PatternFill(start_color="FFE699", end_color="FFE699", fill_type="solid")
RATING_LOW_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
RATING_NA_FILL = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
ALT_ROW_FILL = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")

THIN_BORDER = Border(
    left=Side(style="thin", color="B4C6E7"),
    right=Side(style="thin", color="B4C6E7"),
    top=Side(style="thin", color="B4C6E7"),
    bottom=Side(style="thin", color="B4C6E7"),
)

COLUMNS = [
    ("rank", "Rank", 6),
    ("target_role", "Target Role", 22),
    ("region_group", "Region", 8),
    ("job_title", "Job Title", 42),
    ("job_url", "Job URL", 20),
    ("company", "Company", 24),
    ("is_visa_sponsor", "Visa Sponsor", 13),
    ("sponsor_route", "Visa Route", 14),
    ("is_agency", "Agency", 8),
    ("company_rating", "Rating", 7),
    ("rating_reviews", "Reviews", 8),
    ("rating_source", "Rat. Source", 10),
    ("location", "Location", 14),
    ("work_mode", "Mode", 8),
    ("salary_min", "Salary Min", 12),
    ("salary_max", "Salary Max", 12),
    ("salary_text", "Salary Text", 18),
    ("match_score", "Match", 8),
    ("role_match", "Role", 7),
    ("skill_match", "Skill", 7),
    ("seniority_match", "Senior.", 7),
    ("salary_match", "Sal.", 7),
    ("location_priority", "Loc.", 7),
    ("sponsor_match", "Spons.", 7),
    ("financial_score", "Financial", 10),
    ("composite_score", "Composite", 10),
    ("gross_annual", "Gross Annual", 13),
    ("net_monthly", "Net Monthly", 12),
    ("commute_monthly", "Commute/mo", 12),
    ("net_after_commute", "Net After", 12),
    ("viable", "Viable", 8),
    ("platform", "Platform", 11),
    ("posted_date", "Posted", 11),
    ("scraped_date", "Scraped", 11),
    ("notes", "Notes", 18),
]


def write_data_sheet(ws, jobs, sheet_title, exclude_cols=None):
    """Write a formatted data sheet with job listings."""
    cols = [(k, l, w) for k, l, w in COLUMNS if k not in (exclude_cols or set())]
    for col_idx, (key, label, width) in enumerate(cols, 1):
        cell = ws.cell(row=1, column=col_idx, value=label)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGNMENT
        cell.border = THIN_BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    currency_cols = {"salary_min", "salary_max", "gross_annual", "net_monthly",
                     "commute_monthly", "net_after_commute"}
    score_cols = {"match_score", "role_match", "skill_match", "seniority_match",
                  "salary_match", "location_priority", "sponsor_match",
                  "financial_score", "composite_score"}

    for row_idx, job in enumerate(jobs, 2):
        is_alt = row_idx % 2 == 0
        for col_idx, (key, label, width) in enumerate(cols, 1):
            val = job.get(key, "")
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.font = DATA_FONT
            cell.border = THIN_BORDER

            if key in currency_cols and isinstance(val, (int, float)) and val:
                cell.number_format = '#,##0'
            elif key in score_cols and isinstance(val, (int, float)):
                cell.number_format = '0.0'

            if key == "viable":
                if val == "TRUE":
                    cell.fill = VIABLE_TRUE_FILL
                elif val == "FALSE":
                    cell.fill = VIABLE_FALSE_FILL
                elif is_alt:
                    cell.fill = ALT_ROW_FILL
            elif key == "is_visa_sponsor":
                if val == "TRUE":
                    cell.fill = SPONSOR_TRUE_FILL
                elif val == "UNKNOWN":
                    cell.fill = SPONSOR_UNKNOWN_FILL
                elif is_alt:
                    cell.fill = ALT_ROW_FILL
            elif key == "is_agency":
                if val == "TRUE":
                    cell.fill = AGENCY_TRUE_FILL
                elif val == "FALSE":
                    cell.fill = AGENCY_FALSE_FILL
                elif is_alt:
                    cell.fill = ALT_ROW_FILL
            elif key == "company_rating":
                if isinstance(val, (int, float)) and val is not None:
                    cell.number_format = '0.0'
                    if val >= 4.0:
                        cell.fill = RATING_HIGH_FILL
                    elif val >= 3.0:
                        cell.fill = RATING_MED_FILL
                    else:
                        cell.fill = RATING_LOW_FILL
                else:
                    cell.fill = RATING_NA_FILL
                    cell.value = "N/A"
            elif key == "rating_source":
                if not val or val == "not_found":
                    cell.fill = RATING_NA_FILL
                    cell.value = "N/A"
                elif is_alt:
                    cell.fill = ALT_ROW_FILL
            elif key == "rating_reviews":
                if isinstance(val, (int, float)) and val:
                    cell.number_format = '#,##0'
                elif is_alt:
                    cell.fill = ALT_ROW_FILL
            elif key == "job_url" and val:
                cell.font = Font(name="Calibri", size=10, color="0563C1", underline="single")
                cell.hyperlink = val
                cell.value = "Link"
            elif is_alt:
                cell.fill = ALT_ROW_FILL

            if key in ("rank", "work_mode", "viable", "is_visa_sponsor", "is_agency",
                       "company_rating", "rating_reviews", "rating_source",
                       "platform", "posted_date", "scraped_date") or key in score_cols or key in currency_cols:
                cell.alignment = Alignment(horizontal="center")

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{len(jobs)+1}"


def write_summary_sheet(ws, stats):
    """Write summary statistics sheet."""
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 50

    title_font = Font(name="Calibri", bold=True, size=14, color="2F5496")
    section_font = Font(name="Calibri", bold=True, size=11, color="2F5496")
    label_font = Font(name="Calibri", bold=True, size=10)
    value_font = Font(name="Calibri", size=10)

    row = 1
    ws.cell(row=row, column=1, value="Job Search Summary").font = title_font
    row += 2

    ws.cell(row=row, column=1, value="Search Statistics").font = section_font
    row += 1
    for label, value in [
        ("Search Date", stats["search_date"]),
        ("Expectations File", stats["expectations_file"]),
        ("Total Scraped", stats["total_scraped"]),
        ("After Deduplication", stats["total_dedup"]),
        ("After Scoring (match >= 30)", stats["total_matched"]),
        ("Financially Viable", stats["total_viable"]),
        ("Platforms Used", stats["platforms_used"]),
        ("Platforms Failed", stats.get("platforms_failed", "none")),
    ]:
        ws.cell(row=row, column=1, value=label).font = label_font
        ws.cell(row=row, column=2, value=value).font = value_font
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="Results Breakdown").font = section_font
    row += 1
    for label, value in [
        ("P1 Jobs (Income Priority)", stats["p1_count"]),
        ("P2 Jobs (Commute Priority)", stats["p2_count"]),
    ]:
        ws.cell(row=row, column=1, value=label).font = label_font
        ws.cell(row=row, column=2, value=value).font = value_font
        row += 1

    if "role_counts" in stats:
        row += 1
        ws.cell(row=row, column=1, value="Per Role (in tabs)").font = section_font
        row += 1
        for role, count in stats["role_counts"].items():
            ws.cell(row=row, column=1, value=f"  {role}").font = label_font
            ws.cell(row=row, column=2, value=count).font = value_font
            row += 1

    if "city_counts" in stats:
        row += 1
        ws.cell(row=row, column=1, value="Per City (in output)").font = section_font
        row += 1
        for city, count in sorted(stats["city_counts"].items()):
            ws.cell(row=row, column=1, value=f"  {city}").font = label_font
            ws.cell(row=row, column=2, value=count).font = value_font
            row += 1

    row += 1
    ws.cell(row=row, column=1, value="Financial Parameters").font = section_font
    row += 1
    for label, value in [
        ("Current Net Monthly", stats.get("current_net_monthly", "N/A")),
        ("Improvement Threshold", f"{stats.get('improvement_pct', 10)}%"),
        ("Target Net Monthly", stats.get("target_net_monthly", "N/A")),
        ("Visa Sponsorship Required", stats.get("requires_visa", "N/A")),
    ]:
        ws.cell(row=row, column=1, value=label).font = label_font
        ws.cell(row=row, column=2, value=value).font = value_font
        row += 1

    if "reputation_stats" in stats:
        row += 1
        ws.cell(row=row, column=1, value="Company Reputation").font = section_font
        row += 1
        rep = stats["reputation_stats"]
        for label, value in [
            ("Companies with rating", rep.get("with_rating", 0)),
            ("Companies without rating", rep.get("without_rating", 0)),
            ("Average company rating", f"{rep.get('avg_rating', 0):.1f} / 5.0"),
            ("Rating source", rep.get("primary_source", "N/A")),
        ]:
            ws.cell(row=row, column=1, value=label).font = label_font
            ws.cell(row=row, column=2, value=value).font = value_font
            row += 1


# ═══════════════════════════════════════════════════════════════════
# Excel generation
# ═══════════════════════════════════════════════════════════════════

def _generate_excel(scored_jobs, expectations, output_dir, expectations_path="",
                    total_scraped=None, total_dedup=None):
    """Generate Excel workbook from scored+financial-computed job list."""
    results_per_group = expectations.get("preferences", {}).get("results_per_group", 20)
    current_net = expectations.get("current_situation", {}).get("net_monthly_take_home", 0)
    improvement_pct = expectations.get("preferences", {}).get("improvement_threshold_pct", 10)
    requires_visa = expectations.get("visa", {}).get("requires_visa", False)
    country = expectations.get("country", "gb")
    ccy = CURRENCY_FORMATS.get(country, CURRENCY_FORMATS["gb"])["symbol"]

    def cap_per_city(jobs_list, limit):
        city_counts = {}
        result = []
        for j in jobs_list:
            city_key = j["location"].lower().split(",")[0].strip()
            city_counts[city_key] = city_counts.get(city_key, 0) + 1
            if city_counts[city_key] <= limit:
                result.append(j)
        return result

    role_order = [r["title"] for r in sorted(expectations.get("target_roles", []),
                                             key=lambda r: r.get("priority", 99))]
    role_jobs = {}
    for role in role_order:
        role_list = [j for j in scored_jobs if j.get("target_role") == role]
        role_list.sort(key=lambda x: (0 if x["region_group"] == "P1" else 1, -x["composite_score"]))
        role_list = cap_per_city(role_list, results_per_group)
        for i, j in enumerate(role_list, 1):
            j["rank"] = i
        role_jobs[role] = role_list

    now = datetime.now()
    filename = f"jobs-{now.strftime('%Y-%m-%d_%H%M%S')}.xlsx"
    output_path = Path(output_dir) / filename

    wb = Workbook()
    first_sheet = True
    for role in role_order:
        if first_sheet:
            ws = wb.active
            ws.title = role
            first_sheet = False
        else:
            ws = wb.create_sheet(role)
        write_data_sheet(ws, role_jobs.get(role, []), role, exclude_cols={"target_role"})

    ws_all = wb.create_sheet("All Results")
    all_sorted = sorted([dict(j) for j in scored_jobs], key=lambda x: -x["composite_score"])
    for i, j in enumerate(all_sorted, 1):
        j["rank"] = i
    write_data_sheet(ws_all, all_sorted, "All Results")

    ws_summary = wb.create_sheet("Summary")
    total_viable = sum(1 for j in scored_jobs if j.get("viable") == "TRUE")
    all_platforms = set()
    for j in scored_jobs:
        for p in j.get("platform", "").split(","):
            if p.strip():
                all_platforms.add(p.strip())
    platforms = ",".join(sorted(all_platforms))
    target_net = round(current_net * (1 + improvement_pct / 100), 2) if current_net else "N/A"

    city_counts = {}
    for role_list in role_jobs.values():
        for j in role_list:
            city_key = j["location"].split(",")[0].strip()
            city_counts[city_key] = city_counts.get(city_key, 0) + 1

    role_counts = {role: len(jlist) for role, jlist in role_jobs.items()}

    rated_jobs = [j for j in scored_jobs if isinstance(j.get("company_rating"), (int, float))]
    summary_stats = {
        "search_date": now.strftime("%Y-%m-%d %H:%M:%S"),
        "expectations_file": str(expectations_path),
        "total_scraped": total_scraped if total_scraped is not None else len(scored_jobs),
        "total_dedup": total_dedup if total_dedup is not None else len(scored_jobs),
        "total_matched": len(scored_jobs),
        "total_viable": total_viable,
        "platforms_used": platforms,
        "platforms_failed": "",
        "p1_count": sum(1 for j in scored_jobs if j["region_group"] == "P1"),
        "p2_count": sum(1 for j in scored_jobs if j["region_group"] == "P2"),
        "current_net_monthly": f"{ccy} {current_net:,.2f}" if current_net else "N/A",
        "improvement_pct": improvement_pct,
        "target_net_monthly": f"{ccy} {target_net:,.2f}" if isinstance(target_net, float) else target_net,
        "requires_visa": "Yes" if requires_visa else "No",
        "city_counts": city_counts,
        "role_counts": role_counts,
    }
    if rated_jobs:
        sources = [j.get("rating_source", "") for j in rated_jobs]
        summary_stats["reputation_stats"] = {
            "with_rating": len(rated_jobs),
            "without_rating": len(scored_jobs) - len(rated_jobs),
            "avg_rating": sum(j["company_rating"] for j in rated_jobs) / len(rated_jobs),
            "primary_source": max(set(sources), key=sources.count) if sources else "N/A",
        }

    write_summary_sheet(ws_summary, summary_stats)

    wb.save(output_path)
    return str(output_path), role_jobs, role_order, role_counts


# ═══════════════════════════════════════════════════════════════════
# Pipeline stages
# ═══════════════════════════════════════════════════════════════════

def process_dedup(raw_path, output_dir):
    """Stage 1: Load raw jobs, deduplicate, save checkpoint-dedup.json."""
    with open(raw_path, "r", encoding="utf-8") as f:
        jobs = json.load(f)
    print(f"Loaded {len(jobs)} raw jobs")

    unique = list(_jh_core.dedup_jobs(jobs))
    print(f"After dedup: {len(unique)} unique jobs")

    checkpoint_dir = Path(output_dir)
    dedup_path = checkpoint_dir / "checkpoint-dedup.json"
    with open(dedup_path, "w", encoding="utf-8") as f:
        json.dump(unique, f, ensure_ascii=False, indent=2)
    print(f"Saved dedup checkpoint: {dedup_path}")
    return str(dedup_path)


def process_excel(
        scored_path, expectations_path, config_path,
        ukvi_path=None, output_dir=None,
        ukvi_data_path=None, agencies_path=None):
    """Stage 3: Financial calc + visa + agency detection + Excel from pre-scored jobs."""
    with open(expectations_path, "r", encoding="utf-8") as f:
        expectations = json.load(f)

    country = expectations.get("country", "gb")
    cfg, cfg_parser = load_config(config_path, country=country)
    ccy = CURRENCY_FORMATS.get(country, CURRENCY_FORMATS["gb"])["symbol"]

    # Load agency data and build C++ detector
    global KNOWN_AGENCIES, AGENCY_KEYWORDS, AGENCY_KEYWORD_EXCEPTIONS
    KNOWN_AGENCIES, AGENCY_KEYWORDS, AGENCY_KEYWORD_EXCEPTIONS = _load_agency_data(country, agencies_path)
    agency_detector = _jh_core.AgencyDetector(
        KNOWN_AGENCIES, list(AGENCY_KEYWORDS), list(AGENCY_KEYWORD_EXCEPTIONS))

    current_net = expectations.get("current_situation", {}).get("net_monthly_take_home", 0)
    improvement_pct = expectations.get("preferences", {}).get("improvement_threshold_pct", 10)
    requires_visa = expectations.get("visa", {}).get("requires_visa", False)
    hybrid_days = expectations.get("preferences", {}).get("hybrid_days_per_week", 2)
    cfg["hybrid_days_per_week"] = hybrid_days

    # Load UKVI sponsors and build C++ index
    ukvi_sponsors = {}
    if requires_visa and country == "gb":
        if ukvi_data_path and Path(ukvi_data_path).exists():
            print(f"Loading UKVI sponsor data from MCP: {ukvi_data_path}")
            ukvi_sponsors = load_ukvi_data(ukvi_data_path)
            print(f"Loaded {len(ukvi_sponsors)} Skilled Worker sponsors (DEB Cloud)")
        else:
            ukvi_csv = ukvi_path or expectations.get("visa", {}).get("ukvi_sponsor_list_path")
            if ukvi_csv and Path(ukvi_csv).exists():
                print(f"Loading UKVI sponsor list from CSV: {ukvi_csv}")
                ukvi_sponsors = load_ukvi_sponsors(ukvi_csv)
                print(f"Loaded {len(ukvi_sponsors)} Skilled Worker sponsors")
            else:
                print("WARNING: UKVI sponsor list not found, sponsor matching will return UNKNOWN")

    ukvi_index = _jh_core.UkviIndex(ukvi_sponsors)

    with open(scored_path, "r", encoding="utf-8") as f:
        scored_input = json.load(f)
    print(f"Loaded {len(scored_input)} pre-scored jobs")

    # Ensure target_role is assigned
    role_keywords = _build_role_keywords(expectations)
    default_role = expectations["target_roles"][0]["title"]
    for job in scored_input:
        if not job.get("target_role"):
            # Use C++ scoring to find best role match
            best_role = default_role
            best_score = 0
            title = job.get("title", job.get("job_title", ""))
            for role_title in role_keywords:
                sc = _jh_core.score_role_match(title, role_title, role_keywords)
                if sc > best_score:
                    best_score = sc
                    best_role = role_title
            job["target_role"] = best_role

    # Process all jobs via C++ multi-threaded batch processor
    final_jobs = list(_jh_core.process_batch(
        scored_input, cfg, ukvi_index, agency_detector,
        current_net, improvement_pct, country,
        COMMUTE_COSTS, LOCAL_TRANSPORT, ACCOMMODATION, OVERNIGHT_NEEDED))
    print(f"After filtering (match>=30): {len(final_jobs)} jobs")

    out_dir = output_dir or str(Path(expectations_path).parent)

    # Save final checkpoint
    checkpoint_dir = Path(out_dir)
    with open(checkpoint_dir / "checkpoint-final.json", "w", encoding="utf-8") as f:
        json.dump(final_jobs, f, ensure_ascii=False, indent=2)

    # Generate Excel
    xlsx_path, role_jobs, role_order, role_counts = _generate_excel(
        final_jobs, expectations, out_dir,
        expectations_path=expectations_path,
        total_scraped=len(scored_input),
        total_dedup=len(scored_input),
    )

    total_viable = sum(1 for j in final_jobs if j.get("viable") == "TRUE")
    print(f"\nExcel written to: {xlsx_path}")
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Pre-scored input:   {len(scored_input)}")
    print(f"After filtering:    {len(final_jobs)}")
    print(f"Financially viable: {total_viable}")
    for role in role_order:
        print(f"  {role:30s}: {role_counts.get(role, 0)} jobs")

    for role in role_order:
        top_list = role_jobs.get(role, [])[:10]
        if not top_list:
            continue
        print(f"\n{'-'*60}")
        print(f"TOP 10 {role}")
        print(f"{'-'*60}")
        for j in top_list:
            sal = f"{ccy} {j['gross_annual']:,}" if j["gross_annual"] else "Unlisted"
            sponsor = "[Y]" if j["is_visa_sponsor"] in ("TRUE", "ELIGIBLE") else "[?]"
            viable_str = "[Y]" if j.get("viable") == "TRUE" else ("[X]" if j.get("viable") == "FALSE" else "N/A")
            net_str = f"Net: {ccy} {j['net_after_commute']:,.0f}/mo" if j.get("net_after_commute") else ""
            line = (f"  #{j['rank']:2d} [{j['composite_score']:5.1f}] {j['job_title'][:40]:40s}"
                    f" | {j['company'][:18]:18s} | {j['location']:10s} | {sal:>12s}"
                    f" | {sponsor} | {viable_str} | {net_str}")
            print(line)

    return xlsx_path


def process_jobs(
        raw_path, expectations_path, config_path,
        ukvi_path=None, output_dir=None,
        ukvi_data_path=None, agencies_path=None):
    """Full pipeline (--stage all): dedup -> score -> financial -> Excel."""
    with open(expectations_path, "r", encoding="utf-8") as f:
        expectations = json.load(f)

    country = expectations.get("country", "gb")
    cfg, cfg_parser = load_config(config_path, country=country)
    ccy = CURRENCY_FORMATS.get(country, CURRENCY_FORMATS["gb"])["symbol"]

    # Load candidate skills
    candidate_skills = load_candidate_skills(expectations, cfg_parser)

    # Load agency data and build C++ detector
    global KNOWN_AGENCIES, AGENCY_KEYWORDS, AGENCY_KEYWORD_EXCEPTIONS
    KNOWN_AGENCIES, AGENCY_KEYWORDS, AGENCY_KEYWORD_EXCEPTIONS = _load_agency_data(country, agencies_path)
    agency_detector = _jh_core.AgencyDetector(
        KNOWN_AGENCIES, list(AGENCY_KEYWORDS), list(AGENCY_KEYWORD_EXCEPTIONS))

    sector = expectations.get("sector", "industry")
    current_net = expectations.get("current_situation", {}).get("net_monthly_take_home", 0)
    improvement_pct = expectations.get("preferences", {}).get("improvement_threshold_pct", 10)
    results_per_group = expectations.get("preferences", {}).get("results_per_group", 20)
    requires_visa = expectations.get("visa", {}).get("requires_visa", False)
    hybrid_days = expectations.get("preferences", {}).get("hybrid_days_per_week", 2)
    cfg["hybrid_days_per_week"] = hybrid_days

    # Load UKVI sponsors and build C++ index
    ukvi_sponsors = {}
    if requires_visa and country == "gb":
        if ukvi_data_path and Path(ukvi_data_path).exists():
            print(f"Loading UKVI sponsor data from MCP: {ukvi_data_path}")
            ukvi_sponsors = load_ukvi_data(ukvi_data_path)
            print(f"Loaded {len(ukvi_sponsors)} Skilled Worker sponsors (DEB Cloud)")
        else:
            ukvi_csv = ukvi_path or expectations.get("visa", {}).get("ukvi_sponsor_list_path")
            if ukvi_csv and Path(ukvi_csv).exists():
                print(f"Loading UKVI sponsor list from CSV: {ukvi_csv}")
                ukvi_sponsors = load_ukvi_sponsors(ukvi_csv)
                print(f"Loaded {len(ukvi_sponsors)} Skilled Worker sponsors")
            else:
                print("WARNING: UKVI sponsor list not found, sponsor matching will return UNKNOWN")

    ukvi_index = _jh_core.UkviIndex(ukvi_sponsors)

    # Load raw jobs
    with open(raw_path, "r", encoding="utf-8") as f:
        jobs = json.load(f)
    print(f"Loaded {len(jobs)} raw jobs")

    # Deduplicate via C++
    unique_jobs = list(_jh_core.dedup_jobs(jobs))
    print(f"After dedup: {len(unique_jobs)} unique jobs")

    # Save dedup checkpoint
    checkpoint_dir = Path(output_dir or Path(expectations_path).parent)
    dedup_path = checkpoint_dir / "checkpoint-dedup.json"
    with open(dedup_path, "w", encoding="utf-8") as f:
        json.dump(unique_jobs, f, ensure_ascii=False, indent=2)
    print(f"Saved dedup checkpoint: {dedup_path}")

    # Build role keywords and score each job via C++
    role_keywords = _build_role_keywords(expectations)
    default_role = expectations["target_roles"][0]["title"]

    scored_jobs = []
    for job in unique_jobs:
        title = job.get("title", "")

        # Assign target role via C++ scoring
        if job.get("target_role"):
            target_role = job["target_role"]
        else:
            best_role = default_role
            best_score = 0
            for role_title in role_keywords:
                sc = _jh_core.score_role_match(title, role_title, role_keywords)
                if sc > best_score:
                    best_score = sc
                    best_role = role_title
            target_role = best_role
        min_salary = get_min_salary_for_role(target_role, expectations)

        # Parse academic grade salary if needed
        if sector == "academia" and job.get("salary_unlisted", True):
            grade_min, grade_max = parse_academic_grade_salary(
                job.get("salary_text", ""), cfg_parser)
            if grade_min is not None:
                job["salary_min"] = grade_min
                job["salary_max"] = grade_max
                job["salary_unlisted"] = False
                job["salary_text"] = job.get("salary_text", "") + f" (Grade->{grade_min:,}-{grade_max:,})"

        # Score via C++
        role_sc = _jh_core.score_role_match(title, target_role, role_keywords)
        skill_sc = _jh_core.score_skill_match(title, job.get("description", ""), candidate_skills)
        seniority_sc = _jh_core.score_seniority(title, sector)
        salary_sc = _jh_core.score_salary(
            job.get("salary_min"), job.get("salary_max"),
            job.get("salary_unlisted", True), min_salary)
        location_sc = _jh_core.score_location(
            job.get("location", ""), job.get("work_mode", "hybrid"),
            job.get("region_group", "P1"))
        sponsor_sc = _jh_core.score_sponsor(
            job.get("company", ""), ukvi_index) if requires_visa else 0

        if sector == "academia":
            if requires_visa:
                match_score = (role_sc * 0.30 + skill_sc * 0.25 + seniority_sc * 0.10
                               + salary_sc * 0.10 + location_sc * 0.10 + sponsor_sc * 0.15)
            else:
                match_score = (role_sc * 0.35 + skill_sc * 0.30 + seniority_sc * 0.10
                               + salary_sc * 0.15 + location_sc * 0.10)
        else:
            if requires_visa:
                match_score = (role_sc * 0.25 + skill_sc * 0.20 + seniority_sc * 0.10
                               + salary_sc * 0.20 + location_sc * 0.10 + sponsor_sc * 0.15)
            else:
                match_score = (role_sc * 0.30 + skill_sc * 0.25 + seniority_sc * 0.15
                               + salary_sc * 0.20 + location_sc * 0.10)

        if match_score < 30:
            continue

        job["target_role"] = target_role
        job["match_score"] = round(match_score, 1)
        job["role_match"] = role_sc
        job["skill_match"] = skill_sc
        job["seniority_match"] = seniority_sc
        job["salary_match"] = salary_sc
        job["location_priority"] = location_sc
        job["sponsor_match"] = sponsor_sc
        scored_jobs.append(job)

    print(f"After scoring (match>=30): {len(scored_jobs)} jobs")

    # Save scored checkpoint
    scored_path = checkpoint_dir / "checkpoint-scored.json"
    with open(scored_path, "w", encoding="utf-8") as f:
        json.dump(scored_jobs, f, ensure_ascii=False, indent=2)
    print(f"Saved scored checkpoint: {scored_path}")

    # Process financial viability via C++ multi-threaded batch
    final_jobs = list(_jh_core.process_batch(
        scored_jobs, cfg, ukvi_index, agency_detector,
        current_net, improvement_pct, country,
        COMMUTE_COSTS, LOCAL_TRANSPORT, ACCOMMODATION, OVERNIGHT_NEEDED))

    # Sort, rank, generate Excel
    def cap_per_city(jobs_list, limit):
        city_counts = {}
        result = []
        for j in jobs_list:
            city_key = j["location"].lower().split(",")[0].strip()
            city_counts[city_key] = city_counts.get(city_key, 0) + 1
            if city_counts[city_key] <= limit:
                result.append(j)
        return result

    role_order = [r["title"] for r in sorted(expectations.get("target_roles", []),
                                             key=lambda r: r.get("priority", 99))]
    role_jobs = {}
    for role in role_order:
        role_list = [j for j in final_jobs if j.get("target_role") == role]
        role_list.sort(key=lambda x: (0 if x["region_group"] == "P1" else 1, -x["composite_score"]))
        role_list = cap_per_city(role_list, results_per_group)
        for i, j in enumerate(role_list, 1):
            j["rank"] = i
        role_jobs[role] = role_list

    now = datetime.now()
    filename = f"jobs-{now.strftime('%Y-%m-%d_%H%M%S')}.xlsx"
    output_path = checkpoint_dir / filename

    wb = Workbook()
    first_sheet = True
    for role in role_order:
        if first_sheet:
            ws = wb.active
            ws.title = role
            first_sheet = False
        else:
            ws = wb.create_sheet(role)
        write_data_sheet(ws, role_jobs.get(role, []), role, exclude_cols={"target_role"})

    ws_all = wb.create_sheet("All Results")
    all_sorted = sorted([dict(j) for j in final_jobs], key=lambda x: -x["composite_score"])
    for i, j in enumerate(all_sorted, 1):
        j["rank"] = i
    write_data_sheet(ws_all, all_sorted, "All Results")

    ws_summary = wb.create_sheet("Summary")
    total_viable = sum(1 for j in final_jobs if j.get("viable") == "TRUE")
    all_platforms = set()
    for j in final_jobs:
        for p in j.get("platform", "").split(","):
            if p.strip():
                all_platforms.add(p.strip())
    platforms = ",".join(sorted(all_platforms))
    target_net = round(current_net * (1 + improvement_pct / 100), 2) if current_net else "N/A"

    city_counts = {}
    for role_list in role_jobs.values():
        for j in role_list:
            city_key = j["location"].split(",")[0].strip()
            city_counts[city_key] = city_counts.get(city_key, 0) + 1

    role_counts = {role: len(jlist) for role, jlist in role_jobs.items()}

    rated_jobs_full = [j for j in final_jobs if isinstance(j.get("company_rating"), (int, float))]
    summary_stats_full = {
        "search_date": now.strftime("%Y-%m-%d %H:%M:%S"),
        "expectations_file": str(expectations_path),
        "total_scraped": len(jobs),
        "total_dedup": len(unique_jobs),
        "total_matched": len(final_jobs),
        "total_viable": total_viable,
        "platforms_used": platforms,
        "platforms_failed": "",
        "p1_count": sum(1 for j in final_jobs if j["region_group"] == "P1"),
        "p2_count": sum(1 for j in final_jobs if j["region_group"] == "P2"),
        "current_net_monthly": f"{ccy} {current_net:,.2f}" if current_net else "N/A",
        "improvement_pct": improvement_pct,
        "target_net_monthly": f"{ccy} {target_net:,.2f}" if isinstance(target_net, float) else target_net,
        "requires_visa": "Yes" if requires_visa else "No",
        "city_counts": city_counts,
        "role_counts": role_counts,
    }
    if rated_jobs_full:
        sources = [j.get("rating_source", "") for j in rated_jobs_full]
        summary_stats_full["reputation_stats"] = {
            "with_rating": len(rated_jobs_full),
            "without_rating": len(final_jobs) - len(rated_jobs_full),
            "avg_rating": sum(j["company_rating"] for j in rated_jobs_full) / len(rated_jobs_full),
            "primary_source": max(set(sources), key=sources.count) if sources else "N/A",
        }

    write_summary_sheet(ws_summary, summary_stats_full)
    wb.save(output_path)
    print(f"\nExcel written to: {output_path}")

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Total scraped:      {len(jobs)}")
    print(f"After dedup:        {len(unique_jobs)}")
    print(f"After scoring:      {len(final_jobs)}")
    print(f"Financially viable: {total_viable}")
    print(f"Platforms:          {platforms}")
    for role in role_order:
        print(f"  {role:30s}: {role_counts.get(role, 0)} jobs")

    for role in role_order:
        top_list = role_jobs.get(role, [])[:10]
        if not top_list:
            continue
        print(f"\n{'-'*60}")
        print(f"TOP 10 {role}")
        print(f"{'-'*60}")
        for j in top_list:
            sal = f"{ccy} {j['gross_annual']:,}" if j["gross_annual"] else "Unlisted"
            sponsor = "[Y]" if j["is_visa_sponsor"] in ("TRUE", "ELIGIBLE") else "[?]"
            viable_str = "[Y]" if j.get("viable") == "TRUE" else ("[X]" if j.get("viable") == "FALSE" else "N/A")
            net_str = f"Net: {ccy} {j['net_after_commute']:,.0f}/mo" if j.get("net_after_commute") else ""
            line = (f"  #{j['rank']:2d} [{j['composite_score']:5.1f}] {j['job_title'][:40]:40s}"
                    f" | {j['company'][:18]:18s} | {j['location']:10s} | {sal:>12s}"
                    f" | {sponsor} | {viable_str} | {net_str}")
            print(line)

    return str(output_path)


def main():
    parser = argparse.ArgumentParser(description="Process scraped job listings into Excel")
    parser.add_argument("--stage",
                        choices=["dedup", "excel", "all", "extract-resume",
                                 "load-reputation-cache", "save-reputation-cache"],
                        default="all",
                        help="Pipeline stage: dedup, excel, all, extract-resume, "
                             "load-reputation-cache, save-reputation-cache")
    parser.add_argument("--raw", help="Path to raw scraped jobs JSON (required for dedup/all)")
    parser.add_argument("--scored", help="Path to pre-scored jobs JSON (required for excel stage)")
    parser.add_argument("--resume", help="Path to resume file (for extract-resume stage)")
    parser.add_argument("--reputation-data", help="Path to new reputation data JSON (for save-reputation-cache)")
    parser.add_argument("--expectations", help="Path to expectations JSON")
    parser.add_argument("--config", help="Path to INI config")
    parser.add_argument("--ukvi", help="Path to UKVI sponsor CSV (fallback, overrides expectations JSON)")
    parser.add_argument("--ukvi-data", help="Path to MCP-provided UKVI sponsor JSON (from DEB Cloud)")
    parser.add_argument("--agencies", help="Path to MCP-provided agency list JSON (from DEB Cloud)")
    parser.add_argument("--output-dir", help="Output directory (defaults to expectations JSON dir)")
    args = parser.parse_args()

    output_dir = args.output_dir or (str(Path(args.expectations).parent) if args.expectations else ".")

    if args.stage == "extract-resume":
        if not args.resume:
            parser.error("--resume is required for --stage extract-resume")
        result_path = extract_resume_text(args.resume, output_dir)
        print(f"RESUME_TEXT_PATH={result_path}")

    elif args.stage == "load-reputation-cache":
        if not args.expectations:
            parser.error("--expectations is required for --stage load-reputation-cache")
        with open(args.expectations, "r", encoding="utf-8") as f:
            expectations = json.load(f)
        country = expectations.get("country", "gb")
        export_cache_snapshot(country, output_dir)

    elif args.stage == "save-reputation-cache":
        if not args.reputation_data:
            parser.error("--reputation-data is required for --stage save-reputation-cache")
        if not args.expectations:
            parser.error("--expectations is required for --stage save-reputation-cache")
        with open(args.expectations, "r", encoding="utf-8") as f:
            expectations = json.load(f)
        country = expectations.get("country", "gb")
        import_reputation_data(country, args.reputation_data)

    elif args.stage == "dedup":
        if not args.raw:
            parser.error("--raw is required for --stage dedup")
        process_dedup(args.raw, output_dir)

    elif args.stage == "excel":
        if not args.scored:
            parser.error("--scored is required for --stage excel")
        if not args.expectations or not args.config:
            parser.error("--expectations and --config are required for --stage excel")
        process_excel(args.scored, args.expectations, args.config, args.ukvi, output_dir,
                      ukvi_data_path=args.ukvi_data, agencies_path=args.agencies)

    else:  # all
        if not args.raw:
            parser.error("--raw is required for --stage all")
        if not args.expectations or not args.config:
            parser.error("--expectations and --config are required for --stage all")
        process_jobs(args.raw, args.expectations, args.config, args.ukvi, output_dir,
                     ukvi_data_path=args.ukvi_data, agencies_path=args.agencies)


if __name__ == "__main__":
    main()
