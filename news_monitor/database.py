#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Database operations for news-monitor."""

import sqlite3
import logging
from datetime import datetime
from paths import get_db_path

logger = logging.getLogger(__name__)


def init_database():
    """Initialize the SQLite database and create tables if needed."""
    db_path = str(get_db_path())
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_name TEXT,
            title TEXT,
            translated_title TEXT,
            url TEXT,
            date TEXT,
            pushed INTEGER DEFAULT 0,
            llm_relevance INTEGER DEFAULT -1,
            llm_reason TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(site_name, title, url)
        )
    ''')
    # Backward-compatible column additions
    for col, ddl in [
        ('pushed', 'ALTER TABLE news ADD COLUMN pushed INTEGER DEFAULT 0'),
        ('llm_relevance', 'ALTER TABLE news ADD COLUMN llm_relevance INTEGER DEFAULT -1'),
        ('llm_reason', "ALTER TABLE news ADD COLUMN llm_reason TEXT DEFAULT ''"),
    ]:
        try:
            cursor.execute(ddl)
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()

    # Site stats table
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS site_stats (
            site_name TEXT PRIMARY KEY,
            last_check TIMESTAMP,
            last_success TIMESTAMP,
            last_error TEXT DEFAULT '',
            consecutive_errors INTEGER DEFAULT 0,
            total_checks INTEGER DEFAULT 0,
            total_success INTEGER DEFAULT 0,
            total_errors INTEGER DEFAULT 0,
            total_news INTEGER DEFAULT 0,
            last_news_count INTEGER DEFAULT 0,
            avg_response_time REAL DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()


def update_site_stats(site_name, success, news_count=0, error_msg='', response_time=0):
    """Update per-site scraping statistics."""
    try:
        conn = sqlite3.connect(str(get_db_path()))
        cursor = conn.cursor()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        cursor.execute(
            'SELECT total_checks, total_success, total_errors, total_news, avg_response_time, consecutive_errors FROM site_stats WHERE site_name = ?',
            (site_name,))
        row = cursor.fetchone()

        if row:
            total_checks = row[0] + 1
            total_success = row[1] + (1 if success else 0)
            total_errors = row[2] + (0 if success else 1)
            total_news = row[3] + news_count
            old_avg = row[4]
            avg_time = old_avg * 0.8 + response_time * 0.2 if old_avg > 0 else response_time
            consecutive = 0 if success else (row[5] + 1)

            cursor.execute('''
                UPDATE site_stats SET
                    last_check = ?,
                    last_success = CASE WHEN ? THEN ? ELSE last_success END,
                    last_error = CASE WHEN ? THEN '' ELSE ? END,
                    consecutive_errors = ?,
                    total_checks = ?,
                    total_success = ?,
                    total_errors = ?,
                    total_news = ?,
                    last_news_count = ?,
                    avg_response_time = ?
                WHERE site_name = ?
            ''', (now, success, now, success, error_msg, consecutive,
                  total_checks, total_success, total_errors, total_news,
                  news_count, round(avg_time, 2), site_name))
        else:
            cursor.execute('''
                INSERT INTO site_stats
                (site_name, last_check, last_success, last_error, consecutive_errors,
                 total_checks, total_success, total_errors, total_news, last_news_count, avg_response_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (site_name, now,
                  now if success else None,
                  '' if success else error_msg,
                  0 if success else 1,
                  1, 1 if success else 0, 0 if success else 1,
                  news_count, news_count, round(response_time, 2)))

        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"更新站点统计失败: {site_name}, {str(e)}")


def get_site_stats():
    """Get all site statistics."""
    try:
        conn = sqlite3.connect(str(get_db_path()))
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM site_stats ORDER BY last_check DESC')
        columns = [desc[0] for desc in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"获取站点统计失败: {str(e)}")
        return []


