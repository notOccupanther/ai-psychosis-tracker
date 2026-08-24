#!/usr/bin/env python3
"""Relevance filtering and classification for scraped candidates.

The old pipeline used a single flat keyword list, which let through anything
mentioning "delusion" in a non-AI context. Relevance here requires an AI term
AND either a psychological-harm term or a relational term, so that romance-led
stories ("fell in love with her AI boyfriend") qualify without opening the gate
to every article that merely says "delusion".

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
    'character.ai', 'character ai', 'replika', 'companion app', 'ai companion',
    'generative ai', 'anthropic', 'grok', 'deepseek', 'virtual girlfriend',
    'virtual boyfriend', 'digital companion', 'algorithm',
]

# Romantic, parasocial and dependence framing, which often carries no clinical
# vocabulary at all.
RELATIONAL_TERMS = [
    'fell in love', 'in love with', 'girlfriend', 'boyfriend', 'married',
    'marry', 'proposed to', 'romance', 'romantic', 'relationship', 'companion',
    'parasocial', 'emotional support', 'soulmate', 'lover', 'friend',
    'love', 'dating', 'partner', 'confidant',
    'intimacy', 'intimate', 'bond with', 'attach', 'depend', 'addict',
    'obsess', 'grief', 'grieving', 'loneliness', 'lonely', 'isolat',
]

PSYCH_TERMS = [
    'psychosis', 'psychotic', 'delusion', 'mental health', 'mental illness',
    'schizophreni', 'mania', 'manic', 'paranoi', 'grandiose', 'grandiosity',
    'messianic', 'prophet', 'chosen one', 'awakening', 'sentien',
    'hospitalis', 'hospitaliz', 'involuntary commitment', 'sectioned',
    'suicide', 'suicidal', 'self-harm', 'self harm', 'homicide', 'death',
    'died', 'killed', 'psychiatr', 'therapist', 'therapy', 'counsel',
    'patient', 'clinician', 'diagnos', 'reality testing', 'sycophan',
    'spiral', 'breakdown', 'crisis', 'vulnerable', 'harm', 'liable',
    'psycholog', 'mental harm', 'abuse',
    'wrongful death', 'safeguard', 'distress',
]

# Terms that must not match inside a longer word.
ANCHORED = {'ai', 'a.i.', 'llm', 'grok', 'court', 'died', 'friend', 'bond with'}

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
    if not _compile(AI_TERMS).search(text):
        return False
    return bool(_compile(PSYCH_TERMS).search(text)
                or _compile(RELATIONAL_TERMS).search(text))


def guess_category(title, summary='', source_type='media'):
    if source_type == 'academic':
        return 'clinical'
    text = _blob(title, summary)
    for category, keywords in CATEGORY_RULES:
        if _compile(keywords).search(text):
            return category
    return 'media_coverage'


def guess_severity(title, summary=''):
    text = _blob(title, summary)
    for severity, keywords in SEVERITY_RULES:
        if _compile(keywords).search(text):
            return severity
    return 'low'
