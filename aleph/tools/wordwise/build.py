#!/usr/bin/env python3
"""Build the Word Wise glossaries in aleph/data/wordwise.

usage: build.py NLTK_DATA KOWIKTIONARY_JSONL OUT_DIR

NLTK_DATA holds Princeton WordNet 3.0 as corpora/wordnet.zip,
KOWIKTIONARY_JSONL is Korean Wiktionary's English entries from kaikki.org, and
word frequencies come from the wordfreq package. Each output line is
"word<TAB>hint<TAB>zipf x 10" for words rare enough to deserve a hint.
"""
import json
import os
import re
import sys

import nltk
from wordfreq import top_n_list, zipf_frequency

RAREST = 1.8   # below this a "word" is usually a name or a typo
COMMON = 4.3   # above this nobody needs a hint
HINT_CHARS = 34
KO_CHARS = 14

WORD = re.compile(r"^[a-z][a-z'-]{3,}$")
HANGUL = re.compile(r"[가-힣]")


def candidates():
    words = {}
    for w in top_n_list("en", 150000):
        if WORD.match(w):
            z = zipf_frequency(w, "en")
            if RAREST <= z < COMMON:
                words[w] = z
    return words


LEADS = ("being ", "having ", "a ", "an ", "the ", "in a ", "to ", "marked by ", "characterized by ",
         "showing ", "full of ")


def short_definition(text):
    text = re.sub(r"\(.*?\)", "", text).split(";")[0].strip()
    changed = True
    while changed:
        changed = False
        for lead in LEADS:
            if text.startswith(lead) and len(text) > len(lead) + 3:
                text, changed = text[len(lead):], True
    if text.startswith(("of ", "relating to", "used of", "a person who", "used ", "in ")):
        return None
    words = text.split()
    return text if 1 <= len(words) <= 5 and len(text) <= HINT_CHARS else None


def english_hint(wn, word, z):
    """A clearly more common synonym from the main sense, else a short definition.
    Inflected forms get no entry of their own; the reader finds them by their base."""
    if not wn.lemmas(word):
        return None
    senses = wn.synsets(word)
    if not senses:
        return None
    main = senses[0]
    best, best_z = None, max(z + 0.8, 4.0)
    pools = [main.lemma_names()]
    if main.pos() == "n" and z < 3.0:
        pools += [h.lemma_names() for h in main.hypernyms()[:1]]
    for pool in pools:
        for name in pool:
            cand = name.replace("_", " ").lower()
            if cand == word or cand[:4] == word[:4] or len(cand.split()) > 2 or not cand.isalpha():
                continue
            cz = zipf_frequency(cand, "en")
            if cz >= best_z:
                best, best_z = cand, cz
        if best:
            return best
    for synset in senses[:2]:
        hint = short_definition(synset.definition())
        if not hint or re.search(r"\d", hint) or hint.endswith(" manner"):
            continue
        if word[:5] in hint and not hint.startswith("not "):
            continue
        return hint
    return None


def korean_hints(path, words):
    hints = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            word = (entry.get("word") or "").lower()
            if word not in words or word in hints:
                continue
            for sense in entry.get("senses", []):
                gloss = next(iter(sense.get("glosses") or []), "")
                gloss = re.sub(r"[\(\[\{（].*?[\)\]\}）]", "", gloss)
                gloss = re.split(r"[,;.。/·:]", gloss)[0].strip()
                gloss = re.sub(r"^[을를이가에의은는와과도로]\s+", "", gloss)
                if gloss and HANGUL.search(gloss) and len(gloss) <= KO_CHARS:
                    hints[word] = gloss
                    break
    return hints


def write(path, words, hints):
    with open(path, "w", encoding="utf-8") as f:
        for word in sorted(hints):
            f.write(f"{word}\t{hints[word]}\t{round(words[word] * 10)}\n")


def main(nltk_data, kowiktionary, out_dir):
    words = candidates()
    nltk.data.path.insert(0, os.path.abspath(nltk_data))
    from nltk.corpus import wordnet as wn
    en = {}
    for word, z in words.items():
        hint = english_hint(wn, word, z)
        if hint:
            en[word] = hint
    ko = korean_hints(kowiktionary, words)
    write(f"{out_dir}/en-en.tsv", words, en)
    with open(f"{out_dir}/common-en.txt", "w", encoding="utf-8") as f:
        common = [w for w in top_n_list("en", 30000) if WORD.match(w)]
        f.write("\n".join(sorted(common)) + "\n")
    write(f"{out_dir}/en-ko.tsv", words, ko)
    print(f"{len(words)} candidates, {len(en)} English hints, {len(ko)} Korean hints")


if __name__ == "__main__":
    main(*sys.argv[1:4])
