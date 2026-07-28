#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Notification module — Bark, Server酱, Email."""

import time
import logging
import requests

logger = logging.getLogger(__name__)


def send_notification(message, notification_config):
    """Send a simple text notification to all configured channels."""
    # ── Bark ──
    _send_bark_simple(message, notification_config)

    # ── Server酱 ──
    _send_serverchan_simple(message, notification_config)

    # ── Webhooks (Telegram, 飞书, 钉钉, Discord) ──
    _send_webhooks_simple(message, notification_config.get('webhooks', {}))


def send_notification_with_details(new_news_list, notification_config, title_prefix='新闻更新'):
    """Send detailed news notifications with full content."""
    if not new_news_list:
        return

    # Build full message
    message_lines = [f"\U0001f4f0 {title_prefix}：发现 {len(new_news_list)} 条新闻\n"]
    for i, news in enumerate(new_news_list, 1):
        site_name = news.get('site_name', '未知来源')
        title = news.get('title', '无标题')
        translated_title = news.get('translated_title', '')
        url = news.get('url', '')

        message_lines.append(f"\U0001f538 {i}. 【{site_name}】")
        if translated_title and translated_title != title:
            message_lines.append(f"   {translated_title}")
            message_lines.append(f"   {title}")
        else:
            message_lines.append(f"   {title}")
        if url:
            message_lines.append(f"   {url}")
        message_lines.append("")
    message = "\n".join(message_lines)

    # ── Bark ──
    _send_bark_detailed(new_news_list, notification_config, title_prefix)

    # ── Server酱 ──
    _send_serverchan_detailed(new_news_list, notification_config, message, title_prefix)

    # ── Webhooks ──
    _send_webhooks_detailed(new_news_list, notification_config.get('webhooks', {}), message, title_prefix)

    # ── Email ──
    email_config = notification_config.get('email', {})
    if email_config.get('enabled', False):
        _send_email_notification(new_news_list, email_config, message, title_prefix)


def _send_bark_chunked(bark_url, news_list, title_prefix):
    """Send Bark notification in 1KB chunks to avoid URL length limits."""
    item_lines = []
    for i, news in enumerate(news_list, 1):
        title = news.get('title', '')
        translated = news.get('translated_title', '')
        u = news.get('url', '')
        if translated and translated != title:
            line = f"{i}. {translated}\n   {title}"
        else:
            line = f"{i}. {title}"
        if u:
            line += f"\n   {u}"
        item_lines.append(line)

    max_bytes = 1000
    chunks = []
    current_chunk = []
    current_size = 0
    for line in item_lines:
        line_bytes = len(line.encode('utf-8')) + 1
        if current_size + line_bytes > max_bytes and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_size = 0
        current_chunk.append(line)
        current_size += line_bytes
    if current_chunk:
        chunks.append(current_chunk)

    total_chunks = len(chunks)
    for idx, chunk in enumerate(chunks):
        try:
            if total_chunks > 1:
                push_title = f"\U0001f4f0 {title_prefix} ({idx+1}/{total_chunks})"
            else:
                push_title = f"\U0001f4f0 {title_prefix}（{len(news_list)}条）"
            push_content = "\n".join(chunk)

            response = requests.post(bark_url, json={
                "title": push_title,
                "body": push_content,
                "group": "新闻监控",
            }, timeout=10)
            if response.status_code == 200:
                logger.info(f"Bark定时汇总通知发送成功: {bark_url} ({idx+1}/{total_chunks})")
            else:
                logger.warning(f"Bark定时汇总通知发送失败，状态码: {response.status_code}")

            if idx < total_chunks - 1:
                time.sleep(0.5)
        except Exception as e:
            logger.error(f"Bark定时汇总通知发送失败: {bark_url}, 错误: {str(e)}")


def _send_bark_simple(message, notification_config):
    """Send simple Bark notification."""
    bark_urls = list(notification_config.get('bark_urls', []))
    if notification_config.get('bark_url') and notification_config['bark_url'] not in bark_urls:
        bark_urls.append(notification_config['bark_url'])
    for bark_url in bark_urls:
        if not bark_url.strip():
            continue
        try:
            response = requests.post(bark_url.strip(), json={
                "title": "\U0001f4f0 新闻更新通知",
                "body": message,
                "group": "新闻监控",
            }, timeout=10)
            if response.status_code == 200:
                logger.info(f"Bark通知发送成功: {bark_url}")
            else:
                logger.warning(f"Bark通知发送失败，状态码: {response.status_code}")
        except Exception as e:
            logger.error(f"Bark通知发送失败: {bark_url}, 错误: {str(e)}")


def _send_serverchan_simple(message, notification_config):
    """Send simple Server酱 notification."""
    keys = list(notification_config.get('serverchan_keys', []))
    if notification_config.get('serverchan_key') and notification_config['serverchan_key'] not in keys:
        keys.append(notification_config['serverchan_key'])
    for key in keys:
        if not key.strip():
            continue
        try:
            url = f"https://sctapi.ftqq.com/{key.strip()}.send"
            response = requests.post(url, {'title': '新闻更新通知', 'desp': message}, timeout=10)
            if response.status_code == 200:
                logger.info(f"Server酱通知发送成功: {key}")
            else:
                logger.warning(f"Server酱通知发送失败，状态码: {response.status_code}")
        except Exception as e:
            logger.error(f"Server酱通知发送失败: {key}, 错误: {str(e)}")


