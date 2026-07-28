#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Config validation for news-monitor.

Returns (is_valid, errors_list). Used by both API and (via JSON) frontend.
"""

import re
from urllib.parse import urlparse


def validate_config(config):
    """Validate the full config dict. Returns (True, []) or (False, [errors])."""
    errors = []

    # ── Basic settings ──────────────────────────────────────
    ci = config.get('check_interval')
    if not isinstance(ci, (int, float)) or ci < 1:
        errors.append('检查间隔必须 ≥ 1 分钟')
    if ci > 1440:
        errors.append('检查间隔不能超过 1440 分钟 (24小时)')

    cw = config.get('concurrent_workers', 5)
    if not isinstance(cw, int) or cw < 1:
        errors.append('并发数必须 ≥ 1')
    if cw > 20:
        errors.append('并发数不能超过 20')

    df = config.get('date_filter_days', 0)
    if not isinstance(df, (int, float)) or df < 0:
        errors.append('日期过滤天数不能为负数')
    if df > 365:
        errors.append('日期过滤天数不能超过 365')

    if not isinstance(config.get('headless'), bool):
        errors.append('headless 必须为布尔值')

    # ── Notification ────────────────────────────────────────
    notif = config.get('notification', {})

    # Bark URLs
    for i, url in enumerate(notif.get('bark_urls', [])):
        if url and not _is_valid_url(url):
            errors.append(f'Bark URL #{i+1} 格式无效: {url}')

    # Server酱 keys
    for i, key in enumerate(notif.get('serverchan_keys', [])):
        if key and not re.match(r'^[A-Za-z0-9]+$', key):
            errors.append(f'Server酱密钥 #{i+1} 格式无效（只能包含字母数字）')

    # Email
    email = notif.get('email', {})
    if email.get('enabled'):
        if not email.get('smtp_server'):
            errors.append('邮件已启用但未填写 SMTP 服务器')
        port = email.get('smtp_port')
        if not isinstance(port, int) or port < 1 or port > 65535:
            errors.append(f'SMTP 端口无效: {port}')
        if not email.get('username'):
            errors.append('邮件已启用但未填写用户名')
        if not email.get('password'):
            errors.append('邮件已启用但未填写密码')
        if not email.get('to_addresses'):
            errors.append('邮件已启用但未填写收件人')

    # Webhooks
    wh = notif.get('webhooks', {})
    tg = wh.get('telegram', {})
    if tg.get('enabled'):
        if not tg.get('bot_token'):
            errors.append('Telegram 已启用但未填写 Bot Token')
        if not tg.get('chat_id'):
            errors.append('Telegram 已启用但未填写 Chat ID')

    for name in ['feishu', 'dingtalk', 'discord']:
        cfg = wh.get(name, {})
        if cfg.get('enabled') and not cfg.get('webhook_url'):
            errors.append(f'{name} 已启用但未填写 Webhook URL')
        if cfg.get('webhook_url') and not _is_valid_url(cfg['webhook_url']):
            errors.append(f'{name} Webhook URL 格式无效')

    # ── Translation ─────────────────────────────────────────
    trans = config.get('translation', {})
    if trans.get('enabled'):
        if not trans.get('api_url'):
            errors.append('翻译已启用但未填写 API 地址')
        elif not _is_valid_url(trans['api_url']):
            errors.append('翻译 API 地址格式无效')

    # ── LLM filter ──────────────────────────────────────────
    llm = config.get('llm_filter', {})
    if llm.get('enabled'):
        if not llm.get('api_key'):
            errors.append('LLM筛选已启用但未填写 API Key')
        if not llm.get('api_url'):
            errors.append('LLM筛选已启用但未填写 API 地址')
        elif not _is_valid_url(llm['api_url']):
            errors.append('LLM API 地址格式无效')
        threshold = llm.get('relevance_threshold', 60)
        if not isinstance(threshold, (int, float)) or threshold < 0 or threshold > 100:
            errors.append('相关性阈值必须在 0-100 之间')

    # ── Push mode ───────────────────────────────────────────
    push = config.get('push', {})
    if push.get('mode') == 'scheduled':
        times = push.get('scheduled_times', [])
        if not times:
            errors.append('定时推送模式已启用但未设置推送时间')
        for t in times:
            if not re.match(r'^\d{2}:\d{2}$', str(t)):
                errors.append(f'推送时间格式无效，应为 HH:MM: {t}')

    # ── Keyword filters ─────────────────────────────────────
    kw = config.get('keyword_filters', {})
    if kw.get('enabled'):
        rules = kw.get('rules', [])
        active = [r for r in rules if r.get('enabled', True)]
        if not active:
            errors.append('关键词筛选已启用但没有有效的规则')
        for i, rule in enumerate(rules):
            if rule.get('enabled', True) and not rule.get('keywords'):
                errors.append(f'关键词规则 #{i+1} 没有关键词')
            mode = rule.get('mode', 'or')
            if mode not in ('or', 'and'):
                errors.append(f'关键词规则 #{i+1} 匹配模式无效: {mode}（应为 or 或 and）')

    return len(errors) == 0, errors


def _is_valid_url(url):
    """Basic URL validation."""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False
