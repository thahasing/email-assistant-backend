"""
services/classifier.py
=======================
Email classification engine — Phase 1 uses rules, Phase 2 blends in sender scores.

Classification labels:
  "important"   — Emails the user likely needs to act on
  "promotions"  — Marketing, newsletters, deals
  "spam"        — Likely junk
  "social"      — Social network notifications
  "updates"     — Transactional (receipts, shipping, account notices)

How the scoring works:
  1. Rule-based signals each add or subtract from a score per category
  2. Sender score (from behavior_tracker) is added as a learned signal
  3. The category with the highest score wins

This is intentionally simple — no external ML model is required.
The "learning" comes from the sender_score table, which is updated
every time the user interacts with an email.
"""

import re
from dataclasses import dataclass, field
from app.models.sender_score import SenderScore
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)


# ── Keyword patterns for rule-based scoring ───────────────────────────────────

PROMOTION_KEYWORDS = [
    r"\bsale\b", r"\bdiscount\b", r"\boffer\b", r"\bpromo\b",
    r"\bunsubscribe\b", r"\bnewsletter\b", r"\b\d+%\s*off\b",
    r"\bdeal\b", r"\blimited time\b", r"\bfree shipping\b",
    r"\bclick here\b", r"\bopt.out\b",
]

SPAM_KEYWORDS = [
    r"\bviagra\b", r"\bcasino\b", r"\blottery\b", r"\bwon\b.*\bprize\b",
    r"\burgent\b.*\baction\b", r"\bverify your account\b",
    r"\bclaim your reward\b", r"\byou.ve been selected\b",
    r"\bmake money\b", r"\bwork from home\b",
]

SOCIAL_DOMAINS = [
    "facebook.com", "twitter.com", "instagram.com", "linkedin.com",
    "tiktok.com", "reddit.com", "pinterest.com", "nextdoor.com",
]

UPDATE_KEYWORDS = [
    r"\breceipt\b", r"\border\b.*\bconfirm", r"\bshipping\b",
    r"\bdelivered\b", r"\binvoice\b", r"\bstatement\b",
    r"\bpassword\b.*\breset\b", r"\bverification code\b",
    r"\byour account\b",
]

IMPORTANT_SIGNALS = [
    r"\baction required\b", r"\bimportant\b", r"\burgent\b",
    r"\bfyi\b", r"\bfollowing up\b", r"\bmeeting\b", r"\binterview\b",
    r"\bdeadline\b", r"\bplease review\b",
]


@dataclass
class ClassificationResult:
    label: str
    confidence: float
    source: str = "rules"
    scores: dict = field(default_factory=dict)  # Full score breakdown for debugging


def _count_pattern_matches(text: str, patterns: list[str]) -> int:
    """Count how many regex patterns match in a text string."""
    text_lower = text.lower()
    return sum(1 for p in patterns if re.search(p, text_lower))


def classify_email(
    email_data: dict,
    db: Session | None = None,
) -> ClassificationResult:
    """
    Classify a single email.

    Args:
        email_data: Dict with keys: subject, sender, sender_email, snippet, labels
        db:         Optional DB session. If provided, sender scores are incorporated.

    Returns:
        ClassificationResult with label, confidence, and raw scores.
    """
    subject      = email_data.get("subject", "") or ""
    sender       = email_data.get("sender", "") or ""
    sender_email = email_data.get("sender_email", "") or ""
    snippet      = email_data.get("snippet", "") or ""
    gmail_labels = email_data.get("labels", "") or ""

    # Combined text blob for keyword matching
    full_text = f"{subject} {snippet}"

    # ── Phase 0: Trust Gmail's own labels first ───────────────────────────────
    if "SPAM" in gmail_labels:
        return ClassificationResult(label="spam", confidence=0.95, source="gmail_label")
    if "CATEGORY_PROMOTIONS" in gmail_labels:
        return ClassificationResult(label="promotions", confidence=0.90, source="gmail_label")
    if "CATEGORY_SOCIAL" in gmail_labels:
        return ClassificationResult(label="social", confidence=0.90, source="gmail_label")
    if "CATEGORY_UPDATES" in gmail_labels:
        return ClassificationResult(label="updates", confidence=0.85, source="gmail_label")
    if "IMPORTANT" in gmail_labels:
        # Gmail flagged as important, but still run our own scoring
        pass

    # ── Phase 1: Rule-based scoring ───────────────────────────────────────────
    scores = {
        "important":  0.0,
        "promotions": 0.0,
        "spam":       0.0,
        "social":     0.0,
        "updates":    0.0,
    }

    # Score promotions
    promo_hits = _count_pattern_matches(full_text, PROMOTION_KEYWORDS)
    scores["promotions"] += promo_hits * 1.5

    # Score spam
    spam_hits = _count_pattern_matches(full_text, SPAM_KEYWORDS)
    scores["spam"] += spam_hits * 2.0

    # Score social
    sender_domain = sender_email.split("@")[-1] if "@" in sender_email else ""
    if any(d in sender_domain for d in SOCIAL_DOMAINS):
        scores["social"] += 4.0

    # Score updates
    update_hits = _count_pattern_matches(full_text, UPDATE_KEYWORDS)
    scores["updates"] += update_hits * 1.5

    # Score important
    important_hits = _count_pattern_matches(full_text, IMPORTANT_SIGNALS)
    scores["important"] += important_hits * 2.0
    if "IMPORTANT" in gmail_labels:
        scores["important"] += 3.0

    # ── Phase 2: Blend in learned sender score ────────────────────────────────
    if db and sender_email:
        sender_record = db.query(SenderScore).filter(
            SenderScore.sender_email == sender_email
        ).first()

        if sender_record:
            learned_score = sender_record.importance_score  # -10 to +10
            # Positive score boosts "important", negative boosts "spam/promotions"
            if learned_score > 0:
                scores["important"] += learned_score * 0.8
            elif learned_score < -3:
                scores["spam"] += abs(learned_score) * 0.5
            elif learned_score < 0:
                scores["promotions"] += abs(learned_score) * 0.4

    # ── Determine winner ──────────────────────────────────────────────────────
    # Default to "updates" if no strong signal
    if max(scores.values()) < 1.0:
        return ClassificationResult(
            label="updates", confidence=0.5, source="default", scores=scores
        )

    winner = max(scores, key=scores.get)
    total  = sum(scores.values()) or 1
    confidence = min(scores[winner] / total, 0.99)

    source = "rules" if db is None else "rules+behavior"

    return ClassificationResult(
        label=winner,
        confidence=round(confidence, 3),
        source=source,
        scores=scores,
    )


def classify_batch(emails: list[dict], db: Session | None = None) -> list[ClassificationResult]:
    """Classify a list of emails. Returns results in the same order."""
    return [classify_email(e, db=db) for e in emails]
