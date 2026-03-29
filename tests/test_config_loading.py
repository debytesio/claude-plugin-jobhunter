# -*- coding: utf-8 -*-

"""Tests for config loading and role keyword extraction."""

import os

from process_jobs import (
    _build_role_keywords, get_min_salary_for_role, load_config,
)

PLUGIN_ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))


def test_load_config_returns_dict():
    ini_path = os.path.join(PLUGIN_ROOT, 'config', 'job-hunter.ini')
    if not os.path.exists(ini_path):
        return  # Skip if config not available
    cfg_dict, cfg_parser = load_config(ini_path, country='gb')
    assert isinstance(cfg_dict, dict)
    assert 'country' in cfg_dict
    assert cfg_dict['country'] == 'gb'


def test_load_config_country_override():
    ini_path = os.path.join(PLUGIN_ROOT, 'config', 'job-hunter.ini')
    if not os.path.exists(ini_path):
        return
    cfg_dict, _ = load_config(ini_path, country='fr')
    assert cfg_dict['country'] == 'fr'


def test_build_role_keywords():
    expectations = {
        'target_roles': [
            {
                'title': 'AI Engineer',
                'search_keywords': ['AI Engineer', 'ML Engineer'],
            }
        ]
    }
    kw = _build_role_keywords(expectations)
    assert 'AI Engineer' in kw
    assert 'ai engineer' in kw['AI Engineer']['primary']
    assert 'ml engineer' in kw['AI Engineer']['primary']
    # Generic words excluded from related
    assert 'engineer' not in kw['AI Engineer']['related']
    assert 'ai' in kw['AI Engineer']['related']
    assert 'ml' in kw['AI Engineer']['related']


def test_min_salary_found():
    expectations = {
        'target_roles': [
            {'title': 'AI Engineer', 'min_salary': 80000},
            {'title': 'Data Analyst', 'min_salary': 50000},
        ]
    }
    assert get_min_salary_for_role('AI Engineer', expectations) == 80000
    assert get_min_salary_for_role('Data Analyst', expectations) == 50000


def test_min_salary_default_fallback():
    expectations = {'target_roles': []}
    assert get_min_salary_for_role('Unknown Role', expectations) == 70000
