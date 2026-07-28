#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Log cleanup utility for news-monitor."""

import os
import logging
from paths import get_log_path

logger = logging.getLogger(__name__)


def clean_log_file():
    """Truncate log file if it exceeds 10MB, keeping last 1000 lines."""
    try:
        log_file_path = str(get_log_path())
        if not os.path.exists(log_file_path):
            return

        file_size = os.path.getsize(log_file_path)
        max_size = 10 * 1024 * 1024  # 10MB

        if file_size > max_size:
            with open(log_file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            keep_lines = min(1000, len(lines))
            with open(log_file_path, 'w', encoding='utf-8') as f:
                f.writelines(lines[-keep_lines:])

            logger.info(f"日志文件已清理: {file_size/1024/1024:.1f}MB -> 保留最后 {keep_lines} 行")
    except Exception as e:
        logger.error(f"清理日志文件失败: {str(e)}")
