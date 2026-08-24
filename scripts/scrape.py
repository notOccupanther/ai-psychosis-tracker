#!/usr/bin/env python3
"""AI Psychosis Watch — weekly scraper.

Reads data.json, fetches candidates from PubMed, arXiv, Semantic Scholar and a
set of RSS feeds, drops anything already present or irrelevant, and writes
data.json back with recomputed aggregates.

Every source here is keyless except Brave, which is skipped unless
BRAVE_API_KEY is set. A single source failing is logged and never fatal: a
partial update beats a failed run.

    python scripts/scrape.py [--dry-run] [--days N]
"""

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from classify import guess_category, guess_severity, is_relevant  # noqa: E402
from common import (USER_AGENT, existing_urls, load_data, load_excluded,  # noqa: E402
                    make_id, normalise_url, recompute, save_data)

TIMEOUT = 20

PUBMED_QUERIES = [
    '(chatbot OR "artificial intelligence" OR "large language model") AND (psychosis OR delusion)',
    '"AI psychosis" OR "chatbot psychosis" OR "ChatGPT psychosis"',
    '("conversational agent" OR chatbot) AND ("mental health" OR psychiatric) AND (harm OR risk)',
    '("AI companion" OR "social chatbot") AND (attachment OR loneliness OR dependence)',
]

ARXIV_QUERIES = [
    'chatbot psychosis delusion',
    'large language model mental health harm',
    'AI companion parasocial attachment',
    'LLM sycophancy user wellbeing',
]

SEMANTIC_SCHOLAR_QUERIES = [
    'AI chatbot psychosis',
    'large language model delusion mental health',
    'AI companion emotional dependence',
]

# Mapped to publisher names rather than feed titles: the feeds announce
# themselves as things like "AI (artificial intelligence) | The Guardian", which
# is what ends up displayed next to each case on the site.
RSS_FEEDS = {
    'https://futurism.com/feed': 'Futurism',
    'https://www.psypost.org/feed/': 'PsyPost',
    'https://www.theguardian.com/technology/artificialintelligenceai/rss': 'The Guardian',
    'https://www.wired.com/feed/tag/ai/latest/rss': 'WIRED',
    'https://www.technologyreview.com/feed/': 'MIT Technology Review',
    'https://arstechnica.com/ai/feed/': 'Ars Technica',
    'https://www.404media.co/rss/': '404 Media',
    'https://techcrunch.com/category/artificial-intelligence/feed/': 'TechCrunch',
}

# Query-targeted news search, keyless. The general AI feeds above carry mostly
# unrelated industry news; these are what actually surface media cases, and are
# what the pre-2026 data was built from (its URLs point at news.google.com).
GOOGLE_NEWS_QUERIES = [
    '"AI psychosis"',
    '"chatbot psychosis" OR "ChatGPT psychosis"',
    'chatbot delusions mental health',
    '"AI companion" harm teen OR child',
    'chatbot linked suicide lawsuit',
    '"AI girlfriend" OR "AI boyfriend" relationship',
    'Character.AI OR Replika mental health',
    'chatbot encouraged delusions family',
]

BRAVE_QUERIES = [
    'AI psychosis chatbot delusion',
    'ChatGPT mental health crisis',
    'AI companion app harm',
]


def log(msg):
    print(msg, flush=True)


