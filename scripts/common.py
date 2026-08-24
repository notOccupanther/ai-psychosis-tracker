#!/usr/bin/env python3
"""Shared helpers for the AI Psychosis Watch pipeline.

data.json in the repo root is the source of truth. There is no database:
each run reads the existing cases, adds whatever is new, and writes the file
back. That keeps the whole pipeline reproducible from a git checkout.
"""

import hashlib
import json
import os
import re
import urllib.parse
from collections import Counter
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(ROOT, 'data.json')

SITE_URL = 'https://aipsychosis.watch'
USER_AGENT = 'AIPsychosisWatch/2.0 (+https://aipsychosis.watch)'

# Mirrors CAT_LABELS in index.html. Cases scraped before the rebuild may carry
# categories outside this set; those are preserved as-is and rendered by the
# frontend's title-case fallback.
CAT_LABELS = {
    'romantic_attachment': 'Romantic Attachment',
    'paranoia': 'Paranoia',
    'identity_confusion': 'Identity Confusion',
    'reality_distortion': 'Reality Distortion',
    'clinical': 'Clinical Cases',
    'media_coverage': 'Media Coverage',
    'other': 'Other',
}

SEVERITIES = ('critical', 'high', 'medium', 'low')


# ── data.json I/O ─────────────────────────────────────────────────────────────

def load_data():
    with open(DATA_PATH, encoding='utf-8') as f:
        return json.load(f)


def save_data(data):
    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write('\n')


def normalise_url(url):
    """Canonical form used for dedupe: no scheme, no www, no tracking params."""
    if not url:
        return ''
    url = url.strip()
    try:
        p = urllib.parse.urlsplit(url if '//' in url else '//' + url)
    except ValueError:
        return url.lower()
    host = (p.netloc or '').lower().removeprefix('www.')
    path = (p.path or '').rstrip('/')
    query = urllib.parse.urlencode(
        [(k, v) for k, v in urllib.parse.parse_qsl(p.query)
         if not k.lower().startswith(('utm_', 'fbclid', 'gclid', 'mc_'))]
    )
    return f'{host}{path}' + (f'?{query}' if query else '')


def make_id(url, source_type):
    digest = hashlib.sha256(normalise_url(url).encode()).hexdigest()[:12]
    # Matches the ID style already in data.json: academic/companion are
    # prefixed, media entries are a bare hex digest.
    return f'{source_type}_{digest}' if source_type in ('academic', 'companion') else digest


def existing_urls(data):
    return {normalise_url(c.get('url', '')) for c in data.get('cases', []) if c.get('url')}


# ── Aggregates consumed by index.html ─────────────────────────────────────────

def month_key(date_str):
    m = re.match(r'(\d{4})-(\d{2})', date_str or '')
    return f'{m.group(1)}-{m.group(2)}' if m else None


def recompute(data):
    """Rebuild every derived field from data['cases'] in place."""
    cases = data['cases']

    months = Counter(k for k in (month_key(c.get('date')) for c in cases) if k)
    labels = sorted(months)
    data['trend'] = {'labels': labels, 'values': [months[k] for k in labels]}

    cats = Counter(c.get('category') or 'other' for c in cases)
    ordered = cats.most_common()
    # 'keys' carries the raw slugs so consumers can map to colours; index.html
    # builds its own copy of this structure and relies on the same three fields.
    data['categories'] = {
        'keys': [k for k, _ in ordered],
        'labels': [CAT_LABELS.get(k, k) for k, _ in ordered],
        'values': [v for _, v in ordered],
    }

    sev = Counter(c.get('severity') or 'low' for c in cases)
    data['severity_counts'] = {k: sev.get(k, 0) for k in SEVERITIES if sev.get(k)}

    dates = sorted(c['date'] for c in cases if c.get('date'))
    # Keys match the schema already published in data.json; index.html does not
    # read this field, but external consumers of data.json may.
    data['date_range'] = {'from': dates[0], 'to': dates[-1]} if dates else {}

    data['total_cases'] = len(cases)
    data['generated_at'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    return data
