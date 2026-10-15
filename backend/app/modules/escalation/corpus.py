"""Deterministic corpus retrieval, conflict check and information-vs-advice classifier (E8-S3).

The evidence score is computed from retrieval only (token overlap between the question's content
tokens and the passage's curated keywords/text, 0-1). No model self-assessment, no confidence score,
no external call. Thresholds and the review band are versioned configuration.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from app.core.time import dubai_today
from app.modules.escalation.models import CorpusPassage

STOPWORDS_EN = {
    "what", "is", "the", "a", "an", "in", "for", "of", "to", "how", "do", "does", "i", "my", "we", "our", "are", "and",
    "or", "it", "this", "that", "uae", "dubai", "be", "can", "when", "which", "on", "at", "with", "me", "there", "need",
    "must", "have", "has", "any", "about", "please", "tell", "much", "many", "long", "should", "will", "by", "am", "as",
    "if", "from", "into", "under", "per", "was", "were", "you", "your", "their", "its", "than", "then", "so", "not",
    "company", "business", "llc", "year", "years", "qualify", "qualifies", "deduct", "exempt", "owe", "apply", "applies",
    "situation", "case", "pay", "still", "really", "also", "allowed", "eligible",
}
STOPWORDS_AR = {"ما", "ماذا", "هي", "هو", "في", "من", "على", "هل", "كم", "متى", "كيف", "ان", "أن", "عن", "الى", "إلى", "مع", "او", "أو", "و", "لي", "لنا", "هذا", "هذه", "ذلك", "يجب", "يمكن", "التي", "الذي", "شركه", "شركتي", "دبي", "الامارات"}
_TASHKEEL = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭ]")
_TOKEN = re.compile(r"[0-9a-z؀-ۿ]+")

LEGAL_PATTERNS = (
    "sue", "lawsuit", "court", "litigation", "dispute", "breach of contract", "terminate the contract", "terminate my employee",
    "dismiss", "liable", "liability", "lawyer", "legal action", "claim against", "arbitration", "fine me", "appeal the penalty",
    "draft a contract", "review my contract", "power of attorney", "visa cancellation", "labour case", "labor case",
    "محكمه", "محكمة", "دعوى", "قضيه", "قضية", "محامي", "نزاع", "فسخ العقد", "مقاضاة", "مسؤوليه قانونيه", "تحكيم", "صياغة عقد",
)
OWN_POSITION_PATTERNS = (
    "do i qualify", "qualify for", "am i exempt", "are we exempt", "can i deduct", "can we deduct", "is my income", "my income",
    "my revenue", "my profit", "my turnover", "our revenue", "our turnover", "do i owe", "do we owe", "does my", "apply to my",
    "apply to me", "apply to us", "my situation", "my case", "what should i", "what should we", "do i have to pay", "do we have to pay",
    "should i register", "should we register", "am i required", "are we required", "is my company", "is our company", "my tax position",
    "هل انا", "هل أنا", "هل شركتي", "دخلي", "ايراداتي", "إيراداتي", "هل يحق لي", "هل يمكنني خصم", "هل انا معفي", "هل أنا معفى", "ماذا علي ان افعل", "هل علي ان",
)


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = _TASHKEEL.sub("", text)
    text = re.sub(r"[\u060C\u061B\u061F\u066A-\u066D\u06D4]", " ", text)  # Arabic punctuation
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي").replace("ـ", "")
    return text


def tokens(text: str) -> list[str]:
    out = []
    for tok in _TOKEN.findall(normalise(text)):
        if tok.startswith("ال") and len(tok) > 4:
            tok = tok[2:]
        elif tok.startswith("لل") and len(tok) > 5:
            tok = tok[2:]
        elif tok.startswith(("و", "ب", "ل", "ف")) and len(tok) > 5 and tok[1:3] == "ال":
            tok = tok[3:]
        if tok.endswith("s") and len(tok) > 4 and not tok.endswith("ss"):
            tok = tok[:-1]
        out.append(tok)
    return out


def content_tokens(text: str) -> list[str]:
    return [t for t in tokens(text) if t not in STOPWORDS_EN and t not in STOPWORDS_AR and len(t) > 1]


def passage_tokens(p: CorpusPassage) -> set[str]:
    toks: set[str] = set()
    for kw in p.keywords or []:
        toks.update(tokens(kw))
    toks.update(tokens(p.text_en))
    toks.update(tokens(p.text_ar))
    toks.update(tokens(p.subject))
    return toks


@dataclass
class Retrieval:
    passage: CorpusPassage
    score: float
    matched: list[str] = field(default_factory=list)


def retrieve(question: str, passages: list[CorpusPassage], *, on: date | None = None, limit: int = 5) -> list[Retrieval]:
    """Score every in-force answer-source passage by content-token overlap; deterministic ordering."""
    on = on or dubai_today()
    q = content_tokens(question)
    if not q:
        return []
    qset = set(q)
    out: list[Retrieval] = []
    for p in passages:
        if not p.answer_source or p.status != "in_force":
            continue
        if p.effective_from and p.effective_from > on:
            continue
        if p.effective_to and p.effective_to < on:
            continue
        ptoks = passage_tokens(p)
        matched = sorted(qset & ptoks)
        if not matched:
            continue
        score = round(len(matched) / len(qset), 4)
        out.append(Retrieval(passage=p, score=score, matched=matched))
    out.sort(key=lambda r: (-r.score, r.passage.rank, r.passage.passage_id))
    return out[:limit]


def detect_conflict(best: CorpusPassage, passages: list[CorpusPassage], *, on: date | None = None) -> bool:
    """Two in-force passages with the same subject, condition and taxpayer category, overlapping
    effective periods, different values and no supersedes link → conflict. Superseded without a successor → conflict."""
    on = on or dubai_today()
    if best.status == "superseded" and not any(p.supersedes == best.passage_id for p in passages):
        return True
    for other in passages:
        if other.passage_id == best.passage_id or other.status != "in_force":
            continue
        if (other.subject, other.condition or "", other.taxpayer_category) != (best.subject, best.condition or "", best.taxpayer_category):
            continue
        if (other.value or "") == (best.value or ""):
            continue
        if other.supersedes == best.passage_id or best.supersedes == other.passage_id:
            continue
        a_from, a_to = best.effective_from or date.min, best.effective_to or date.max
        b_from, b_to = other.effective_from or date.min, other.effective_to or date.max
        if a_from <= b_to and b_from <= a_to:
            return True
    return False


def question_kind(question: str) -> str:
    """'legal' | 'own_position' | 'information' from fixed pattern lists (no model, no free-written reason)."""
    n = normalise(question)
    if any(normalise(p) in n for p in LEGAL_PATTERNS):
        return "legal"
    if any(normalise(p) in n for p in OWN_POSITION_PATTERNS):
        return "own_position"
    return "information"


def detect_language(question: str) -> str:
    try:
        from app.modules.localmodel.client import language_class

        lc = language_class(question)
        return "ar" if lc in ("ar", "mixed") else "en"
    except ImportError:  # pragma: no cover
        return "ar" if re.search(r"[؀-ۿ]", question or "") else "en"


def citation_for(p: CorpusPassage, lang: str) -> dict:
    return {
        "passage_id": p.passage_id,
        "instrument": p.instrument,
        "instrument_ar": p.instrument_ar,
        "article": p.article,
        "corpus_version": p.corpus_version,
        "effective_from": p.effective_from.isoformat() if p.effective_from else None,
        "source_ref": p.source_ref,
        "source_language": "ar",
        "authoritative_language": "ar",
        "quoted_text_ar": p.text_ar,
        "text_en_unofficial": p.text_en,
        "shown_in_original_language": lang != "ar",
        "value_status": p.value_status,
        "owner_role": p.owner_role,
    }
