#!/usr/bin/env python3
"""Print Markdown release notes describing the current dataset snapshot."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import load_data  # noqa: E402


def main():
    d = load_data()
    r = d.get('date_range') or {}
    sources = len({c.get('source') for c in d['cases'] if c.get('source')})
    academic = sum(1 for c in d['cases'] if c.get('source_type') == 'academic')

    print('Snapshot of the AI Psychosis Watch dataset.\n')
    print(f"- **{d['total_cases']}** cases ({academic} academic) from **{sources}** sources")
    print(f"- Coverage: {r.get('from', '?')} to {r.get('to', '?')}")
    print(f"- Generated: {d.get('generated_at', '?')}\n")
    print('Attached: `data.json` (full dataset), `feed.xml`, `excluded.json` '
          '(items reviewed and rejected).\n')
    print('Entries document reports rather than verified diagnoses, and counts '
          'reflect media and research coverage rather than population '
          'incidence. Inclusion criteria, classification and limitations: '
          'https://aipsychosis.watch/methodology.html')


if __name__ == '__main__':
    main()