def fetch(url, headers=None, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def strip_html(text):
    """Entity-decode, remove markup, collapse whitespace.

    Feeds commonly double-encode: the description holds "&lt;p&gt;text&lt;/p&gt;"
    rather than "<p>text</p>", so a single tag-strip pass sees no tags and the
    markup ends up rendered as visible text on the site.
    """
    out = text or ''
    # Repeat rather than assume a fixed depth: feeds vary between one and two
    # layers of encoding, and a single pass leaves the markup visible.
    for _ in range(3):
        decoded = html.unescape(out)
        stripped = re.sub(r'<[^>]+>', ' ', decoded)
        if stripped == out:
            break
        out = stripped
    return re.sub(r'\s+', ' ', out).strip()


def tag(name, text):
    m = re.search(r'<' + name + r'(?:\s[^>]*)?>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</' + name + '>',
                  text, re.DOTALL)
    return m.group(1).strip() if m else ''


# ── PubMed ────────────────────────────────────────────────────────────────────

def scrape_pubmed(query, days):
    base = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils'
    params = urllib.parse.urlencode({
        'db': 'pubmed', 'term': query, 'retmax': 30,
        'retmode': 'json', 'sort': 'date', 'reldate': days, 'datetype': 'edat',
    })
    ids = json.loads(fetch(f'{base}/esearch.fcgi?{params}'))['esearchresult'].get('idlist', [])
    if not ids:
        return []

    fetch_params = urllib.parse.urlencode({
        'db': 'pubmed', 'id': ','.join(ids), 'retmode': 'xml',
    })
    root = ET.fromstring(fetch(f'{base}/efetch.fcgi?{fetch_params}'))

    out = []
    for art in root.findall('.//PubmedArticle'):
        title = ''.join(art.find('.//ArticleTitle').itertext()) if art.find('.//ArticleTitle') is not None else ''
        abstract = ' '.join(''.join(e.itertext()) for e in art.findall('.//AbstractText'))
        journal = art.findtext('.//Journal/Title') or 'PubMed'
        doi = next((e.text for e in art.findall('.//ArticleId')
                    if e.get('IdType') == 'doi'), None)
        pmid = art.findtext('.//PMID') or ''
        authors = ', '.join(
            f"{a.findtext('LastName') or ''} {a.findtext('Initials') or ''}".strip()
            for a in art.findall('.//Author')[:8]
        ).strip(', ')

        pd = art.find('.//PubDate')
        year = pd.findtext('Year') if pd is not None else None
        month = pd.findtext('Month') if pd is not None else None
        date = ''
        if year:
            months = {m: f'{i:02d}' for i, m in enumerate(
                ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 1)}
            date = f'{year}-{months.get((month or "")[:3], "01")}-01'

        out.append({
            'title': title, 'url': f'https://doi.org/{doi}' if doi else f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/',
            'date': date, 'source': 'PubMed', 'summary': abstract[:600],
            'abstract': abstract[:2000] or None, 'authors': authors or None,
            'doi': doi, 'venue': journal, 'source_type': 'academic',
        })
    return out


# ── arXiv ─────────────────────────────────────────────────────────────────────

def scrape_arxiv(query):
    params = urllib.parse.urlencode({
        'search_query': f'all:{query}', 'start': 0, 'max_results': 15,
        'sortBy': 'submittedDate', 'sortOrder': 'descending',
    })
    content = fetch(f'https://export.arxiv.org/api/query?{params}').decode('utf-8', 'replace')
    out = []
    for entry in re.findall(r'<entry>(.*?)</entry>', content, re.DOTALL):
        title = strip_html(tag('title', entry)).replace('\n', ' ')
        url = tag('id', entry).strip()
        summary = strip_html(tag('summary', entry)).replace('\n', ' ')
        if not title or not url:
            continue
        out.append({
            'title': title, 'url': url, 'date': tag('published', entry)[:10],
            'source': 'arXiv', 'summary': summary[:600], 'abstract': summary[:2000] or None,
            'authors': ', '.join(re.findall(r'<name>(.*?)</name>', entry)[:8]) or None,
            'venue': 'arXiv', 'source_type': 'academic',
        })
    return out


# ── Semantic Scholar ──────────────────────────────────────────────────────────

def scrape_semantic_scholar(query, days):
    params = urllib.parse.urlencode({
        'query': query, 'limit': 20,
        'fields': 'title,abstract,url,venue,publicationDate,authors,externalIds',
    })
    url = f'https://api.semanticscholar.org/graph/v1/paper/search?{params}'
    try:
        data = json.loads(fetch(url))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            log('  [rate limit] Semantic Scholar 429 — waiting 20s')
            time.sleep(20)
            data = json.loads(fetch(url))
        else:
            raise

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
    out = []
    for p in data.get('data', []):
        date = p.get('publicationDate') or ''
        if date and date < cutoff:
            continue
        link = p.get('url') or ''
        doi = (p.get('externalIds') or {}).get('DOI')
        abstract = p.get('abstract') or ''
        out.append({
            'title': p.get('title') or '', 'url': f'https://doi.org/{doi}' if doi else link,
            'date': date, 'source': 'Semantic Scholar', 'summary': abstract[:600],
            'abstract': abstract[:2000] or None,
            'authors': ', '.join(a.get('name', '') for a in (p.get('authors') or [])[:8]) or None,
            'doi': doi, 'venue': p.get('venue') or None, 'source_type': 'academic',
        })
    return out


# ── RSS ───────────────────────────────────────────────────────────────────────

def parse_date(s):
    if not s:
        return ''
    try:
        import email.utils
        return email.utils.parsedate_to_datetime(s).strftime('%Y-%m-%d')
    except Exception:
        m = re.search(r'(\d{4}-\d{2}-\d{2})', s)
        return m.group(1) if m else ''


def scrape_rss(feed_url, days, source_name=None):
    content = fetch(feed_url, {'Accept': 'application/rss+xml, application/xml, text/xml, */*'}).decode('utf-8', 'replace')
    feed_title = source_name or urllib.parse.urlsplit(feed_url).netloc.removeprefix('www.')
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')

    out = []
    for m in re.finditer(r'<item>(.*?)</item>|<entry>(.*?)</entry>', content, re.DOTALL):
        item = m.group(1) or m.group(2)
        title = strip_html(tag('title', item))
        link = tag('link', item)
        if not link:
            lm = re.search(r'<link[^>]+href=["\']([^"\']+)["\']', item)
            link = lm.group(1) if lm else ''
        if not title or not link:
            continue
        date = parse_date(tag('pubDate', item) or tag('published', item) or tag('updated', item))
        if date and date < cutoff:
            continue
        summary = strip_html(tag('description', item) or tag('summary', item) or tag('content', item))
        out.append({
            'title': title, 'url': link, 'date': date, 'source': feed_title,
            'summary': summary[:600], 'source_type': 'media',
        })
    return out


# ── Google News search (keyless) ──────────────────────────────────────────────

def scrape_google_news(query, days):
    """Google News RSS search. Titles arrive as "Headline - Publisher"."""
    params = urllib.parse.urlencode({'q': query, 'hl': 'en-GB', 'gl': 'GB', 'ceid': 'GB:en'})
    entries = scrape_rss(f'https://news.google.com/rss/search?{params}', days,
                         source_name='Google News')
    for e in entries:
        # Recover the real publisher so the site credits the outlet, not the feed.
        if ' - ' in e['title']:
            headline, _, publisher = e['title'].rpartition(' - ')
            if headline and len(publisher) < 60:
                e['title'] = headline.strip()
                e['source'] = publisher.strip()
    return entries


# ── Brave (optional) ──────────────────────────────────────────────────────────

def scrape_brave(query, api_key):
    params = urllib.parse.urlencode({'q': query, 'count': 20, 'freshness': 'pw'})
    data = json.loads(fetch(
        f'https://api.search.brave.com/res/v1/news/search?{params}',
        {'Accept': 'application/json', 'Accept-Encoding': 'identity',
         'X-Subscription-Token': api_key},
    ))
    out = []
    for item in data.get('results', []):
        age = str(item.get('age') or item.get('page_age') or '')
        out.append({
            'title': item.get('title', ''), 'url': item.get('url', ''),
            'date': age[:10] if 'T' in age else '',
            'source': (item.get('meta_url') or {}).get('hostname', '') or 'Brave News',
            'summary': strip_html(item.get('description', ''))[:600],
            'source_type': 'media',
        })
    return out


# ── Main ──────────────────────────────────────────────────────────────────────

def collect(days):
    """Run every source, tolerating individual failures."""
    jobs = [(f'pubmed: {q[:45]}', scrape_pubmed, (q, days)) for q in PUBMED_QUERIES]
    jobs += [(f'arxiv: {q}', scrape_arxiv, (q,)) for q in ARXIV_QUERIES]
    jobs += [(f's2: {q}', scrape_semantic_scholar, (q, days)) for q in SEMANTIC_SCHOLAR_QUERIES]
    jobs += [(f'rss: {name}', scrape_rss, (url, days, name)) for url, name in RSS_FEEDS.items()]
    jobs += [(f'news: {q[:40]}', scrape_google_news, (q, days)) for q in GOOGLE_NEWS_QUERIES]

    brave_key = os.environ.get('BRAVE_API_KEY', '').strip()
    if brave_key:
        jobs += [(f'brave: {q}', scrape_brave, (q, brave_key)) for q in BRAVE_QUERIES]
    else:
        log('[skip] Brave — BRAVE_API_KEY not set (all other sources still run)')

    results, failures = [], 0
    for label, fn, args in jobs:
        try:
            found = fn(*args)
            log(f'  [{len(found):3d}] {label}')
            results.extend(found)
        except Exception as e:
            failures += 1
            log(f'  [ERR] {label}: {type(e).__name__}: {e}')
        time.sleep(1.5)
    return results, failures, len(jobs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='report findings without writing data.json')
    ap.add_argument('--days', type=int, default=8, help='look-back window (default 8, for a weekly run)')
    args = ap.parse_args()

    data = load_data()
    before = len(data['cases'])
    excluded = load_excluded()
    seen = existing_urls(data) | {normalise_url(u) for u in excluded}
    log(f'Existing cases: {before} (plus {len(excluded)} previously rejected URLs)')

    candidates, failures, total = collect(args.days)
    log(f'\nFetched {len(candidates)} candidates ({total - failures}/{total} sources ok)')

    if failures == total:
        log('ERROR: every source failed — refusing to write data.json')
        return 1

    added = []
    for c in candidates:
        url = c.get('url', '')
        key = normalise_url(url)
        if not url or not c.get('title') or key in seen:
            continue
        if not is_relevant(c['title'], c.get('summary', '')):
            continue
        seen.add(key)
        c['category'] = guess_category(c['title'], c.get('summary', ''), c.get('source_type', 'media'))
        c['severity'] = guess_severity(c['title'], c.get('summary', ''))
        c['id'] = make_id(url, c.get('source_type', 'media'))
        c['scraped_at'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        if not c.get('date'):
            c['date'] = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        # Flags the keyword-assigned labels for the weekly Claude review pass.
        c['needs_review'] = True
        added.append(c)

    log(f'New relevant cases: {len(added)}')
    for c in added:
        log(f'  + [{c["severity"]:8s}] [{c["category"]:20s}] {c["title"][:70]}')

    if args.dry_run:
        log('\n--dry-run: data.json not written')
        return 0

    data['cases'].extend(added)
    recompute(data)
    save_data(data)
    log(f'\ndata.json: {before} -> {data["total_cases"]} cases')
    return 0


if __name__ == '__main__':
    sys.exit(main())
