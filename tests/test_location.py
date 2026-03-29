# -*- coding: utf-8 -*-

"""Tests for location normalization in process_jobs.py."""

from process_jobs import _normalize_location


def test_strips_country_suffix():
    assert _normalize_location(
        'London, England, United Kingdom') == 'London'


def test_strips_postcode():
    assert _normalize_location('London EC2A 2AP') == 'London'


def test_strips_county():
    assert _normalize_location('Oxford, Oxfordshire') == 'Oxford'


def test_greater_london_alias():
    assert _normalize_location('Greater London') == 'London'


def test_greater_manchester_alias():
    assert _normalize_location('Greater Manchester') == 'Manchester'


def test_area_suffix_stripped():
    assert _normalize_location('Manchester Area') == 'Manchester'


def test_city_of_london():
    assert _normalize_location('City of London') == 'London'


def test_empty_returns_empty():
    assert _normalize_location('') == ''
    assert _normalize_location(None) == ''


def test_simple_city_unchanged():
    assert _normalize_location('Birmingham') == 'Birmingham'
