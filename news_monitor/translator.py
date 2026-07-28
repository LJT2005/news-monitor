#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Translation module — DeepLX API integration."""

import logging
import requests

logger = logging.getLogger(__name__)


def translate_text(text, translation_config):
    """Translate text using DeepLX API. Returns original text if translation is disabled or fails."""
    if not translation_config.get('enabled', False):
        return text

    try:
        api_url = translation_config['api_url']
        api_key = translation_config['api_key']

        headers = {'Content-Type': 'application/json'}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'

        data = {
            'text': text,
            'source_lang': 'EN',
            'target_lang': 'ZH'
        }

        response = requests.post(api_url, json=data, headers=headers, timeout=10)

        if response.status_code == 200:
            result = response.json()
            if result.get('code') == 200:
                return result.get('data', text)
            else:
                logger.warning(f"翻译API返回错误: {result}")
        else:
            logger.error(f"翻译API请求失败，状态码: {response.status_code}")
    except Exception as e:
        logger.error(f"翻译失败: {str(e)}")

    return text
