#!/usr/bin/env python3
"""Regenerate sitemap.xml with real lastmod dates from data.json.

The previous sitemap was a static file with no lastmod, so crawlers had no
signal that the data changes weekly.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import ROOT, SITE_URL, load_data  # noqa: E402

# path, changefreq, priority
PAGES = [
    ('', 'weekly', '1.0'),
    ('methodology.html', 'monthly', '0.8'),
    ('data.json', 'weekly', '0.6'),
    ('feed.xml', 'weekly', '0.6'),
]


def main():
    lastmod = (load_data().get('generated_at') or '')[:10]
    urls = []
    for path, changefreq, priority in PAGES:
        urls.append(
            f'  <url>\n'
            f'    <loc>{SITE_URL}/{path}</loc>\n'
            + (f'    <lastmod>{lastmod}</lastmod>\n' if lastmod else '')
            + f'    <changefreq>{changefreq}</changefreq>\n'
            f'    <priority>{priority}</priority>\n'
            f'  </url>'
        )

    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           + '\n'.join(urls) + '\n</urlset>\n')

    with open(os.path.join(ROOT, 'sitemap.xml'), 'w', encoding='utf-8') as f:
        f.write(xml)
    print(f'sitemap.xml: {len(PAGES)} urls, lastmod {lastmod}')


if __name__ == '__main__':
    main()
