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

from news_monitor import NewsMonitor
from news_monitor.web import create_app, run_app

if __name__ == '__main__':
    monitor = NewsMonitor()
    monitor.start_scheduler()
    run_app(monitor)