def filter_existing_news(news_items):
    """Filter out news items that already exist in the database."""
    if not news_items:
        return []
    conn = sqlite3.connect(str(get_db_path()))
    cursor = conn.cursor()
    existing = set()
    for item in news_items:
        cursor.execute(
            'SELECT 1 FROM news WHERE site_name=? AND title=? AND url=?',
            (item['site_name'], item['title'], item['url']))
        if cursor.fetchone():
            existing.add((item['site_name'], item['title'], item['url']))
    conn.close()
    return [item for item in news_items
            if (item['site_name'], item['title'], item['url']) not in existing]


def save_news(news_items):
    """Save news items to database. Returns (new_count, new_news_list)."""
    if not news_items:
        return 0, []
    conn = sqlite3.connect(str(get_db_path()))
    cursor = conn.cursor()
    new_count = 0
    new_news_list = []
    for item in news_items:
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO news
                (site_name, title, translated_title, url, date, llm_relevance, llm_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                item['site_name'],
                item['title'],
                item['translated_title'],
                item['url'],
                item['date'],
                item.get('llm_relevance', -1),
                item.get('llm_reason', '')
            ))
            if cursor.rowcount > 0:
                new_count += 1
                new_news_list.append(item)
        except Exception as e:
            logger.error(f"保存新闻失败: {str(e)}")
    conn.commit()
    conn.close()
    return new_count, new_news_list


def mark_as_pushed(news_list):
    """Mark news items as pushed."""
    if not news_list:
        return
    conn = sqlite3.connect(str(get_db_path()))
    cursor = conn.cursor()
    for item in news_list:
        try:
            cursor.execute(
                'UPDATE news SET pushed = 1 WHERE site_name = ? AND title = ? AND url = ?',
                (item['site_name'], item['title'], item['url']))
        except Exception as e:
            logger.error(f"标记已推送失败: {str(e)}")
    conn.commit()
    conn.close()


def mark_as_filtered(news_list):
    """Mark news items as filtered (pushed=2)."""
    if not news_list:
        return
    conn = sqlite3.connect(str(get_db_path()))
    cursor = conn.cursor()
    for item in news_list:
        try:
            cursor.execute(
                'UPDATE news SET pushed = 2 WHERE site_name = ? AND title = ? AND url = ?',
                (item['site_name'], item['title'], item['url']))
        except Exception as e:
            logger.error(f"标记主题无关失败: {str(e)}")
    conn.commit()
    conn.close()


def get_pending_count():
    """Count un-pushed news."""
    conn = sqlite3.connect(str(get_db_path()))
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM news WHERE pushed = 0')
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_unrated_count():
    """Count LLM-unscored news."""
    conn = sqlite3.connect(str(get_db_path()))
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM news WHERE llm_relevance = -1 AND pushed = 0')
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_pending_news():
    """Get all pending (unpushed) news items."""
    conn = sqlite3.connect(str(get_db_path()))
    cursor = conn.cursor()
    cursor.execute('''
        SELECT site_name, title, translated_title, url, date, llm_relevance
        FROM news WHERE pushed = 0
        ORDER BY created_at ASC
    ''')
    rows = cursor.fetchall()
    conn.close()
    return [{'site_name': r[0], 'title': r[1], 'translated_title': r[2],
             'url': r[3], 'date': r[4], 'llm_relevance': r[5]} for r in rows]


def get_unrated_news():
    """Get all LLM-unscored news items."""
    conn = sqlite3.connect(str(get_db_path()))
    cursor = conn.cursor()
    cursor.execute('''
        SELECT site_name, title, translated_title, url, date
        FROM news WHERE llm_relevance = -1 AND pushed = 0
        ORDER BY created_at DESC
    ''')
    rows = cursor.fetchall()
    conn.close()
    return [{'site_name': r[0], 'title': r[1], 'translated_title': r[2],
             'url': r[3], 'date': r[4]} for r in rows]


def update_llm_score(item):
    """Update LLM score for a single news item."""
    conn = sqlite3.connect(str(get_db_path()))
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE news SET llm_relevance = ?, llm_reason = ?, translated_title = ?
        WHERE site_name = ? AND title = ? AND url = ?
    ''', (
        item['llm_relevance'],
        item.get('llm_reason', ''),
        item.get('translated_title', ''),
        item['site_name'],
        item['title'],
        item['url']
    ))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0
