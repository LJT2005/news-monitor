#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Configuration management for news-monitor."""

import json
import logging
from paths import get_config_path

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    'check_interval': 60,
    'concurrent_workers': 5,
    'date_filter_days': 0,
    'headless': False,
    'notification': {
        'bark_urls': [],
        'serverchan_keys': [],
        'bark_url': '',
        'serverchan_key': '',
        'email': {
            'enabled': False,
            'smtp_server': '',
            'smtp_port': 465,
            'use_ssl': True,
            'username': '',
            'password': '',
            'from_address': '',
            'to_addresses': []
        },
        'webhooks': {
            'telegram': {'enabled': False, 'bot_token': '', 'chat_id': ''},
            'feishu': {'enabled': False, 'webhook_url': ''},
            'dingtalk': {'enabled': False, 'webhook_url': ''},
            'discord': {'enabled': False, 'webhook_url': ''},
        }
    },
    'translation': {
        'api_key': '',
        'api_url': '',
        'enabled': False
    },
    'keyword_filters': {
        'enabled': False,
        'rules': []
    },
    'push': {
        'mode': 'immediate',
        'scheduled_times': ['09:00', '18:00'],
    },
    'llm_filter': {
        'enabled': False,
        'api_url': 'https://api.deepseek.com/v1/chat/completions',
        'api_key': '',
        'model': 'deepseek-v4-flash',
        'user_prompt': '筛选与以下主题相关的新闻：国际经济、金融市场、科技发展、地缘政治',
        'relevance_threshold': 60,
        'max_retries': 2
    },
    'news_sites': []
}


def load_config(config):
    """Load config file, merging with defaults."""
    default = dict(DEFAULT_CONFIG)
    try:
        config_path = str(get_config_path())
        if config_path and __import__('os').path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            # Deep merge: only override keys present in loaded
            for key, value in loaded.items():
                if key in default and isinstance(default[key], dict) and isinstance(value, dict):
                    default[key].update(value)
                else:
                    default[key] = value
    except Exception as e:
        logger.error(f"加载配置文件失败: {str(e)}")

    # Ensure news_sites exist
    if not default.get('news_sites'):
        default['news_sites'] = get_default_news_sites()
    else:
        # Merge: add any default sites not present in config
        default_sites = get_default_news_sites()
        existing_names = {s['name'] for s in default['news_sites']}
        for site in default_sites:
            if site['name'] not in existing_names:
                default['news_sites'].append(site)

    return default


def save_config(config):
    """Save config to file."""
    try:
        config_path = str(get_config_path())
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        logger.info(f"配置已保存: {config_path}")
    except Exception as e:
        logger.error(f"保存配置失败: {str(e)}")


def get_default_news_sites():
    """Return the built-in list of default news sites."""
    return _DEFAULT_NEWS_SITES


def restore_default_news_sites(config):
    """Replace config news_sites with defaults (preserving enablement from defaults)."""
    config['news_sites'] = get_default_news_sites()
    save_config(config)
    logger.info("已恢复默认新闻源列表")
    return get_default_news_sites()


