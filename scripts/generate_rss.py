#!/usr/bin/env python3
"""Regenerate feed.xml from data.json (20 most recent non-academic cases)."""

import os
import sys
from datetime import datetime, timezone
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import CAT_LABELS, ROOT, SITE_URL, load_data  # noqa: E402

OUT_PATH = os.path.join(ROOT, 'feed.xml')
TITLE = 'AI Psychosis Watch'
DESCRIPTION = ('Weekly tracking of AI-induced psychological harm — dependency, '
               'delusion, identity confusion, and reality distortion.')


def rfc2822(date_str):
    try:
        d = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        d = datetime.now(timezone.utc)
    return d.strftime('%a, %d %b %Y 00:00:00 +0000')


def main():
    cases = [c for c in load_data()['cases'] if c.get('source_type') != 'academic']
    cases.sort(key=lambda c: c.get('date') or '', reverse=True)

    items = []
    for c in cases[:20]:
        link = c.get('url') or f'{SITE_URL}/#case-{c.get("id", "")}'
        category = CAT_LABELS.get(c.get('category'), c.get('category') or 'Other')
        items.append(f'''  <item>
    <title>{escape(c.get('title') or '')}</title>
    <link>{escape(link)}</link>
    <guid isPermaLink="false">{escape(link)}</guid>
    <pubDate>{rfc2822(c.get('date'))}</pubDate>
    <category>{escape(category)}</category>
    <description>{escape(c.get('summary') or '')}</description>
    <source url="{SITE_URL}">{TITLE}</source>
  </item>''')

    feed = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{TITLE}</title>
    <link>{SITE_URL}</link>
    <description>{escape(DESCRIPTION)}</description>
    <language>en</language>
    <lastBuildDate>{datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S +0000')}</lastBuildDate>
    <atom:link href="{SITE_URL}/feed.xml" rel="self" type="application/rss+xml"/>
    <image>
      <url>{SITE_URL}/apw-logo.png</url>
      <title>{TITLE}</title>
      <link>{SITE_URL}</link>
    </image>
{chr(10).join(items)}
  </channel>
</rss>
'''
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        f.write(feed)
    print(f'feed.xml: {len(items)} items')


if __name__ == '__main__':
    main()
