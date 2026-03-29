# -*- coding: utf-8 -*-

"""Shared fixtures for plugin tests."""

import os
import sys
from types import ModuleType
from unittest.mock import MagicMock

# Add libs/ and scripts/ to path
plugin_root = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(plugin_root, 'libs'))
sys.path.insert(0, os.path.join(plugin_root, 'scripts'))

# Mock _jh_core before process_jobs imports it (C++ binary
# not available in CI). Must happen before any test imports.
if '_jh_core' not in sys.modules:
    mock_core = ModuleType('_jh_core')
    mock_core.dedup_jobs = MagicMock(return_value=[])
    mock_core.process_batch = MagicMock(return_value=[])
    sys.modules['_jh_core'] = mock_core