# ── Default news sites ──────────────────────────────────────────────
_DEFAULT_NEWS_SITES = [
    {"name": "IMF", "url": "https://www.imf.org/en/Publications/RSS?language=eng&series=IMF%20Working%20Papers", "site_type": "rss", "title_selector": ".container__headline-text", "date_selector": ".timestamp", "date_format": "%Y-%m-%d", "enabled": True},
    {"name": "世界银行", "url": "https://documents.worldbank.org/en/publication/documents-reports/documentlist?docty_exact=Policy%2BResearch%2BWorking%2BPaper", "site_type": "html", "title_selector": "div.search-listing-content > h3 > a.ng-tns-c0-0", "date_selector": "div.search-listing-content > div > span:nth-child(3)", "date_format": "%B %-d, %Y", "enabled": True},
    {"name": "国际清算银行-Papers", "url": "https://www.bis.org/doclist/bispapers.rss", "site_type": "rss", "title_selector": 'h3[data-testid=', "date_selector": "time", "date_format": "%Y-%m-%d", "enabled": True},
    {"name": "国际清算银行-Working papers", "url": "https://www.bis.org/doclist/wppubls.rss", "site_type": "rss", "title_selector": 'h3[data-testid=', "date_selector": "time", "date_format": "%Y-%m-%d", "enabled": True},
    {"name": "亚洲开发银行", "url": "https://www.adb.org/publications/series/economics-working-papers", "site_type": "html", "title_selector": "li.clearfix > a", "date_selector": "time", "date_format": "%d %b %Y", "enabled": True},
    {"name": "亚太经合组织", "url": "https://www.apec.org/apecapi/publication/getpublications?keyword=&type=&fromDate=&toDate=&sort=&page=1", "site_type": "api", "base_url": "https://www.apec.org", "title_selector": "", "date_selector": "", "date_format": "%B %Y", "enabled": True},
    {"name": "亚太经合组织-新闻", "url": "https://www.apec.org/apecapi/article/getarticleswithfilters?listingType=749e45d0-485d-4283-883a-e94445934bf9%7C9c4616f2-d623-42a1-8755-e01269234bb1%7Ce270d054-e65c-4dd6-9b81-7a807e9862d8%7C1f82ea4b-ec75-4581-a7b5-d53dd7ef3592%7C99f65abc-265b-4b1f-a296-b10a93d76f64%7C0052e8e7-9448-4751-8c7b-978a8237fa35&year=&keyword=&page=1", "site_type": "api", "base_url": "https://www.apec.org", "title_selector": "", "date_selector": "", "date_format": "%B %d, %Y", "enabled": True},
    {"name": "美联储-feds", "url": "https://www.federalreserve.gov/feeds/feds.xml", "site_type": "rss", "title_selector": 'h3[data-testid=', "date_selector": "time", "date_format": "%Y-%m-%d", "enabled": True},
    {"name": "美联储-feds_notes", "url": "https://www.federalreserve.gov/feeds/feds_notes.xml", "site_type": "rss", "title_selector": 'h3[data-testid=', "date_selector": "time", "date_format": "%Y-%m-%d", "enabled": True},
    {"name": "美联储-ifdp", "url": "https://www.federalreserve.gov/feeds/ifdp.xml", "site_type": "rss", "title_selector": 'h3[data-testid=', "date_selector": "time", "date_format": "%Y-%m-%d", "enabled": True},
    {"name": "Hoover", "url": "https://www.hoover.org/research/type/working-papers", "site_type": "html", "title_selector": "div > div.content > h6", "date_selector": ".name-date span.date", "date_format": "%B %-d, %Y", "enabled": True},
    {"name": "欧洲央行", "url": "https://www.ecb.europa.eu/press/research-publications/working-papers/html/index.en.html", "site_type": "html", "title_selector": "div.title > a", "date_selector": ".foedb-plugin dl dt", "date_format": "%d %B %Y", "enabled": True},
    {"name": "美国布鲁金斯学会", "url": "https://www.brookings.edu/programs/economic-studies/explore-research-and-commentary/", "site_type": "html", "title_selector": "article > a > span", "date_selector": "p.date", "date_format": "%Y-%m-%d", "enabled": True},
    {"name": "美国经济研究局", "url": "https://www.nber.org/papers?page=1&perPage=50&sortBy=public_date", "site_type": "html", "title_selector": "div.digest-card__title > a", "date_selector": ".digest-card__date .digest-card__label", "date_format": "%B %Y", "enabled": True},
    {"name": "彼得森研究所（PIIE）", "url": "https://www.piie.com/publications/working-papers", "site_type": "html", "title_selector": "h2.teaser__title > a", "date_selector": "p.teaser__date > time", "date_format": "%Y-%m-%d", "enabled": False},
    {"name": "哈德逊研究所", "url": "https://www.hudson.org/search?hud-content-type=258&expert=&date-from=&date-to=&keywords=&topics=All&region=All", "site_type": "html", "title_selector": "a.c-horizontal-card__title > span", "date_selector": "div.c-horizontal-card__meta > div.c-horizontal-card__date > div > time", "date_format": "%Y-%m-%d", "enabled": False},
    {"name": "布鲁盖尔研究所", "url": "https://www.bruegel.org/publications/working-papers", "site_type": "html", "title_selector": "h2.c-list-item__title > a > span", "date_selector": "p.c-list-item__date", "date_format": "%Y-%m-%d", "enabled": True},
    {"name": "法国央行", "url": "https://www.banque-france.fr/en/publications-and-statistics/publications", "site_type": "html", "title_selector": "span.title-truncation", "date_selector": "div.card-body.py-4.px-5.d-flex.flex-column > small", "date_format": "%Y-%m-%d", "enabled": False},
    {"name": "日本央行", "url": "https://www.boj.or.jp/en/research/wps_rev/index.htm", "site_type": "html", "title_selector": "tbody > tr > td:nth-child(4)", "date_selector": "li.news_list-li time.time", "date_format": "%Y-%m-%d", "enabled": True},
    {"name": "加拿大央行", "url": "https://www.bankofcanada.ca/feed/?content_type=working-papers&post_type%5B0%5D=post&post_type%5B1%5D=page", "site_type": "rss", "title_selector": 'h3[data-testid=', "date_selector": "time", "date_format": "%Y-%m-%d", "enabled": True},
]
