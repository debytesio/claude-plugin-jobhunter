# -*- coding: utf-8 -*-

"""Tests for reputation cache load/save."""

import json
import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

from process_jobs import (
    load_reputation_cache, save_reputation_cache,
)


def test_load_nonexistent_returns_empty():
    with patch('process_jobs._reputation_cache_path') as mock_path:
        from pathlib import Path
        mock_path.return_value = Path('/nonexistent/path.json')
        result = load_reputation_cache('gb')
        assert result == {}


def test_load_filters_expired_entries():
    fresh_date = datetime.now().strftime('%Y-%m-%d')
    old_date = (datetime.now() - timedelta(days=100)).strftime(
        '%Y-%m-%d')
    cache_data = {
        'Fresh Corp': {'rating': 4.5, 'scraped_date': fresh_date},
        'Old Corp': {'rating': 3.0, 'scraped_date': old_date},
    }

    with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False) as f:
        json.dump(cache_data, f)
        tmp_path = f.name

    try:
        from pathlib import Path
        with patch('process_jobs._reputation_cache_path',
                   return_value=Path(tmp_path)):
            result = load_reputation_cache('gb')
            assert 'Fresh Corp' in result
            assert 'Old Corp' not in result
    finally:
        os.unlink(tmp_path)


def test_save_merges_existing():
    existing = {'Corp A': {'rating': 4.0, 'scraped_date': '2026-03-01'}}
    new_data = {'Corp B': {'rating': 3.5, 'scraped_date': '2026-03-15'}}

    with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False) as f:
        json.dump(existing, f)
        tmp_path = f.name

    try:
        from pathlib import Path
        with patch('process_jobs._reputation_cache_path',
                   return_value=Path(tmp_path)):
            save_reputation_cache('gb', new_data, merge=True)

        with open(tmp_path) as f:
            merged = json.load(f)
        assert 'Corp A' in merged
        assert 'Corp B' in merged
    finally:
        os.unlink(tmp_path)
