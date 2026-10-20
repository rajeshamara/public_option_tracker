"""Read the editable display thresholds without consulting brokerage data."""

import json
import math
from pathlib import Path
import re


RULES_PATH = Path(__file__).resolve().parents[1] / 'near-strike.json'
RULE_KEYS = {'$', '%', 'use'}
SYMBOL_PATTERN = re.compile(r'[A-Z0-9.$/-]{1,20}')


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _valid_distance(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def load_rules():
    """Return an all-or-nothing rules snapshot; reread edits on every call."""
    try:
        contents = RULES_PATH.read_text(encoding='utf-8-sig')
    except OSError:
        raise ValueError('Could not read near-strike.json. Check that the file exists and is readable.') from None
    except UnicodeError:
        raise ValueError('near-strike.json must contain valid UTF-8 JSON.') from None
    try:
        rules = json.loads(contents, object_pairs_hook=_unique_keys)
    except ValueError:
        raise ValueError('near-strike.json must contain valid JSON with unique keys.') from None
    if not isinstance(rules, dict) or 'default' not in rules:
        raise ValueError('near-strike.json must be an object containing a default rule.')
    normalized = {}
    for source_symbol, rule in rules.items():
        if source_symbol.lower() == 'default' and source_symbol != 'default':
            raise ValueError('near-strike.json must spell the default key in lowercase.')
        symbol = source_symbol if source_symbol == 'default' else source_symbol.upper()
        if symbol != 'default' and not SYMBOL_PATTERN.fullmatch(symbol):
            raise ValueError('near-strike.json symbol keys must be stock symbols, such as SPY or BRK/B.')
        if symbol in normalized:
            raise ValueError('near-strike.json must not contain duplicate stock symbols.')
        if not isinstance(rule, dict) or set(rule) != RULE_KEYS:
            raise ValueError('Each near-strike.json rule must contain exactly "$", "%", and "use".')
        if not all(_valid_distance(rule[key]) for key in ('$', '%')):
            raise ValueError('near-strike.json "$" and "%" values must be finite, nonnegative numbers.')
        if rule['use'] not in ('$', '%'):
            raise ValueError('near-strike.json "use" must be "$" or "%".')
        normalized[symbol] = rule
    return normalized
