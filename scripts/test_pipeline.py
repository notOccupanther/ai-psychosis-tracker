#!/usr/bin/env python3
"""Offline tests for the pipeline.

The parsers are exercised against recorded-shape fixtures rather than the live
APIs, so this suite runs anywhere, including in CI before a network call is
made. Run: python scripts/test_pipeline.py
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import classify  # noqa: E402
import common  # noqa: E402
import scrape  # noqa: E402

ARXIV_FIXTURE = b'''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2601.01234v1</id>
    <published>2026-01-15T10:00:00Z</published>
    <title>Sycophancy in Large Language Models Reinforces User Delusions</title>
    <summary>We show that chatbot agreement amplifies delusional beliefs in vulnerable users.</summary>
    <author><name>A Researcher</name></author>
    <author><name>B Scientist</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2601.05678v1</id>
    <published>2026-01-20T10:00:00Z</published>
    <title>Efficient Sparse Attention Kernels</title>
    <summary>A faster attention implementation for transformer training.</summary>
    <author><name>C Engineer</name></author>
  </entry>
</feed>'''

RSS_FIXTURE = b'''<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Example Tech News</title>
  <item>
    <title>Man hospitalised after ChatGPT encouraged his delusions</title>
    <link>https://example.com/story-one?utm_source=rss&amp;utm_medium=feed</link>
    <pubDate>Mon, 20 Jul 2026 09:00:00 +0000</pubDate>
    <description>&amp;lt;p&amp;gt;His family says the chatbot told him he was chosen.&amp;lt;/p&amp;gt;</description>
  </item>
  <item>
    <title>New quarterly results from a cloud provider</title>
    <link>https://example.com/story-two</link>
    <pubDate>Tue, 21 Jul 2026 09:00:00 +0000</pubDate>
    <description>Revenue grew.</description>
  </item>
</channel></rss>'''

PUBMED_SEARCH = json.dumps({'esearchresult': {'idlist': ['40000001']}}).encode()
PUBMED_FETCH = b'''<?xml version="1.0"?>
<PubmedArticleSet><PubmedArticle><MedlineCitation>
  <PMID>40000001</PMID>
  <Article>
    <Journal><Title>British Journal of Psychiatry</Title>
      <JournalIssue><PubDate><Year>2026</Year><Month>Mar</Month></PubDate></JournalIssue>
    </Journal>
    <ArticleTitle>Chatbot psychosis: a case series</ArticleTitle>
    <Abstract><AbstractText>Three patients developed delusions after chatbot use.</AbstractText></Abstract>
    <AuthorList>
      <Author><LastName>Smith</LastName><Initials>J</Initials></Author>
    </AuthorList>
  </Article>
</MedlineCitation>
<PubmedData><ArticleIdList>
  <ArticleId IdType="doi">10.1192/bjp.2026.1</ArticleId>
</ArticleIdList></PubmedData>
</PubmedArticle></PubmedArticleSet>'''

S2_FIXTURE = json.dumps({'data': [
    {'title': 'Emotional dependence on AI companions', 'abstract': 'Users report attachment.',
     'url': 'https://www.semanticscholar.org/paper/abc', 'venue': 'JMIR',
     'publicationDate': '2026-08-01', 'authors': [{'name': 'D Author'}],
     'externalIds': {'DOI': '10.1000/xyz'}},
    {'title': 'Ancient pottery classification', 'abstract': 'Kilns.',
     'url': 'https://www.semanticscholar.org/paper/def', 'venue': 'Archaeology',
     'publicationDate': '2026-08-02', 'authors': [], 'externalIds': {}},
]}).encode()


class TestNormalise(unittest.TestCase):
    def test_strips_scheme_www_slash_and_tracking(self):
        variants = [
            'https://www.example.com/a/b/',
            'http://example.com/a/b',
            'https://example.com/a/b?utm_source=x&utm_campaign=y',
        ]
        keys = {common.normalise_url(v) for v in variants}
        self.assertEqual(keys, {'example.com/a/b'}, 'these should all dedupe together')

    def test_keeps_meaningful_query(self):
        self.assertEqual(common.normalise_url('https://example.com/p?id=7'), 'example.com/p?id=7')

    def test_distinct_urls_stay_distinct(self):
        self.assertNotEqual(common.normalise_url('https://a.com/x'), common.normalise_url('https://b.com/x'))


class TestClassify(unittest.TestCase):
    def test_requires_both_vocabularies(self):
        self.assertFalse(classify.is_relevant('Therapy waiting lists hit record highs'))
        self.assertFalse(classify.is_relevant('Anthropic ships a faster model'))
        self.assertTrue(classify.is_relevant('ChatGPT reinforced his delusions, family says'))

    def test_word_boundaries(self):
        # "said"/"again"/"email" contain "ai"; "courtesy" contains "court".
        self.assertFalse(classify.is_relevant('She said again the email detail was unclear'))
        self.assertFalse(classify.is_relevant('Courtesy vouchers issued after delays'))

    def test_inflections_match(self):
        for t in ['delusion', 'delusions', 'delusional']:
            self.assertTrue(classify.is_relevant(f'AI chatbot linked to {t} thinking'), t)

    def test_romance_without_clinical_language(self):
        self.assertTrue(classify.is_relevant('She fell in love with her AI boyfriend'))

    def test_severity_ranking(self):
        self.assertEqual(classify.guess_severity('Teen killed after chatbot conversations'), 'critical')
        self.assertEqual(classify.guess_severity('Man hospitalised after chatbot use'), 'high')
        self.assertEqual(classify.guess_severity('Users report delusional thinking'), 'medium')
        self.assertEqual(classify.guess_severity('A columnist reflects on AI companions'), 'low')

    def test_academic_is_clinical(self):
        self.assertEqual(classify.guess_category('Any title', '', 'academic'), 'clinical')

    def test_corpus_recall(self):
        """The curated corpus is the ground truth: the filter must not reject it."""
        cases = common.load_data()['cases']
        kept = [c for c in cases if classify.is_relevant(c.get('title', ''), c.get('summary', ''))]
        ratio = len(kept) / len(cases)
        self.assertGreater(ratio, 0.90, f'recall regressed to {ratio:.1%}')

    def test_precision_on_labelled_scrape(self):
        """Guards the failure that shipped: a scrape whose entries are mostly junk.

        eval_cases.json is the first live scrape, hand-labelled. The original
        vocabulary scored 39% precision here and published a datacentre story
        and a side-channel paper as AI psychosis cases.
        """
        path = os.path.join(os.path.dirname(__file__), 'eval_cases.json')
        with open(path, encoding='utf-8') as f:
            labelled = json.load(f)
        tp = fp = fn = 0
        for case in labelled:
            got = classify.is_relevant(case['title'], case['summary'])
            if got and case['label']:
                tp += 1
            elif got:
                fp += 1
            elif case['label']:
                fn += 1
        precision = tp / (tp + fp)
        recall = tp / (tp + fn)
        self.assertGreater(precision, 0.75, f'precision regressed to {precision:.0%}')
        self.assertGreater(recall, 0.90, f'recall regressed to {recall:.0%}')

    def test_generic_technical_prose_is_rejected(self):
        """The exact false positives from the first live run."""
        for title in [
            'Nvidia partners with data center developer Cloverleaf',
            'Remote-Timer-as-a-Service: Efficient Microarchitectural Leakage in the Cloud',
            'ConceptTS: LLM-Guided Concept Bottlenecks for Time-Series Forecasting',
            'Axios Partners With OpenAI to Automate Local Journalism',
            "An AI 'debt bomb' crisis? No. This isn't Enron 2.0",
            'Frustrated GP patients hang up as Yorkshire accent baffles AI receptionist',
        ]:
            self.assertFalse(classify.is_relevant(title), title)

    def test_academic_severity_is_capped(self):
        """A suicide-prevention paper must not display as a death."""
        title = 'Large language models in adolescent suicide prevention'
        self.assertEqual(classify.guess_severity(title, '', 'media'), 'critical')
        self.assertEqual(classify.guess_severity(title, '', 'academic'), 'medium')


class TestParsers(unittest.TestCase):
    def parse(self, fixture, fn, *args):
        with mock.patch.object(scrape, 'fetch', return_value=fixture):
            return fn(*args)

    def test_arxiv(self):
        got = self.parse(ARXIV_FIXTURE, scrape.scrape_arxiv, 'q')
        self.assertEqual(len(got), 2, 'parser returns all entries; relevance filters later')
        first = got[0]
        self.assertEqual(first['date'], '2026-01-15')
        self.assertEqual(first['source_type'], 'academic')
        self.assertEqual(first['authors'], 'A Researcher, B Scientist')
        self.assertTrue(classify.is_relevant(first['title'], first['summary']))
        self.assertFalse(classify.is_relevant(got[1]['title'], got[1]['summary']))

    def test_rss_strips_html_and_filters_by_date(self):
        got = self.parse(RSS_FIXTURE, scrape.scrape_rss,
                         'https://example.com/feed', 100000, 'Example News')
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0]['source'], 'Example News',
                         'publisher name should come from the feed map, not the feed title')
        self.assertNotIn('<p>', got[0]['summary'])
        self.assertEqual(got[0]['date'], '2026-07-20')

    def test_rss_decodes_entity_encoded_markup(self):
        """Feeds double-encode: the site showed literal "&lt;p&gt;" to readers."""
        got = self.parse(RSS_FIXTURE, scrape.scrape_rss,
                         'https://example.com/feed', 100000, 'Example News')
        summary = got[0]['summary']
        for artefact in ('&lt;', '&gt;', '&amp;', '<p>'):
            self.assertNotIn(artefact, summary)
        self.assertIn('chosen', summary)

    def test_google_news_recovers_publisher(self):
        fixture = (b'<?xml version="1.0"?><rss><channel><title>Google News</title>'
                   b'<item><title>Man hospitalised after ChatGPT fed his delusions'
                   b' - The Guardian</title>'
                   b'<link>https://news.google.com/rss/articles/ABC</link>'
                   b'<pubDate>Mon, 24 Aug 2026 09:00:00 +0000</pubDate>'
                   b'<description>&lt;p&gt;Family say it agreed with everything.&lt;/p&gt;'
                   b'</description></item></channel></rss>')
        got = self.parse(fixture, scrape.scrape_google_news, '"AI psychosis"', 100000)
        self.assertEqual(got[0]['source'], 'The Guardian')
        self.assertEqual(got[0]['title'], 'Man hospitalised after ChatGPT fed his delusions')
        self.assertNotIn('&lt;', got[0]['summary'])

    def test_every_feed_has_a_publisher_name(self):
        for url, name in scrape.RSS_FEEDS.items():
            self.assertTrue(name and '|' not in name and '&' not in name, url)

    def test_rss_date_cutoff_excludes_old(self):
        got = self.parse(RSS_FIXTURE, scrape.scrape_rss, 'https://example.com/feed', 1)
        self.assertEqual(got, [], 'fixture items are older than a 1-day window')

    def test_pubmed(self):
        with mock.patch.object(scrape, 'fetch', side_effect=[PUBMED_SEARCH, PUBMED_FETCH]):
            got = scrape.scrape_pubmed('q', 8)
        self.assertEqual(len(got), 1)
        c = got[0]
        self.assertEqual(c['url'], 'https://doi.org/10.1192/bjp.2026.1')
        self.assertEqual(c['date'], '2026-03-01')
        self.assertEqual(c['venue'], 'British Journal of Psychiatry')
        self.assertEqual(c['authors'], 'Smith J')

    def test_pubmed_empty_search_short_circuits(self):
        empty = json.dumps({'esearchresult': {'idlist': []}}).encode()
        with mock.patch.object(scrape, 'fetch', return_value=empty) as f:
            self.assertEqual(scrape.scrape_pubmed('q', 8), [])
            self.assertEqual(f.call_count, 1, 'must not call efetch with an empty id list')

    def test_semantic_scholar_uses_doi_and_date_window(self):
        got = self.parse(S2_FIXTURE, scrape.scrape_semantic_scholar, 'q', 100000)
        self.assertEqual(got[0]['url'], 'https://doi.org/10.1000/xyz')
        self.assertEqual(got[1]['url'], 'https://www.semanticscholar.org/paper/def')


class TestExclusions(unittest.TestCase):
    def test_excluded_urls_are_not_rescraped(self):
        """A rejected entry must stay rejected, or review work is undone weekly."""
        excluded = common.load_excluded()
        self.assertTrue(excluded, 'blocklist should carry the reviewed rejections')
        published = {common.normalise_url(c['url'])
                     for c in common.load_data()['cases'] if c.get('url')}
        for url in excluded:
            self.assertNotIn(common.normalise_url(url), published,
                             f'{url} is both excluded and published')


class TestAggregates(unittest.TestCase):
    def sample(self):
        return {'cases': [
            {'date': '2026-01-05', 'category': 'clinical', 'severity': 'high', 'url': 'https://a.com/1'},
            {'date': '2026-01-20', 'category': 'clinical', 'severity': 'low', 'url': 'https://a.com/2'},
            {'date': '2026-02-02', 'category': 'romantic_attachment', 'severity': 'critical', 'url': 'https://a.com/3'},
        ]}

    def test_recompute(self):
        d = common.recompute(self.sample())
        self.assertEqual(d['total_cases'], 3)
        self.assertEqual(d['trend'], {'labels': ['2026-01', '2026-02'], 'values': [2, 1]})
        self.assertEqual(d['categories']['labels'][0], 'Clinical Cases')
        self.assertEqual(d['severity_counts'], {'critical': 1, 'high': 1, 'low': 1})
        self.assertEqual(d['date_range'], {'from': '2026-01-05', 'to': '2026-02-02'})

    def test_recompute_is_idempotent(self):
        a = common.recompute(self.sample())
        b = common.recompute(common.recompute(self.sample()))
        for k in ('trend', 'categories', 'severity_counts', 'date_range', 'total_cases'):
            self.assertEqual(a[k], b[k], k)

    def test_recompute_preserves_published_schema(self):
        """recompute() must not rename keys that data.json already publishes."""
        published = common.load_data()
        recomputed = common.recompute(json.loads(json.dumps(published)))
        for key in ('trend', 'categories', 'severity_counts', 'date_range'):
            self.assertEqual(set(published[key]), set(recomputed[key]),
                             f'{key} key set changed')
        # Same counts, order is not significant.
        self.assertEqual(
            dict(zip(published['categories']['labels'], published['categories']['values'])),
            dict(zip(recomputed['categories']['labels'], recomputed['categories']['values'])))
        self.assertEqual(published['severity_counts'], recomputed['severity_counts'])
        self.assertEqual(published['trend'], recomputed['trend'])

    def test_live_data_matches_frontend_contract(self):
        """index.html reads these keys directly; a missing one blanks the page."""
        d = common.load_data()
        for key in ('generated_at', 'total_cases', 'cases', 'severity_counts', 'trend'):
            self.assertIn(key, d)
        self.assertEqual(d['total_cases'], len(d['cases']))
        self.assertEqual(len(d['trend']['labels']), len(d['trend']['values']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