def _send_bark_detailed(news_list, notification_config, title_prefix):
    """Send detailed Bark notification."""
    bark_urls = list(notification_config.get('bark_urls', []))
    if notification_config.get('bark_url') and notification_config['bark_url'] not in bark_urls:
        bark_urls.append(notification_config['bark_url'])
    for bark_url in bark_urls:
        if not bark_url.strip():
            continue
        if title_prefix == '定时新闻汇总':
            _send_bark_chunked(bark_url.strip(), news_list, title_prefix)
        else:
            for news in news_list:
                try:
                    site_name = news.get('site_name', '未知来源')
                    title = news.get('title', '无标题')
                    translated_title = news.get('translated_title', '')
                    url = news.get('url', '')
                    push_title = f"\U0001f4f0 {site_name}"
                    push_content = f"{translated_title}\n{title}" if (translated_title and translated_title != title) else title
                    payload = {"title": push_title, "body": push_content, "group": "新闻监控"}
                    if url:
                        payload["url"] = url
                    response = requests.post(bark_url.strip(), json=payload, timeout=10)
                    if response.status_code == 200:
                        logger.info(f"Bark通知发送成功: {bark_url} - {title[:30]}...")
                    else:
                        logger.warning(f"Bark通知发送失败，状态码: {response.status_code}")
                except Exception as e:
                    logger.error(f"Bark通知发送失败: {bark_url}, 错误: {str(e)}")


def _send_serverchan_detailed(news_list, notification_config, message, title_prefix):
    """Send detailed Server酱 notification."""
    keys = list(notification_config.get('serverchan_keys', []))
    if notification_config.get('serverchan_key') and notification_config['serverchan_key'] not in keys:
        keys.append(notification_config['serverchan_key'])
    for key in keys:
        if not key.strip():
            continue
        try:
            url = f"https://sctapi.ftqq.com/{key.strip()}.send"
            response = requests.post(url, {
                'title': f'\U0001f4f0 {title_prefix} ({len(news_list)}条)',
                'desp': message
            }, timeout=10)
            if response.status_code == 200:
                logger.info(f"Server酱详细通知发送成功: {key}")
            else:
                logger.warning(f"Server酱详细通知发送失败，状态码: {response.status_code}")
        except Exception as e:
            logger.error(f"Server酱详细通知发送失败: {key}, 错误: {str(e)}")


# ── Webhook notification dispatch ────────────────────────────────

def _build_webhook_message(news_list, title_prefix):
    """Build a formatted message for webhook delivery."""
    lines = [f"\U0001f4f0 **{title_prefix}** — {len(news_list)} 条新闻\n"]
    for i, news in enumerate(news_list, 1):
        site = news.get('site_name', '?')
        title = news.get('title', '无标题')
        zh = news.get('translated_title', '')
        url = news.get('url', '')
        line = f"{i}. **{zh}**\n   {title}" if (zh and zh != title) else f"{i}. {title}"
        if url:
            line += f"\n   {url}"
        lines.append(line)
    return "\n\n".join(lines)


def _send_webhooks_simple(message, webhooks_config):
    """Send simple message to all enabled webhooks."""
    _send_telegram(message, webhooks_config.get('telegram', {}))
    _send_feishu(message, webhooks_config.get('feishu', {}))
    _send_dingtalk(message, webhooks_config.get('dingtalk', {}))
    _send_discord(message, webhooks_config.get('discord', {}))


def _send_webhooks_detailed(news_list, webhooks_config, plain_message, title_prefix):
    """Send detailed news to all enabled webhooks."""
    msg = _build_webhook_message(news_list, title_prefix)
    _send_telegram(msg, webhooks_config.get('telegram', {}))
    _send_feishu(msg, webhooks_config.get('feishu', {}))
    _send_dingtalk(plain_message, webhooks_config.get('dingtalk', {}))
    _send_discord(msg, webhooks_config.get('discord', {}))


