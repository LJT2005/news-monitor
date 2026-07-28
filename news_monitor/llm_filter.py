#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM-based news scoring and filtering via OpenAI-compatible API."""

import re
import json
import time
import logging
import requests

logger = logging.getLogger(__name__)


def _parse_llm_json(content):
    """Extract JSON object from LLM response, filtering out explanatory text."""
    if not content:
        return None

    content = re.sub(r'```(?:json)?\s*', '', content)
    content = re.sub(r'```', '', content)
    content = content.strip()

    # Direct parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Extract first complete JSON object (supports nesting)
    depth = 0
    start = -1
    for i, ch in enumerate(content):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(content[start:i + 1])
                except json.JSONDecodeError:
                    start = -1

    # Regex fallback
    match = re.search(r'\{[^{}]+\}', content)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


def match_keyword_rules(news_item, keyword_config):
    """Check if a news item matches user-defined keyword rules."""
    if not keyword_config.get('enabled', False):
        return True

    rules = keyword_config.get('rules', [])
    active_rules = [r for r in rules if r.get('enabled', True) and r.get('keywords')]
    if not active_rules:
        return True

    title = (news_item.get('title', '') or '').lower()
    translated_title = (news_item.get('translated_title', '') or '').lower()
    match_text = f"{title} {translated_title}"

    for rule in active_rules:
        keywords = [kw.lower() for kw in rule['keywords'] if kw.strip()]
        if not keywords:
            continue
        mode = rule.get('mode', 'or')
        if mode == 'or' and any(kw in match_text for kw in keywords):
            return True
        if mode == 'and' and all(kw in match_text for kw in keywords):
            return True

    return False


def llm_score_news(news_items, llm_config, translate_fn=None):
    """Score news relevance using LLM API and optionally translate titles.

    Updates each item in-place with: llm_relevance, llm_reason, translated_title.
    Returns the (possibly modified) news_items list.
    """
    if not llm_config.get('enabled', False):
        return news_items

    api_url = llm_config.get('api_url', '')
    api_key = llm_config.get('api_key', '')
    model = llm_config.get('model', 'deepseek-v4-flash')
    user_prompt = llm_config.get('user_prompt', '')
    max_retries = llm_config.get('max_retries', 2)

    if not api_key:
        logger.warning("LLM筛选已启用但未配置API密钥，跳过打分")
        return news_items

    system_prompt = (
        '你是一个新闻筛选和翻译助手。根据用户提供的筛选主题，判断新闻标题的相关性，并将英文标题翻译为中文。\n'
        '\n'
        '【输出要求】\n'
        '- 只输出一个JSON对象，不要输出任何其他文字、解释、说明或markdown标记\n'
        '- 不要输出```json```代码块标记\n'
        '- 不要在JSON前后添加任何内容\n'
        '- translation字段必须为非空的中文翻译，不得留空或返回原文\n'
        '\n'
        '【JSON格式】\n'
        '{"relevance":0-100的整数,"reason":"中文理由","translation":"中文翻译"}'
    )

    for item in news_items:
        title = item.get('title', '')
        if not title:
            continue

        success = False
        for attempt in range(1, max_retries + 1):
            try:
                full_user_prompt = f"{user_prompt}\n\n新闻标题：{title}"
                response = requests.post(
                    api_url,
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {api_key}'
                    },
                    json={
                        'model': model,
                        'messages': [
                            {'role': 'system', 'content': system_prompt},
                            {'role': 'user', 'content': full_user_prompt}
                        ],
                        'temperature': 0.1,
                        'max_tokens': 256
                    },
                    timeout=30
                )
                if response.status_code == 200:
                    result = response.json()
                    content = result['choices'][0]['message']['content']
                    llm_result = _parse_llm_json(content)
                    if llm_result:
                        relevance = llm_result.get('relevance', 0)
                        translated = (llm_result.get('translation') or '').strip()
                        if not translated or translated == title:
                            if translate_fn:
                                translated = translate_fn(title)
                        item['translated_title'] = translated
                        item['llm_relevance'] = relevance
                        item['llm_reason'] = llm_result.get('reason', '')
                        success = True
                        break
                    else:
                        logger.warning(f"LLM返回格式异常(第{attempt}次): {content[:200]}")
                else:
                    logger.error(f"LLM API请求失败(第{attempt}次): {response.status_code}")
            except Exception as e:
                logger.error(f"LLM打分异常(第{attempt}次): {str(e)}")

            if attempt < max_retries:
                time.sleep(1)

        if not success:
            logger.warning(f"LLM打分{max_retries}次重试均失败: {title}")

    return news_items
