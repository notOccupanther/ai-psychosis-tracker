#!/usr/bin/env python3
"""Relevance filtering and classification for scraped candidates.

The old pipeline used a single flat keyword list, which let through anything
mentioning "delusion" in a non-AI context. Relevance here requires an AI term
AND a term from a strict harm vocabulary. An earlier version also accepted a
broad "relational" vocabulary; words like "depend", "isolat", "attach" and
"vulnerable" match ordinary technical prose, and the first live run admitted a
microarchitectural side-channel paper and a Nvidia datacentre story. Generic
single words are now excluded in favour of clinical terms and explicitly
AI-directed relational phrases.

Matching anchors the head of each term on a word boundary but leaves the tail
open, so "delusion" also catches "delusions" and "hospitalis" catches
"hospitalised". Short or ambiguous terms are tail-anchored too, via ANCHORED:
without it "ai" fires inside "said", "again" and "email", and "court" inside
"courtesy".
"""

import re

AI_TERMS = [
    'ai', 'a.i.', 'artificial intelligence', 'chatbot', 'chat bot', 'chatgpt',
    'openai', 'claude', 'gemini', 'copilot', 'llm', 'large language model',
    'character.ai', 'character ai', 'replika', 'generative ai', 'anthropic',
    'grok', 'deepseek', 'conversational agent',
]

# A candidate must carry at least one of these alongside an AI term. Every entry
# is either clinical vocabulary or an explicitly AI-directed relational phrase.
# Bare words that appear in ordinary technical writing are deliberately excluded.
HARM_TERMS = [
    # psychosis and related states
    'psychosis', 'psychotic', 'delusion', 'schizophreni', 'mania', 'manic',
    'paranoi', 'grandiose', 'grandiosity', 'messianic', 'chosen one',
    'reality testing', 'break from reality', 'lost touch with reality',
    # self-harm and violence
    'suicide', 'suicidal', 'self-harm', 'self harm', 'took his own life',
    'took her own life', 'took their own life', 'homicide', 'manslaughter',
    'wrongful death', 'murdered', 'killed himself', 'killed herself',
    # clinical contact
    'mental health', 'mental illness', 'mental harm', 'psychiatr',
    'psychotherapy', 'psychological harm', 'psychological risk',
    'hospitalis', 'hospitaliz', 'involuntary commitment', 'sectioned',
    'psychiatric ward', 'inpatient', 'clinical psycholog',
    # AI-directed relational harm
    'parasocial', 'ai companion', 'chatbot companion', 'digital companion',
    'companion app', 'ai girlfriend', 'ai boyfriend', 'virtual girlfriend',
    'virtual boyfriend', 'replika', 'character.ai', 'character ai',
    'fell in love', 'in love with', 'romantic relationship', 'human-chatbot',
    'human-ai relationship', 'soulmate', 'emotional dependence',
    'emotional dependency', 'emotional attachment', 'emotional support',
    'ai addiction', 'chatbot addiction', 'ai psychosis', 'chatbot psychosis',
    'chatgpt psychosis', 'loneliness', 'lonely', 'love', 'ai partner',
    'confidant', 'therapist', 'addict', 'obsess', 'hypochondria',
    'ai dependency', 'ai dependence', 'depending on ai',
    'human relationship', 'relational engagement', 'relationship advice',
    # Deaths and violence linked to AI use are core to this tracker; 'death'
    # and 'killed' are broad but only fire alongside a required AI term.
    'death', 'killed', 'shooting',
    # mechanism terms specific to this literature
    'sycophan', 'anthropomorphis', 'anthropomorphiz',
]

# Terms that must not match inside a longer word.
ANCHORED = {'ai', 'a.i.', 'llm', 'grok', 'lonely', 'inpatient', 'sectioned'}

# Checked in order; first match wins.
CATEGORY_RULES = [
    ('romantic_attachment', [
        'girlfriend', 'boyfriend', 'romantic', 'romance', 'in love',
        'fell in love', 'marry', 'married', 'partner', 'lover', 'dating',
        'companion app', 'ai companion', 'replika', 'parasocial', 'soulmate',
        'intimacy', 'intimate',
    ]),
    ('clinical', [
        'case report', 'case series', 'psychiatr', 'clinician', 'inpatient',
        'diagnos', 'dsm', 'comorbid', 'admitted to hospital',
        'emergency department', 'peer-reviewed', 'cohort',
    ]),
    ('paranoia', [
        'paranoi', 'surveillance', 'conspiracy', 'being watched', 'persecut',
        'tracking me', 'spying',
    ]),
    ('identity_confusion', [
        'identity', 'who i am', 'sentien', 'is conscious', 'became god',
        'chosen one', 'messianic', 'prophet', 'awakening', 'simulation',
    ]),
    ('reality_distortion', [
        'psychosis', 'psychotic', 'delusion', 'break from reality',
        'lost touch with reality', 'reality distortion', 'grandiose', 'mania',
        'spiral', 'rabbit hole', 'reinforc', 'sycophan',
    ]),
]

SEVERITY_RULES = [
    ('critical', [
        'killed', 'murder', 'homicide', 'manslaughter', 'suicide',
        'took his own life', 'took her own life', 'took their own life',
        'fatal', 'shooting', 'stabbed', 'wrongful death', 'died',
    ]),
    ('high', [
        'hospitalis', 'hospitaliz', 'involuntary commitment', 'sectioned',
        'arrest', 'charged', 'court', 'lawsuit', 'psychiatric ward', 'detained',
        'self-harm', 'self harm', 'suicidal', 'overdose', 'violence', 'assault',
    ]),
    ('medium', [
        'psychosis', 'psychotic', 'delusion', 'mania', 'manic', 'breakdown',
        'crisis', 'divorce', 'lost his job', 'lost her job', 'estranged',
        'debt', 'financial ruin', 'addict',
    ]),
]

_CACHE = {}


def _compile(terms):
    key = id(terms)
    if key not in _CACHE:
        parts = []
        for t in terms:
            esc = re.escape(t)
            head = r'\b' if t[0].isalnum() else ''
            tail = r'\b' if t in ANCHORED and t[-1].isalnum() else ''
            parts.append(head + esc + tail)
        _CACHE[key] = re.compile('|'.join(parts))
    return _CACHE[key]


def _blob(*parts):
    return ' '.join(p for p in parts if p).lower()


def is_relevant(title, summary=''):
    text = _blob(title, summary)
    return bool(_compile(AI_TERMS).search(text) and _compile(HARM_TERMS).search(text))



def guess_category(title, summary='', source_type='media'):
    text = _blob(title, summary)
    for category, keywords in CATEGORY_RULES:
        if _compile(keywords).search(text):
            return category
    # Fall back by source type rather than lumping papers under "Media Coverage".
    return 'clinical' if source_type == 'academic' else 'media_coverage'


def guess_severity(title, summary='', source_type='media'):
    text = _blob(title, summary)
    severity = 'low'
    for level, keywords in SEVERITY_RULES:
        if _compile(keywords).search(text):
            severity = level
            break
    # Papers are literature, not incidents. A suicide-prevention study matching
    # "suicide" should not display as 'critical', which on the site means a death
    # occurred. Cap the literature at 'medium' and let the weekly review promote
    # a genuine case report if it warrants it.
    if source_type == 'academic' and severity in ('critical', 'high'):
        severity = 'medium'
    return severity