def _send_telegram(text, cfg):
    """Send via Telegram Bot API."""
    if not cfg.get('enabled') or not cfg.get('bot_token') or not cfg.get('chat_id'):
        return
    try:
        url = f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage"
        resp = requests.post(url, json={
            'chat_id': cfg['chat_id'],
            'text': text,
            'parse_mode': 'Markdown',
            'disable_web_page_preview': True
        }, timeout=10)
        if resp.status_code == 200:
            logger.info("Telegram通知发送成功")
        else:
            logger.warning(f"Telegram通知发送失败: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        logger.error(f"Telegram通知发送失败: {str(e)}")


def _send_feishu(text, cfg):
    """Send via 飞书 webhook."""
    if not cfg.get('enabled') or not cfg.get('webhook_url'):
        return
    try:
        resp = requests.post(cfg['webhook_url'], json={
            'msg_type': 'text',
            'content': {'text': text}
        }, timeout=10)
        if resp.status_code == 200:
            body = resp.json()
            if body.get('code') == 0:
                logger.info("飞书通知发送成功")
            else:
                logger.warning(f"飞书通知发送失败: {body}")
        else:
            logger.warning(f"飞书通知发送失败: {resp.status_code}")
    except Exception as e:
        logger.error(f"飞书通知发送失败: {str(e)}")


def _send_dingtalk(text, cfg):
    """Send via 钉钉 webhook."""
    if not cfg.get('enabled') or not cfg.get('webhook_url'):
        return
    try:
        resp = requests.post(cfg['webhook_url'], json={
            'msgtype': 'text',
            'text': {'content': text}
        }, timeout=10)
        if resp.status_code == 200:
            body = resp.json()
            if body.get('errcode') == 0:
                logger.info("钉钉通知发送成功")
            else:
                logger.warning(f"钉钉通知发送失败: {body}")
        else:
            logger.warning(f"钉钉通知发送失败: {resp.status_code}")
    except Exception as e:
        logger.error(f"钉钉通知发送失败: {str(e)}")


def _send_discord(text, cfg):
    """Send via Discord webhook."""
    if not cfg.get('enabled') or not cfg.get('webhook_url'):
        return
    try:
        # Discord has a 2000-char limit per message
        chunks = [text[i:i+1900] for i in range(0, len(text), 1900)]
        for chunk in chunks:
            resp = requests.post(cfg['webhook_url'], json={'content': chunk}, timeout=10)
            if resp.status_code == 204:
                logger.info("Discord通知发送成功")
            else:
                logger.warning(f"Discord通知发送失败: {resp.status_code}")
            if len(chunks) > 1:
                time.sleep(0.5)
    except Exception as e:
        logger.error(f"Discord通知发送失败: {str(e)}")
def _send_email_notification(news_list, email_config, text_message, title_prefix):
    """Send email notification with HTML formatting."""
    smtp_server = email_config.get('smtp_server', '')
    smtp_port = email_config.get('smtp_port', 465)
    use_ssl = email_config.get('use_ssl', True)
    username = email_config.get('username', '')
    password = email_config.get('password', '')
    from_address = email_config.get('from_address', '') or username
    to_addresses = email_config.get('to_addresses', [])

    if not (smtp_server and username and password and to_addresses):
        logger.warning("邮件配置不完整，跳过发送")
        return

    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'\U0001f4f0 {title_prefix} ({len(news_list)}条)'
        msg['From'] = from_address
        msg['To'] = ', '.join(to_addresses)

        msg.attach(MIMEText(text_message, 'plain', 'utf-8'))

        html_lines = ['<html><body style="font-family: sans-serif; padding: 20px;">']
        html_lines.append(f'<h2>\U0001f4f0 {title_prefix}：{len(news_list)} 条新闻</h2>')
        for i, news in enumerate(news_list, 1):
            site_name = news.get('site_name', '未知来源')
            title = news.get('title', '无标题')
            translated_title = news.get('translated_title', '')
            url = news.get('url', '')
            llm_reason = news.get('llm_reason', '')
            html_lines.append(
                '<div style="margin-bottom:16px;padding:12px;background:#f8f9fa;'
                'border-radius:8px;border-left:4px solid #0d6efd;">')
            html_lines.append(f'<div style="color:#666;font-size:13px;margin-bottom:4px;">{i}. 【{site_name}】</div>')
            if translated_title and translated_title != title:
                html_lines.append(f'<div style="font-weight:bold;font-size:15px;">{translated_title}</div>')
                if url:
                    html_lines.append(f'<a href="{url}" style="color:#0d6efd;text-decoration:none;font-size:13px;">{title}</a>')
                else:
                    html_lines.append(f'<div style="color:#555;font-size:13px;">{title}</div>')
            else:
                if url:
                    html_lines.append(f'<a href="{url}" style="color:#0d6efd;text-decoration:none;font-weight:bold;font-size:15px;">{title}</a>')
                else:
                    html_lines.append(f'<div style="font-weight:bold;font-size:15px;">{title}</div>')
            if url:
                html_lines.append(f'<div style="color:#0d6efd;font-size:12px;margin-top:4px;"><a href="{url}" style="color:#0d6efd;">{url}</a></div>')
            if llm_reason:
                html_lines.append(f'<div style="color:#888;font-size:12px;margin-top:4px;">🤖 {llm_reason}</div>')
            html_lines.append('</div>')
        html_lines.append('</body></html>')
        msg.attach(MIMEText('\n'.join(html_lines), 'html', 'utf-8'))

        if use_ssl:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)
            server.starttls()
        server.login(username, password)
        server.sendmail(from_address, to_addresses, msg.as_string())
        server.quit()
        logger.info(f"邮件通知发送成功: {', '.join(to_addresses)}")
    except Exception as e:
        logger.error(f"邮件通知发送失败: {str(e)}")
