#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""News Monitor — entry point.

A real-time news monitoring system that scrapes 30+ global institutions
(IMF, World Bank, central banks, think tanks), filters by keywords, translates
titles via DeepLX, scores relevance via LLM, and pushes notifications via
Bark / Server酱 / Email.

Usage:
    python app.py
"""

import logging
from logging.handlers import RotatingFileHandler
from paths import get_log_path

# Logging: rotating 10MB × 5 files (50MB total)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            str(get_log_path()), encoding='utf-8',
            maxBytes=10 * 1024 * 1024, backupCount=5
        ),
        logging.StreamHandler()
    ]
)

from news_monitor import NewsMonitor
from news_monitor.web import create_app, run_app

if __name__ == '__main__':
    monitor = NewsMonitor()
    monitor.start_scheduler()
    run_app(monitor)
