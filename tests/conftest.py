# -*- coding: utf-8 -*-

"""Shared fixtures for plugin tests."""

import os
import sys

import pytest

# Add scripts/ to path for process_jobs imports
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'scripts'))
