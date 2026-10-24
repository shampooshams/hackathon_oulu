"""Fact receipts checker.

Rule: every number in an AI-written sentence must match a number inside one of
the facts that sentence cites ([F3]). Sentences without numbers (opinion,
banter) pass, but the UI labels them as opinion, not data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from companion.facts import FactStore

CITE = re.compile(r"\[([A-Z])(\d+)\]")
NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)")
EXEMPT = re.compile(r"\b(top|last|next|first|bottom)[\s-]+(\d{1,2})\b", re.I)
WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
         "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
         "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20}
WORD_RE = re.compile(r"\b(" + "|".join(WORDS) + r")\b", re.I)


def numbers_in(text: str) -> list[float]:
    return [float(m.replace(",", "")) for m in NUM.findall(text)]


def _number_set(text: str) -> set[float]:
    return {round(x, 2) for x in numbers_in(text)}


LEADING_CITES = re.compile(r"^((?:\s*\[[A-Z]\d+\])+)[\s.,;:!?]*")


def split_sentences(text: str) -> list[tuple[str, str]]:
    """Split into (sentence, extra_citations). Citations placed right after a
    full stop ("... 25 points. [F4]") are attached to the sentence before them."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+(?=\S)|\n+", text)]
    out: list[list[str]] = []
    for p in parts:
        if not p:
            continue
        m = LEADING_CITES.match(p)
        if m and out:
            out[-1][1] += m.group(1)
            p = p[m.end():].strip()
            if not p:
                continue
        out.append([p, ""])
    return [(a, b) for a, b in out]


@dataclass
class SentenceCheck:
    sentence: str
    cited: list[str]
    numbers: list[float]
    unsupported: list[float]
    unknown_ids: list[str]

    @property
    def ok(self) -> bool:
        return not self.unsupported and not self.unknown_ids


@dataclass
class Report:
    checks: list[SentenceCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def numbers_checked(self) -> int:
        return sum(len(c.numbers) for c in self.checks)

    @property
    def numbers_verified(self) -> int:
        return sum(len(c.numbers) - len(c.unsupported) for c in self.checks)

    @property
    def cited_ids(self) -> list[str]:
        seen = []
        for c in self.checks:
            for i in c.cited:
                if i not in seen:
                    seen.append(i)
        return seen

    @property
    def problems(self) -> list[SentenceCheck]:
        return [c for c in self.checks if not c.ok]

    def feedback(self, store: FactStore) -> str:
        lines = []
        for c in self.problems:
            if c.unknown_ids:
                lines.append(f'- "{c.sentence}" cites IDs that do not exist: {", ".join(c.unknown_ids)}')
            if c.unsupported:
                nums = ", ".join(_fmt(x) for x in c.unsupported)
                lines.append(f'- "{c.sentence}" contains number(s) {nums} that are not in the facts it cites '
                             f'({", ".join(c.cited) or "no citation"}).')
        return "\n".join(lines)


def _fmt(x: float) -> str:
    return str(int(x)) if x == int(x) else str(x)


def verify(text: str, store: FactStore) -> Report:
    rep = Report()
    for s, extra in split_sentences(text):
        cited = [f"{p}{n}" for p, n in CITE.findall(s + extra)]
        unknown = [c for c in cited if c not in store.facts]
        body = CITE.sub(" ", s)
        body = EXEMPT.sub(" ", body)
        nums = [round(x, 2) for x in numbers_in(body)]
        nums += [float(WORDS[w.lower()]) for w in WORD_RE.findall(body)]
        allowed: set[float] = set()
        for c in cited:
            if c in store.facts:
                allowed |= _number_set(store.facts[c].display + " " + store.facts[c].label)
        unsupported = [x for x in nums if x not in allowed]
        rep.checks.append(SentenceCheck(s, cited, nums, unsupported, unknown))
    return rep


def redact(text: str, rep: Report) -> str:
    out = text
    for c in rep.problems:
        out = out.replace(c.sentence, "_(removed: a claim I couldn't verify against the data)_")
    return out


def tamper(text: str, store: FactStore) -> tuple[str, str]:
    """Demo helper: corrupt one cited number to show the checker catching it."""
    for s, extra in split_sentences(text):
        cited = [f"{p}{n}" for p, n in CITE.findall(s + extra)]
        if not cited:
            continue
        body = CITE.sub(" ", s)
        for m in NUM.finditer(body):
            val = float(m.group(1).replace(",", ""))
            if val < 1:
                continue
            allowed = set()
            for c in cited:
                if c in store.facts:
                    allowed |= _number_set(store.facts[c].display + " " + store.facts[c].label)
            for delta in (17, 3, 11, 23):
                new = val + delta if val + delta < 100 else val - delta
                if round(new, 2) not in allowed and new > 0:
                    break
            old_tok = m.group(1)
            new_tok = _fmt(new)
            # replace this exact token occurrence in the original sentence
            new_s = re.sub(rf"(?<![\w.]){re.escape(old_tok)}(?![\d])", new_tok, s, count=1)
            return text.replace(s, new_s, 1), f"changed {old_tok} → {new_tok}"
    return text, ""


def strip_citations(text: str) -> str:
    return re.sub(r"\s*\[[A-Z]\d+\]", "", text)
