# -*- coding: utf-8 -*-
"""Authoritative message-body normalization.

Translation removal is deliberately conservative: only an exact, complete suffix
is removed and a non-empty original body must remain. No language/character
heuristics are used.
"""
import hashlib


def translation_text(metadata):
    if not isinstance(metadata, dict):
        return None
    value = metadata.get('translation')
    if not isinstance(value, dict) or not isinstance(value.get('text'), str):
        return None
    text = value['text'].strip()
    return text or None


def split_translation_suffix(body, metadata):
    """Return (canonical_body, changed), preserving the original if unsafe."""
    if not isinstance(body, str):
        return body, False
    translated = translation_text(metadata)
    if not translated:
        return body, False
    trimmed = body.strip()
    if trimmed == translated or not trimmed.endswith(translated):
        return body, False
    original = trimmed[:-len(translated)].rstrip()
    if not original:
        return body, False
    return original, original != body


def message_digest(text, direction, content_type, occurred_at):
    raw = (text or '') + '|' + str(direction) + '|' + str(content_type) + '|' + str(occurred_at)
    return hashlib.sha256(raw.encode()).hexdigest()
