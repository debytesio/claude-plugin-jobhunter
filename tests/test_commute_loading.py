# -*- coding: utf-8 -*-

"""Tests for commute data loading from MCP results."""

import json
import os
import tempfile

from process_jobs import _load_commute_overrides, COMMUTE_COSTS


def test_loads_routes_array():
    data = {
        'routes': [
            {
                'destination': 'London',
                'status': 'found',
                'one_way_fare': 25.0,
                'return_fare': 50.0,
                'duration_minutes': 120,
                'transport_mode': 'train',
                'overnight_needed': False,
            }
        ]
    }

    with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False) as f:
        json.dump(data, f)
        tmp_path = f.name

    try:
        _load_commute_overrides(tmp_path)
        assert 'london' in COMMUTE_COSTS
    finally:
        os.unlink(tmp_path)


def test_skips_not_found_routes():
    data = {
        'routes': [
            {'destination': 'Atlantis', 'status': 'not_found'},
            {
                'destination': 'Manchester',
                'status': 'found',
                'one_way_fare': 15.0,
                'return_fare': 30.0,
                'duration_minutes': 90,
                'transport_mode': 'train',
                'overnight_needed': False,
            }
        ]
    }

    with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False) as f:
        json.dump(data, f)
        tmp_path = f.name

    try:
        _load_commute_overrides(tmp_path)
        assert 'atlantis' not in COMMUTE_COSTS
        assert 'manchester' in COMMUTE_COSTS
    finally:
        os.unlink(tmp_path)
