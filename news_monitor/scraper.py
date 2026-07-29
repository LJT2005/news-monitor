#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web scraping module for news-monitor.

Provides:
- WebDriver factory (Selenium + Chrome)
- RSS / HTML / API scrapers
- Date parsing and filtering utilities
"""

import re
import time
import hashlib
import logging
from datetime import datetime, timedelta
from functools import lru_cache
from urllib.parse import urljoin

import requests
import feedparser
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

logger = logging.getLogger(__name__)

# ── Retry with backoff ──────────────────────────────────────────────

_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def _fetch_with_retry(url, headers=None, timeout=30, max_retries=3):
    """Fetch URL with exponential backoff on transient errors.

    Retries: timeout, connection errors, 429, 5xx.
    Does NOT retry: 403, 404 (permanent failures).
    """
    headers = headers or {}
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code in _RETRYABLE_STATUSES and attempt < max_retries:
                delay = 5 * (2 ** (attempt - 1))  # 5, 10, 20 seconds
                logger.debug(f"{url[:60]} 返回 {resp.status_code}，{delay}s 后重试 ({attempt}/{max_retries})")
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp.content
        except (requests.Timeout, requests.ConnectionError) as e:
            last_exc = e
            if attempt < max_retries:
                delay = 5 * (2 ** (attempt - 1))
                logger.debug(f"{url[:60]} {type(e).__name__}，{delay}s 后重试 ({attempt}/{max_retries})")
                time.sleep(delay)
            else:
                raise
        except requests.HTTPError:
            raise  # 4xx non-retryable — propagate immediately
    raise last_exc  # all retries exhausted


# ── URL cache (5-min TTL, avoids re-fetching same URL within a check cycle) ──
_url_cache = {}
_CACHE_TTL = 300  # seconds


def _cache_key(url, site_type):
    return f"{site_type}:{url}"


def _cached_fetch(url, headers=None, timeout=30):
    """Fetch URL with cache. Returns (content, from_cache)."""
    key = _cache_key(url, 'fetch')
    now = time.time()
    if key in _url_cache:
        entry = _url_cache[key]
        if now - entry['time'] < _CACHE_TTL:
            logger.debug(f"缓存命中: {url[:60]}")
            return entry['content'], True
    try:
        content = _fetch_with_retry(url, headers=headers or {}, timeout=timeout)
        _url_cache[key] = {'content': content, 'time': now}
        return content, False
    except Exception:
        raise


# ── WebDriver ───────────────────────────────────────────────────────

def create_webdriver(headless=False):
    """Create a Chrome WebDriver with anti-detection measures."""
    chrome_options = Options()

    if headless:
        chrome_options.add_argument('--headless=new')

    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument(
        '--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('--disable-infobars')
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_argument('--disable-popup-blocking')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_experimental_option("prefs", {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
    })

    # Prefer webdriver-manager for automatic driver management
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        driver_path = ChromeDriverManager().install()
        import pathlib
        import stat as st
        driver_dir = pathlib.Path(driver_path).parent
        actual_driver = driver_dir / 'chromedriver'
        if actual_driver.exists() and actual_driver.is_file():
            driver_path = str(actual_driver)
            if not (actual_driver.stat().st_mode & st.S_IXUSR):
                actual_driver.chmod(actual_driver.stat().st_mode | st.S_IXUSR | st.S_IXGRP | st.S_IXOTH)
                logger.info(f"已修复 chromedriver 执行权限: {driver_path}")
        service = Service(driver_path)
        logger.info(f"使用 webdriver-manager 自动管理 ChromeDriver: {driver_path}")
    except Exception as e:
        service = Service()
        logger.info(f"使用系统 PATH 中的 ChromeDriver (webdriver-manager 失败: {e})")

    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(60)
    driver.set_script_timeout(30)

    # Anti-detection scripts via CDP
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': '''
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            window.chrome = { runtime: {} };
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
            );
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) return 'Intel Inc.';
                if (parameter === 37446) return 'Intel Iris OpenGL Engine';
                return getParameter.apply(this, arguments);
            };
        '''
    })
    return driver


# ── Date utilities ──────────────────────────────────────────────────

def parse_date_string(date_str, date_format=None):
    """Parse various date string formats, returning a datetime or None."""
    if not date_str:
        return None

    date_str = date_str.strip()
    formats_to_try = []

    if date_format:
        formats_to_try.append(date_format)

    # Common formats to try
    formats_to_try.extend([
        '%Y-%m-%d',
        '%Y/%m/%d',
        '%d %B %Y',
        '%B %d, %Y',
        '%B %-d, %Y',
        '%b %d, %Y',
        '%d %b %Y',
        '%d-%b-%Y',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%d %H:%M:%S',
    ])

    for fmt in formats_to_try:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    # Try parsing ISO-8601
    try:
        return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        pass

    # Regex fallback: extract YYYY-MM-DD
    match = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', date_str)
    if match:
        try:
            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            pass

    return None


def is_within_date_filter(date_str, date_format=None, days=0):
    """Check if a date is within the filter window (days=0 means no filter)."""
    if days <= 0:
        return True
    parsed = parse_date_string(date_str, date_format)
    if parsed is None:
        return True  # Can't parse, don't filter out
    cutoff = datetime.now() - timedelta(days=days)
    return parsed >= cutoff


# ── Scrapers ────────────────────────────────────────────────────────

def scrape_rss_site(site_config, date_filter_days=0, translate_fn=None):
    """Scrape an RSS news site."""
    if not site_config.get('enabled', True):
        return []

    try:
        logger.info(f"开始抓取RSS {site_config['name']}")
        content, cached = _cached_fetch(site_config['url'], headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
            'Accept': 'application/rss+xml, application/xml, text/xml, */*'
        })
        if cached:
            logger.debug(f"RSS {site_config['name']} 使用缓存")
        feed = feedparser.parse(content)

        if feed.bozo:
            logger.warning(f"RSS解析可能有问题: {site_config['name']}")

        news_items = []
        for entry in feed.entries:
            title = entry.get('title', '').strip()
            if not title:
                continue

            url = entry.get('link', site_config['url'])
            date_str = datetime.now().strftime('%Y-%m-%d')

            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try:
                    date_str = datetime(*entry.published_parsed[:6]).strftime('%Y-%m-%d')
                except Exception:
                    pass
            elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                try:
                    date_str = datetime(*entry.updated_parsed[:6]).strftime('%Y-%m-%d')
                except Exception:
                    pass

            if not is_within_date_filter(date_str, days=date_filter_days):
                continue

            translated_title = translate_fn(title) if translate_fn else title
            news_items.append({
                'site_name': site_config['name'],
                'title': title,
                'translated_title': translated_title,
                'url': url,
                'date': date_str
            })

        logger.info(f"从RSS {site_config['name']} 获取到 {len(news_items)} 条新闻")
        return news_items

    except Exception as e:
        logger.error(f"抓取RSS {site_config['name']} 失败: {str(e)}")
        return []


def scrape_html_site_light(site_config, date_filter_days=0, translate_fn=None):
    """Lightweight HTML scraper using requests+BS4 (no browser).
    
    Returns (news_items, success). If success=False, caller should fall back to Selenium.
    """
    if not site_config.get('enabled', True):
        return [], False

    try:
        logger.info(f"轻量抓取HTML {site_config['name']}")
        content, cached = _cached_fetch(site_config['url'], headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'
        })
        if cached:
            logger.debug(f"HTML {site_config['name']} 使用缓存")

        soup = BeautifulSoup(content, 'html.parser')
        title_elements = soup.select(site_config['title_selector'])

        if len(title_elements) == 0:
            logger.warning(f"{site_config['name']} 主选择器失效，尝试通用降级选择器")
            title_elements = _fallback_select_titles(soup, site_config['name'])

        if len(title_elements) == 0:
            logger.debug(f"轻量抓取 {site_config['name']} 未找到标题元素，降级到 Selenium")
            return [], False

        news_items = _parse_html_titles(
            title_elements, site_config, soup, date_filter_days, translate_fn)
        
        if len(news_items) == 0:
            logger.debug(f"轻量抓取 {site_config['name']} 无有效新闻，降级到 Selenium")
            return [], False

        logger.info(f"轻量抓取HTML {site_config['name']} 获取到 {len(news_items)} 条新闻")
        return news_items, True

    except Exception as e:
        logger.debug(f"轻量抓取 {site_config['name']} 失败: {e}，降级到 Selenium")
        return [], False


def _fallback_select_titles(soup, site_name):
    """Generic CSS fallback chain when primary selector fails.

    Level 1: Common article/link patterns (article a, h3 a, .title a, etc.)
    Level 2: All <a> tags with text 15-300 chars
    Level 3: All <h1>-<h4> tags with parent <a>
    """
    # Level 1: broad but sensible patterns
    level1 = soup.select(
        'article a[href], '
        '.post a[href], '
        '.card a[href], '
        '.item a[href], '
        '.entry a[href], '
        'h3 a[href], h2 a[href], h4 a[href], '
        '.title a[href], '
        '[class*=title] a[href], '
        '.headline a[href], '
        'li a[href]'
    )
    if level1:
        logger.info(f"{site_name} 降级L1: 通用选择器找到 {len(level1)} 个元素")
        return level1

    # Level 2: all links with reasonable text
    all_links = soup.find_all('a', href=True)
    candidates = [
        a for a in all_links
        if 15 < len(a.get_text(strip=True)) < 300
    ]
    if candidates:
        logger.info(f"{site_name} 降级L2: <a>标签文本筛选找到 {len(candidates)} 个候选")
        return candidates

    # Level 3: heading tags with links nearby
    headings = soup.select('h1, h2, h3, h4')
    result = []
    for h in headings:
        link = h.find('a')
        if not link:
            link = h.find_parent('a')
        if link and link.get('href'):
            result.append(link)
    if result:
        logger.info(f"{site_name} 降级L3: <h1>-<h4>含链接找到 {len(result)} 个")
        return result

    logger.warning(f"{site_name} 三级降级全部失败，需人工修复选择器")
    return []


def _parse_html_titles(title_elements, site_config, soup, date_filter_days=0, translate_fn=None):
    """Parse title elements from HTML into news items. Shared by light and heavy scrapers."""
    # Patterns that are clearly navigation/UI — not news
    _NAV_PATTERNS = [
        # ── Navigation / framework ──
        'documents & reports', 'documents and reports', 'research & publications',
        'understanding poverty', 'stumble upon', 'share', 'search', 'menu',
        'home', 'about', 'contact', 'login', 'register', 'subscribe',
        'privacy', 'terms of use', 'accessibility', 'copyright',
        'newsletter', 'newsletters', 'breadcrumb', 'skip to main',
        'skip to footer', 'skip to content', 'skip to navigation',
        'who we are', 'what we do', 'what we achieved', 'engage with us',
        'our members', 'how we work', 'host economy', 'policy support unit',
        'leadership', 'past administration', 'publications',
        'projects database', 'meeting document database', 'aimp login',
        'tenders and rfps', 'meetings and events',
        'declarations and statements', "leaders' declarations",
        'policies and procedures', 'industry dialogues',
        'expressed views disclaimer', 'washington, dc',
        'research and analysis',
        # ── Generic labels ──
        'blog post', 'working paper', 'news releases',
        'member companies', 'board of directors', 'member survey',
        'all research & analysis', 'washington update',
        'budget management', 'capacity building',
        'applying for funds', 'implementing projects',
        'project overseer toolkit', 'project quality: training',
        'periodical reports', 'psu governance', 'psu publications',
        # ── Organizational units (committees, working groups, etc.) ──
        'working group', 'chemical dialogue', 'secretariat staff',
        'tourism websites',
        # ── Journal / magazine issue covers (not real articles) ──
        '月号',  # Japanese magazine issue marker
        # ── Chinese nav terms ──
        '高级官员', '联系我们', '年度部长级', '出版物',
        'senior officials', 'annual ministerial', 'contact apec',
        # ── APEC category / group / process pages (not publications) ──
        'structural reform', 'market access group', 'business mobility',
        'high level policy dialogue', 'apec aspire', 'urbanization',
        'food security', 'apec in action', 'automotive dialogue',
        'trade and investment', 'investment experts', 'investment related links',
        'specialized apec', 'finance ministers', 'agricultural biotechnology',
        'innovation and digitalisation', 'telecommunications and information',
        'experts group', 'policy dialogue', 'related links', 'in action',
        'join uscbc', 'economic and financial publications',
        'competition policy and law', 'economic and technical cooperation',
        'digital economy steering', 'intellectual property experts',
        'project funding sources', 'auto-parts supplier portal',
        'business travel card', 'customs requirements',
        'china market intelligence', 'financial services industry update',
        'us-china trade war tracker',
        'sub-committee on customs', 'import regulations',
        'intellectual property rights service', 'apec-oecd',
        'strong, balanced, secure', 'electrical and electronic equipment mutual',
        'apec in charts',
    ]

    news_items = []
    for element in title_elements:
        title = element.get_text().strip()
        if not title or len(title) < 10:
            continue

        # Skip navigation/UI items
        title_lower = title.lower()
        if any(p == title_lower or (len(p) > 6 and p in title_lower) for p in _NAV_PATTERNS):
            continue
        # Extra short-pattern substring matches (journal/magazine markers)
        if any(m in title_lower for m in ['月号', '最新号', '年x月']):
            continue

        # Skip titles that are too short to be real news (single words, names, etc.)
        # CJK text doesn't use spaces — skip word-count check if it contains CJK
        has_cjk = any('\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' for c in title)
        if not has_cjk:
            words = title.split()
            if len(words) < 3 and len(title) < 30:
                continue

        # Extract URL
        url = site_config['url']
        if element.name == 'a' and element.get('href'):
            url = urljoin(site_config['url'], element['href'])
        else:
            link = element.find('a')
            if link and link.get('href'):
                url = urljoin(site_config['url'], link['href'])
            else:
                link = element.find_parent('a')
                if link and link.get('href'):
                    url = urljoin(site_config['url'], link['href'])

        # Extract date
        date_str = datetime.now().strftime('%Y-%m-%d')
        try:
            if site_config.get('date_selector'):
                date_element = None
                parent = element
                for _ in range(6):
                    parent = parent.find_parent()
                    if not parent:
                        break
                    date_element = parent.select_one(site_config['date_selector'])
                    if date_element:
                        break
                if date_element:
                    datetime_attr = date_element.get('datetime', '').strip()
                    date_str = datetime_attr if datetime_attr else date_element.get_text().strip()
        except Exception:
            pass

        date_format = site_config.get('date_format', '')
        if not is_within_date_filter(date_str, date_format or None, date_filter_days):
            continue

        parsed_date = parse_date_string(date_str, date_format or None)
        if parsed_date:
            date_str = parsed_date.strftime('%Y-%m-%d')

        translated_title = translate_fn(title) if translate_fn else title

        news_items.append({
            'site_name': site_config['name'],
            'title': title,
            'translated_title': translated_title,
            'url': url,
            'date': date_str
        })

    return news_items


def scrape_html_site(site_config, headless=False, date_filter_days=0, translate_fn=None):
    """Scrape an HTML news site using Selenium Chrome."""
    if not site_config.get('enabled', True):
        return []

    driver = None
    try:
        logger.info(f"开始抓取HTML {site_config['name']} - URL: {site_config['url']}")
        driver = create_webdriver(headless=headless)
        driver.get(site_config['url'])

        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body")))
        WebDriverWait(driver, 15).until(
            lambda d: d.execute_script("return document.readyState") == "complete")
        time.sleep(10)

        # Dynamic content detection
        previous_len = 0
        stable_count = 0
        for cycle in range(6):
            current_len = len(driver.page_source)
            if current_len == previous_len:
                stable_count += 1
                if stable_count >= 2:
                    break
            else:
                stable_count = 0
            previous_len = current_len
            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight/3);")
                time.sleep(1)
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight*2/3);")
                time.sleep(1)
                driver.execute_script("window.scrollTo(0, 0);")
            except Exception:
                pass
            time.sleep(3)

        time.sleep(5)
        soup = BeautifulSoup(driver.page_source, 'html.parser')

        # Try waiting for title elements
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, site_config['title_selector'])))
            time.sleep(3)
        except TimeoutException:
            logger.warning(f"等待标题元素超时: {site_config['title_selector']}")

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        title_elements = soup.select(site_config['title_selector'])
        logger.debug(f"找到 {len(title_elements)} 个标题元素")

        news_items = []
        for element in title_elements:
            title = element.get_text().strip()
            if not title or len(title) < 10:
                continue

            # Extract URL
            url = site_config['url']
            if element.name == 'a' and element.get('href'):
                url = urljoin(site_config['url'], element['href'])
            else:
                link = element.find('a')
                if link and link.get('href'):
                    url = urljoin(site_config['url'], link['href'])
                else:
                    link = element.find_parent('a')
                    if link and link.get('href'):
                        url = urljoin(site_config['url'], link['href'])

            # Extract date
            date_str = datetime.now().strftime('%Y-%m-%d')
            try:
                if site_config.get('date_selector'):
                    date_element = None
                    parent = element
                    for _ in range(6):
                        parent = parent.find_parent()
                        if not parent:
                            break
                        date_element = parent.select_one(site_config['date_selector'])
                        if date_element:
                            break
                    if date_element:
                        datetime_attr = date_element.get('datetime', '').strip()
                        date_str = datetime_attr if datetime_attr else date_element.get_text().strip()
            except Exception:
                pass

            date_format = site_config.get('date_format', '')
            if not is_within_date_filter(date_str, date_format or None, date_filter_days):
                continue

            parsed_date = parse_date_string(date_str, date_format or None)
            if parsed_date:
                date_str = parsed_date.strftime('%Y-%m-%d')

            translated_title = translate_fn(title) if translate_fn else title

            news_items.append({
                'site_name': site_config['name'],
                'title': title,
                'translated_title': translated_title,
                'url': url,
                'date': date_str
            })

        logger.info(f"从HTML {site_config['name']} 获取到 {len(news_items)} 条新闻")
        return news_items

    except TimeoutException as e:
        logger.error(f"抓取HTML {site_config['name']} 超时: {e}")
        return []
    except WebDriverException as e:
        logger.error(f"抓取HTML {site_config['name']} WebDriver错误: {e}")
        return []
    except Exception as e:
        logger.error(f"抓取HTML {site_config['name']} 失败: {str(e)}")
        import traceback
        logger.debug(traceback.format_exc())
        return []
    finally:
        if driver:
            driver.quit()


def scrape_api_site(site_config, date_filter_days=0, translate_fn=None):
    """Scrape a JSON API news source."""
    if not site_config.get('enabled', True):
        return []

    try:
        logger.info(f"开始抓取API {site_config['name']}")
        resp = requests.get(site_config['url'], timeout=30, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': site_config.get('url', '').split('?')[0]
        })
        resp.raise_for_status()
        data = resp.json()

        items = data.get('items', data) if isinstance(data, dict) else data
        if not isinstance(items, list):
            logger.warning(f"API {site_config['name']} 返回格式异常")
            return []

        logger.debug(f"API {site_config['name']} 返回 {len(items)} 条")
        news_items = []
        base_url = site_config.get('base_url', '')

        for item in items:
            title = item.get('title', '').strip()
            if not title:
                continue
            # Clean APEC "Reports\n\n\n" prefix from concatenated titles
            title = title.replace('Reports\n\n\n', '').strip()

            url = item.get('url', '')
            if url and not url.startswith('http'):
                url = base_url + url

            date_str = item.get('date', '') or item.get('publishedDate', '') or item.get('date_published', '')
            date_format = site_config.get('date_format', '')
            parsed_date = parse_date_string(date_str, date_format or None)
            date_str = parsed_date.strftime('%Y-%m-%d') if parsed_date else datetime.now().strftime('%Y-%m-%d')

            if not is_within_date_filter(date_str, date_format or None, date_filter_days):
                continue

            translated_title = translate_fn(title) if translate_fn else title
            news_items.append({
                'site_name': site_config['name'],
                'title': title,
                'translated_title': translated_title,
                'url': url,
                'date': date_str
            })

        logger.info(f"从API {site_config['name']} 获取到 {len(news_items)} 条新闻")
        return news_items

    except Exception as e:
        logger.error(f"抓取API {site_config['name']} 失败: {str(e)}")
        return []


def scrape_news_site(site_config, headless=False, date_filter_days=0, translate_fn=None):
    """Scrape a news site, auto-detecting the type.

    For HTML sites, tries lightweight requests+BS4 first; falls back to
    Selenium+Chrome only if the light scraper fails (no titles found).
    This avoids spinning up a browser for simple static pages.
    """
    site_type = site_config.get('site_type', 'html').lower()

    if site_type == 'rss':
        return scrape_rss_site(site_config, date_filter_days, translate_fn)
    elif site_type == 'api':
        return scrape_api_site(site_config, date_filter_days, translate_fn)
    else:
        # HTML: try lightweight first, fall back to Selenium
        items, ok = scrape_html_site_light(
            site_config, date_filter_days, translate_fn)
        if ok:
            return items
        logger.info(f"轻量抓取 {site_config['name']} 失败，降级到 Selenium")
        return scrape_html_site(
            site_config, headless, date_filter_days, translate_fn)
