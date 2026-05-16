"""Unit tests for the classifier — no DB or API required."""
import pytest
from app.services.classifier import classify_email


def test_classifies_spam():
    email = {"subject": "You won the lottery! Claim your prize now", "snippet": "", "sender": "noreply@spam.biz", "sender_email": "noreply@spam.biz", "labels": ""}
    result = classify_email(email)
    assert result.label == "spam"


def test_classifies_promotions():
    email = {"subject": "50% off sale — limited time deal!", "snippet": "Unsubscribe here", "sender": "deals@shop.com", "sender_email": "deals@shop.com", "labels": ""}
    result = classify_email(email)
    assert result.label == "promotions"


def test_classifies_social():
    email = {"subject": "John liked your post", "snippet": "", "sender": "noreply@facebook.com", "sender_email": "noreply@facebook.com", "labels": ""}
    result = classify_email(email)
    assert result.label == "social"


def test_trusts_gmail_spam_label():
    email = {"subject": "Hello", "snippet": "", "sender": "a@b.com", "sender_email": "a@b.com", "labels": "SPAM"}
    result = classify_email(email)
    assert result.label == "spam"
    assert result.source == "gmail_label"
