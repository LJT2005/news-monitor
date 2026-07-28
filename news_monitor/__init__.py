#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NewsMonitor — main application class that coordinates all modules."""

import time
import threading
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import schedule

from . import config as config_mod
from . import database as db
from . import scraper
from . import translator
from . import llm_filter
from . import notifier
from . import scheduler as sched_mod

logger = logging.getLogger(__name__)


class NewsMonitor:
    """Main application class. Thin coordinator that delegates to modules."""

    def __init__(self):
        self.config = config_mod.load_config(None)
        self.is_running = False
        self.last_check_time = None
        self.news_version = 0
        self.scrape_progress = {
            'current_site': '',
            'completed': 0,
            'total': 0,
            'status': 'idle'
        }
        db.init_database()

    # ── Config ──────────────────────────────────────────────────

    def save_config(self, config=None):
        if config is not None:
            self.config = config
        config_mod.save_config(self.config)

    def get_default_news_sites(self):
        return config_mod.get_default_news_sites()

    def restore_default_news_sites(self):
        return config_mod.restore_default_news_sites(self.config)

    # ── Translation ─────────────────────────────────────────────

    def translate_text(self, text):
        return translator.translate_text(text, self.config['translation'])

    # ── Keyword matching ────────────────────────────────────────

    def match_keyword_rules(self, news_item):
        return llm_filter.match_keyword_rules(news_item, self.config.get('keyword_filters', {}))

    # ── LLM scoring ─────────────────────────────────────────────

    def llm_score_news(self, news_items):
        return llm_filter.llm_score_news(
            news_items,
            self.config.get('llm_filter', {}),
            translate_fn=self.translate_text
        )

    def retry_llm_scoring(self):
        """Re-score previously failed LLM items."""
        news_items = db.get_unrated_news()
        if not news_items:
            return 0

        logger.info(f"重试LLM打分：共 {len(news_items)} 条未评分新闻")
        scored_items = self.llm_score_news(news_items)

        updated = 0
        for item in scored_items:
            if item.get('llm_relevance', -1) >= 0:
                if db.update_llm_score(item):
                    updated += 1

        threshold = self.config.get('llm_filter', {}).get('relevance_threshold', 60)
        below = [i for i in scored_items if i.get('llm_relevance', -1) >= 0 and i['llm_relevance'] < threshold]
        if below:
            db.mark_as_filtered(below)
            logger.info(f"重试LLM打分：{len(below)} 条低分新闻标记为主题无关")

        logger.info(f"重试LLM打分完成：成功 {updated} 条")
        return updated

    # ── Scraping ────────────────────────────────────────────────

    def create_webdriver(self):
        return scraper.create_webdriver(headless=self.config.get('headless', False))

    def parse_date_string(self, date_str, date_format=None):
        return scraper.parse_date_string(date_str, date_format)

    def is_within_date_filter(self, date_str, date_format=None):
        return scraper.is_within_date_filter(
            date_str, date_format, self.config.get('date_filter_days', 0))

    def scrape_news_site(self, site_config):
        return scraper.scrape_news_site(
            site_config,
            headless=self.config.get('headless', False),
            date_filter_days=self.config.get('date_filter_days', 0),
            translate_fn=self.translate_text
        )

    # ── Database ────────────────────────────────────────────────

    def init_database(self):
        db.init_database()

    def update_site_stats(self, site_name, success, news_count=0, error_msg='', response_time=0):
        db.update_site_stats(site_name, success, news_count, error_msg, response_time)

    def get_site_stats(self):
        return db.get_site_stats()

    def filter_existing_news(self, news_items):
        return db.filter_existing_news(news_items)

    def save_news(self, news_items):
        return db.save_news(news_items)

    def mark_as_pushed(self, news_list):
        db.mark_as_pushed(news_list)

    def mark_as_filtered(self, news_list):
        db.mark_as_filtered(news_list)

    def get_pending_count(self):
        return db.get_pending_count()

    def get_unrated_count(self):
        return db.get_unrated_count()

    # ── Notifications ───────────────────────────────────────────

    def send_notification(self, message):
        notifier.send_notification(message, self.config['notification'])

    def send_notification_with_details(self, new_news_list, title_prefix='新闻更新'):
        notifier.send_notification_with_details(
            new_news_list, self.config['notification'], title_prefix)

    # ── Scheduler ───────────────────────────────────────────────

    def check_news_updates(self):
        """Main news update check — scrape, score, filter, push."""
        if self.is_running:
            logger.info("新闻检查任务已在运行中")
            return

        self.is_running = True
        self.last_check_time = datetime.now()
        try:
            logger.info("开始检查新闻更新...")
            all_news = []

            enabled_sites = [site for site in self.config['news_sites'] if site.get('enabled', True)]
            if not enabled_sites:
                logger.info("没有启用的新闻站点")
                return

            self.scrape_progress = {
                'current_site': '', 'completed': 0,
                'total': len(enabled_sites), 'status': 'running'
            }

            max_workers = self.config.get('concurrent_workers', 5)
            logger.info(f"使用 {max_workers} 个并发线程检查 {len(enabled_sites)} 个新闻站点")

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_site = {}
                future_to_start = {}
                for site in enabled_sites:
                    future = executor.submit(self.scrape_news_site, site)
                    future_to_site[future] = site
                    future_to_start[future] = time.time()

                for future in as_completed(future_to_site):
                    site = future_to_site[future]
                    site_name = site.get('name', 'Unknown')
                    response_time = time.time() - future_to_start[future]
                    self.scrape_progress['current_site'] = site_name
                    self.scrape_progress['completed'] += 1
                    try:
                        news_items = future.result(timeout=180)
                        all_news.extend(news_items)
                        self.update_site_stats(site_name, True, len(news_items), '', response_time)
                        logger.info(f"完成检查站点: {site_name}，获取 {len(news_items)} 条新闻")
                    except TimeoutError:
                        self.update_site_stats(site_name, False, 0, '站点抓取超时（超过180秒）', response_time)
                        logger.error(f"检查站点 {site_name} 超时")
                    except Exception as e:
                        self.update_site_stats(site_name, False, 0, str(e), response_time)
                        logger.error(f"检查站点 {site_name} 失败: {str(e)}")

            # Deduplicate against existing
            if all_news:
                before = len(all_news)
                all_news = self.filter_existing_news(all_news)
                if before > len(all_news):
                    logger.info(f"跳过 {before - len(all_news)} 条已存在的新闻")

            # LLM scoring
            if all_news and self.config.get('llm_filter', {}).get('enabled', False):
                self.scrape_progress['status'] = 'scoring'
                self.scrape_progress['current_site'] = 'LLM大模型打分中...'
                logger.info(f"开始LLM前置打分，共 {len(all_news)} 条新新闻")
                all_news = self.llm_score_news(all_news)

            self.scrape_progress['status'] = 'done'
            self.scrape_progress['current_site'] = ''

            new_count, new_news_list = self.save_news(all_news)
            self.news_version += 1

            if new_count > 0:
                logger.info(f"发现 {new_count} 条新新闻")
                filtered_news = [n for n in new_news_list if self.match_keyword_rules(n)]

                threshold = self.config.get('llm_filter', {}).get('relevance_threshold', 60)
                if self.config.get('llm_filter', {}).get('enabled', False):
                    before = len(filtered_news)
                    below = [n for n in filtered_news
                             if n.get('llm_relevance', -1) >= 0 and n.get('llm_relevance', 0) < threshold]
                    if below:
                        self.mark_as_filtered(below)
                        logger.info(f"LLM筛选：{len(below)} 条低分新闻标记为主题无关")
                    filtered_news = [n for n in filtered_news
                                     if n.get('llm_relevance', -1) < 0 or n.get('llm_relevance', 0) >= threshold]
                    logger.info(f"LLM阈值筛选: {before} -> {len(filtered_news)} 条 (阈值: {threshold})")

                if filtered_news:
                    push_mode = self.config.get('push', {}).get('mode', 'immediate')
                    if push_mode == 'scheduled':
                        logger.info(f"定时模式：{len(filtered_news)} 条新闻已存入待推送队列")
                    else:
                        logger.info(f"{len(filtered_news)} 条新闻通过筛选，开始推送")
                        self.send_notification_with_details(filtered_news)
                        self.mark_as_pushed(filtered_news)
                else:
                    logger.info(f"共 {new_count} 条新新闻，但无通过筛选的新闻，跳过推送")
            else:
                logger.info("没有发现新新闻")

        except Exception as e:
            logger.error(f"检查新闻更新失败: {str(e)}")
        finally:
            self.is_running = False
            self.scrape_progress = {
                'current_site': '', 'completed': 0,
                'total': 0, 'status': 'idle'
            }

    def start_scheduler(self):
        """Start the background scheduler for periodic checks and pushes."""
        check_minutes = self.config.get('check_interval', 60)

        def run_scheduler():
            while True:
                try:
                    schedule.run_pending()
                except Exception as e:
                    logger.error(f"调度器执行异常: {str(e)}")
                time.sleep(1)

        # Schedule news update checks
        schedule.every(check_minutes).minutes.do(self.check_news_updates)

        # Schedule timed pushes (if in scheduled mode)
        push_config = self.config.get('push', {})
        if push_config.get('mode') == 'scheduled':
            for t in push_config.get('scheduled_times', ['09:00', '18:00']):
                schedule.every().day.at(t).do(self.push_pending_news)

        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True, name="NewsScheduler")
        scheduler_thread.start()

        logger.info(f"定时任务已启动 (每 {check_minutes} 分钟检查一次)")

    def push_pending_news(self):
        """Push all pending news in batch (for scheduled mode)."""
        logger.info("定时推送任务触发")
        news_list = db.get_pending_news()

        if not news_list:
            logger.info("定时推送：无待推送新闻，跳过")
            return

        logger.info(f"定时推送：共 {len(news_list)} 条待推送新闻")

        filtered = [n for n in news_list if self.match_keyword_rules(n)]

        threshold = self.config.get('llm_filter', {}).get('relevance_threshold', 60)
        if self.config.get('llm_filter', {}).get('enabled', False):
            before = len(filtered)
            below = [n for n in filtered
                     if n.get('llm_relevance', -1) >= 0 and n.get('llm_relevance', 0) < threshold]
            if below:
                db.mark_as_filtered(below)
                logger.info(f"定时推送：{len(below)} 条低分新闻标记为主题无关")
            filtered = [n for n in filtered
                        if n.get('llm_relevance', -1) < 0 or n.get('llm_relevance', 0) >= threshold]
            logger.info(f"定时推送：LLM阈值筛选 {before} -> {len(filtered)} 条 (阈值: {threshold})")

        if filtered:
            logger.info(f"定时推送：{len(filtered)} 条新闻通过筛选，开始推送")
            self.send_notification_with_details(filtered, title_prefix='定时新闻汇总')
            db.mark_as_pushed(filtered)
        else:
            logger.info("定时推送：无通过筛选的新闻，跳过推送")
            db.mark_as_pushed(news_list)
