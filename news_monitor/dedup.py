#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""News deduplication via title similarity (difflib.SequenceMatcher)."""

import logging
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.85


def find_similar(news_items, existing_titles):
    """Find existing news with very similar titles.

    Args:
        news_items: list of new items with 'title' and 'site_name'
        existing_titles: list of (id, title, site_name) tuples from DB

    Returns: dict mapping {new_item_idx: (existing_id, existing_title, ratio)}
    """
    matches = {}
    for idx, item in enumerate(news_items):
        title_a = _normalize(item.get('title', ''))
        if not title_a:
            continue
        for ex_id, ex_title, ex_site in existing_titles:
            # Skip same source (likely same article)
            if ex_site == item.get('site_name'):
                continue
            title_b = _normalize(ex_title)
            if not title_b:
                continue
            ratio = SequenceMatcher(None, title_a, title_b).ratio()
            if ratio >= SIMILARITY_THRESHOLD:
                matches[idx] = (ex_id, ex_title, round(ratio * 100))
                logger.info(f"重复检测: \"{title_a[:50]}...\" ≈ \"{title_b[:50]}...\" ({ratio*100:.0f}%)")
                break  # one match is enough
    return matches


def mark_duplicates(cursor, matches, news_items, inserted_ids):
    """Mark newly inserted news as duplicates of existing ones.

    Args:
        cursor: active DB cursor
        matches: dict from find_similar
        news_items: original new items list
        inserted_ids: list of (site_name, title, url, new_id) for just-inserted rows
    """
    for new_idx, (ex_id, ex_title, ratio) in matches.items():
        item = news_items[new_idx]
        # Find the rowid of the just-inserted row
        for ins_site, ins_title, ins_url, ins_id in inserted_ids:
            if ins_title == item['title']:
                cursor.execute(
                    'UPDATE news SET duplicate_of = ? WHERE id = ?',
                    (ex_id, ins_id))
                break


def _normalize(title):
    """Normalize title for comparison: lowercase, strip punctuation."""
    import re
    t = title.lower().strip()
    t = re.sub(r'[^\w\s]', '', t)
    t = re.sub(r'\s+', ' ', t)
    return t
