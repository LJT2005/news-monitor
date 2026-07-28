#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask web routes for news-monitor."""

import os
import sys
import time
import socket
import sqlite3
import threading
import logging
from datetime import datetime, timedelta

from flask import Flask, render_template, request, jsonify

from paths import get_config_path, get_db_path, get_log_path, get_template_dir
from . import database as db

logger = logging.getLogger(__name__)


def find_available_port(start_port=5000, max_attempts=10):
    """Find an available TCP port."""
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('0.0.0.0', port))
                logger.info(f'找到可用端口: {port}')
                return port
        except OSError:
            logger.info(f'端口 {port} 已被占用，尝试下一个端口')
            continue
    raise RuntimeError(f'无法找到可用端口，已尝试端口范围: {start_port}-{start_port + max_attempts - 1}')


def create_app(monitor):
    """Create and configure the Flask application."""
    app = Flask(__name__, template_folder=str(get_template_dir()))
    app.secret_key = 'news_monitor_secret_key_2024'

    # ── Page routes ─────────────────────────────────────────────

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/config')
    def config_page():
        return render_template('config.html', config=monitor.config, config_path=str(get_config_path()))

    @app.route('/logs')
    def logs_page():
        return render_template('logs.html')

    @app.route('/sites')
    def sites_page():
        return render_template('sites.html')

    @app.route('/stats')
    def stats_page():
        return render_template('stats.html')

    # ── Config API ──────────────────────────────────────────────

    @app.route('/api/config', methods=['GET', 'POST'])
    def api_config():
        if request.method == 'GET':
            return jsonify(monitor.config)
        try:
            new_config = request.json
            # Validate before saving
            from . import validator
            valid, errors = validator.validate_config(new_config)
            if not valid:
                return jsonify({
                    'success': False,
                    'message': '配置校验失败',
                    'errors': errors
                })
            monitor.config = new_config
            monitor.save_config()
            return jsonify({'success': True, 'message': '配置保存成功'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})

    @app.route('/api/config/restore-news-sites', methods=['POST'])
    def api_restore_news_sites():
        try:
            sites = monitor.restore_default_news_sites()
            return jsonify({'success': True, 'count': len(sites), 'message': f'已恢复 {len(sites)} 个默认网站配置'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})

    # ── News API ────────────────────────────────────────────────

    @app.route('/api/news')
    def api_news():
        try:
            page = request.args.get('page', 1, type=int)
            per_page = min(request.args.get('per_page', 20, type=int), 100)
            site_filter = request.args.get('site', '')
            pushed_filter = request.args.get('pushed', '')
            offset = (page - 1) * per_page

            conn = sqlite3.connect(str(get_db_path()))
            cursor = conn.cursor()

            conditions = []
            params = []
            llm_threshold = monitor.config.get('llm_filter', {}).get('relevance_threshold', 60)
            if site_filter:
                conditions.append('site_name = ?')
                params.append(site_filter)
            if pushed_filter == '1':
                conditions.append('pushed = 1')
            elif pushed_filter == '2':
                conditions.append('pushed = 2')
            elif pushed_filter == '0':
                conditions.append('pushed = 0')
                conditions.append(f'(llm_relevance < 0 OR llm_relevance >= {llm_threshold})')
            elif pushed_filter == 'filtered':
                conditions.append(
                    f'(pushed = 2 OR (pushed = 0 AND llm_relevance >= 0 AND llm_relevance < {llm_threshold}))')
            where_clause = (' WHERE ' + ' AND '.join(conditions)) if conditions else ''

            cursor.execute(f'SELECT COUNT(*) FROM news{where_clause}', params)
            total = cursor.fetchone()[0]

            cursor.execute(f'''
                SELECT site_name, title, translated_title, url, date, created_at, pushed, llm_relevance, llm_reason
                FROM news{where_clause}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            ''', params + [per_page, offset])
            news = cursor.fetchall()

            cursor.execute('SELECT DISTINCT site_name FROM news ORDER BY site_name')
            site_names = [row[0] for row in cursor.fetchall()]
            conn.close()

            news_list = []
            for item in news:
                relevance = item[7]
                pushed = item[6]
                if pushed == 2:
                    push_status = 'filtered'
                elif pushed == 1:
                    push_status = 'pushed'
                elif relevance >= 0 and relevance < llm_threshold:
                    push_status = 'filtered'
                else:
                    push_status = 'pending'
                news_list.append({
                    'site_name': item[0], 'title': item[1],
                    'translated_title': item[2], 'url': item[3],
                    'date': item[4], 'created_at': item[5],
                    'pushed': pushed, 'push_status': push_status,
                    'llm_relevance': relevance, 'llm_reason': item[8] or ''
                })

            return jsonify({
                'items': news_list, 'total': total, 'page': page,
                'per_page': per_page, 'pages': (total + per_page - 1) // per_page,
                'site_names': site_names, 'llm_threshold': llm_threshold
            })
        except Exception as e:
            return jsonify({'error': str(e)})

    # ── Action APIs ─────────────────────────────────────────────

    @app.route('/api/check_now')
    def api_check_now():
        try:
            threading.Thread(target=monitor.check_news_updates, daemon=True).start()
            return jsonify({'success': True, 'message': '开始检查新闻更新'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})

    @app.route('/api/push_pending', methods=['POST'])
    def api_push_pending():
        try:
            pending_count = monitor.get_pending_count()
            if pending_count == 0:
                return jsonify({'success': False, 'message': '没有待推送的新闻'})
            threading.Thread(target=monitor.push_pending_news, daemon=True).start()
            return jsonify({'success': True, 'message': f'开始推送 {pending_count} 条待发新闻'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})

    @app.route('/api/site_stats')
    def api_site_stats():
        try:
            return jsonify({'stats': monitor.get_site_stats()})
        except Exception as e:
            return jsonify({'error': str(e)})

    @app.route('/api/retry_llm', methods=['POST'])
    def api_retry_llm():
        try:
            if monitor.is_running:
                return jsonify({'success': False, 'message': '正在采集中，请稍后再试'})
            if not monitor.config.get('llm_filter', {}).get('enabled', False):
                return jsonify({'success': False, 'message': 'LLM筛选未启用'})
            unrated = monitor.get_unrated_count()
            if unrated == 0:
                return jsonify({'success': True, 'message': '没有需要重试的新闻', 'updated': 0})
            updated = monitor.retry_llm_scoring()
            return jsonify({'success': True, 'message': f'重试完成，成功评分 {updated} 条', 'updated': updated})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})

    @app.route('/api/restart', methods=['POST'])
    def api_restart():
        def restart_server():
            time.sleep(1)
            logger.info('正在重启服务以应用新配置...')
            os.execv(sys.executable, ['python'] + sys.argv)
        try:
            threading.Thread(target=restart_server, daemon=True).start()
            return jsonify({'success': True, 'message': '服务正在重启...'})
        except Exception as e:
            logger.error(f'重启服务失败: {str(e)}')
            return jsonify({'success': False, 'message': str(e)})

    @app.route('/api/logs')
    def api_logs():
        try:
            with open(str(get_log_path()), 'r', encoding='utf-8') as f:
                logs = f.readlines()[-100:]
            return jsonify({'logs': logs})
        except Exception as e:
            return jsonify({'logs': [f'读取日志失败: {str(e)}']})

    @app.route('/api/health')
    def api_health():
        """Health check endpoint for monitoring systems."""
        import sqlite3
        db_ok = False
        try:
            conn = sqlite3.connect(str(get_db_path()))
            conn.execute('SELECT 1')
            conn.close()
            db_ok = True
        except Exception:
            pass

        # Count failed sites in last 24h
        failed_24h = 0
        try:
            stats = monitor.get_site_stats()
            now = datetime.now()
            for s in stats:
                last_check = s.get('last_check', '')
                if last_check:
                    try:
                        lc = datetime.strptime(last_check, '%Y-%m-%d %H:%M:%S')
                        if (now - lc).total_seconds() < 86400:
                            if s.get('consecutive_errors', 0) > 0:
                                failed_24h += 1
                    except ValueError:
                        pass
        except Exception:
            pass

        enabled_count = len([s for s in monitor.config.get('news_sites', [])
                             if s.get('enabled', True)])

        next_check = None
        if monitor.last_check_time:
            next_check = monitor.last_check_time + timedelta(
                minutes=monitor.config['check_interval'])

        return jsonify({
            'status': 'ok' if db_ok else 'degraded',
            'db_ok': db_ok,
            'last_check': monitor.last_check_time.isoformat() if monitor.last_check_time else None,
            'next_check': next_check.isoformat() if next_check else None,
            'pending_news': monitor.get_pending_count(),
            'enabled_sites': enabled_count,
            'failed_sites_24h': failed_24h,
            'is_running': monitor.is_running,
        })

    @app.route('/api/stats')
    def api_dashboard_stats():
        """Aggregated statistics for the dashboard."""
        import sqlite3
        conn = sqlite3.connect(str(get_db_path()))
        cursor = conn.cursor()

        # Total news count
        cursor.execute('SELECT COUNT(*) FROM news')
        total_news = cursor.fetchone()[0]

        # News by source (top 20)
        cursor.execute('''
            SELECT site_name, COUNT(*) as cnt
            FROM news GROUP BY site_name
            ORDER BY cnt DESC LIMIT 20
        ''')
        news_by_source = [{'name': r[0], 'count': r[1]} for r in cursor.fetchall()]

        # News over last 7 days
        from datetime import datetime as dt
        dates = []
        counts = []
        for i in range(6, -1, -1):
            day = dt.now() - __import__('datetime').timedelta(days=i)
            day_str = day.strftime('%Y-%m-%d')
            dates.append(day_str)
            cursor.execute(
                "SELECT COUNT(*) FROM news WHERE date(date) = ?", (day_str,))
            counts.append(cursor.fetchone()[0])

        # Site stats
        cursor.execute('SELECT * FROM site_stats ORDER BY last_check DESC')
        cols = [d[0] for d in cursor.description]
        site_stats_raw = [dict(zip(cols, r)) for r in cursor.fetchall()]

        # Compute success rate and summarize
        total_checks = sum(s.get('total_checks', 0) for s in site_stats_raw)
        total_success = sum(s.get('total_success', 0) for s in site_stats_raw)
        total_errors = sum(s.get('total_errors', 0) for s in site_stats_raw)
        success_rate = round(total_success / total_checks * 100, 1) if total_checks > 0 else 0

        # Sites with consecutive errors > 0
        failing = [s for s in site_stats_raw if s.get('consecutive_errors', 0) > 0]

        site_summary = []
        for s in site_stats_raw:
            sc = s.get('total_checks', 0)
            ss = s.get('total_success', 0)
            rate = round(ss / sc * 100, 1) if sc > 0 else 0
            site_summary.append({
                'name': s['site_name'],
                'success_rate': rate,
                'total_checks': sc,
                'total_news': s.get('total_news', 0),
                'last_check': s.get('last_check', ''),
                'avg_response_time': round(s.get('avg_response_time', 0), 2),
                'consecutive_errors': s.get('consecutive_errors', 0),
                'status': 'error' if s.get('consecutive_errors', 0) > 0 else 'ok'
            })
        site_summary.sort(key=lambda x: x['total_news'], reverse=True)

        # Enabled sites count
        enabled_count = len([s for s in monitor.config.get('news_sites', [])
                             if s.get('enabled', True)])

        conn.close()

        return jsonify({
            'total_news': total_news,
            'total_checks': total_checks,
            'total_success': total_success,
            'total_errors': total_errors,
            'success_rate': success_rate,
            'enabled_sites': enabled_count,
            'failing_sites': len(failing),
            'news_by_source': news_by_source,
            'daily_news': {'dates': dates, 'counts': counts},
            'site_summary': site_summary,
            'pending_news': monitor.get_pending_count(),
        })

    @app.route('/api/export/csv')
    def api_export_csv():
        """Export news as CSV file."""
        import csv
        import io
        from flask import Response

        site_filter = request.args.get('site', '')
        date_range = request.args.get('range', '30d')  # all, 30d, 7d
        date_from = request.args.get('from', '')
        date_to = request.args.get('to', '')
        pushed_filter = request.args.get('pushed', '')

        conn = sqlite3.connect(str(get_db_path()))
        cursor = conn.cursor()

        conditions = []
        params = []
        if site_filter:
            conditions.append('site_name = ?')
            params.append(site_filter)

        # Date range presets (overridden by explicit from/to)
        if date_from:
            conditions.append('date >= ?')
            params.append(date_from)
        elif date_range == '7d':
            cutoff = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            conditions.append('date >= ?')
            params.append(cutoff)
        elif date_range == '30d':
            cutoff = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            conditions.append('date >= ?')
            params.append(cutoff)
        # range=all → no date filter
        if date_to:
            conditions.append('date <= ?')
            params.append(date_to)
        if pushed_filter == '1':
            conditions.append('pushed = 1')
        elif pushed_filter == '2':
            conditions.append('pushed = 2')
        elif pushed_filter == '0':
            conditions.append('pushed = 0')

        where = (' WHERE ' + ' AND '.join(conditions)) if conditions else ''
        cursor.execute(f'''
            SELECT site_name, title, translated_title, url, date, created_at, pushed, llm_relevance, llm_reason
            FROM news{where} ORDER BY created_at DESC
        ''', params)
        rows = cursor.fetchall()
        conn.close()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['来源', '英文标题', '中文标题', 'URL', '日期', '入库时间', '推送状态', 'LLM分数', 'LLM理由'])
        push_labels = {0: '未推送', 1: '已推送', 2: '主题无关'}
        for r in rows:
            writer.writerow([
                r[0], r[1], r[2] or '', r[3], r[4], r[5],
                push_labels.get(r[6], str(r[6])),
                r[7] if r[7] >= 0 else '', (r[8] or '')
            ])

        output.seek(0)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return Response(
            output.getvalue().encode('utf-8-sig'),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename=news_export_{timestamp}.csv'}
        )

    @app.route('/api/status')
    def api_status():
        next_check_time = None
        if monitor.last_check_time:
            next_check_time = monitor.last_check_time + timedelta(minutes=monitor.config['check_interval'])
        else:
            next_check_time = datetime.now() + timedelta(minutes=monitor.config['check_interval'])

        push_config = monitor.config.get('push', {})
        push_mode = push_config.get('mode', 'immediate')
        next_push_time = None
        if push_mode == 'scheduled':
            scheduled_times = push_config.get('scheduled_times', [])
            if scheduled_times:
                now = datetime.now()
                today = now.strftime('%Y-%m-%d')
                candidates = []
                for t in scheduled_times:
                    t = t.strip()
                    if not t:
                        continue
                    try:
                        dt = datetime.strptime(f"{today} {t}", '%Y-%m-%d %H:%M')
                        if dt > now:
                            candidates.append(dt)
                    except ValueError:
                        pass
                if not candidates:
                    for t in sorted(scheduled_times):
                        t = t.strip()
                        if not t:
                            continue
                        try:
                            dt = datetime.strptime(f"{today} {t}", '%Y-%m-%d %H:%M') + timedelta(days=1)
                            candidates.append(dt)
                            break
                        except ValueError:
                            pass
                if candidates:
                    next_push_time = min(candidates)

        return jsonify({
            'is_running': monitor.is_running,
            'driver_available': True,
            'config_loaded': monitor.config is not None,
            'check_interval': monitor.config['check_interval'],
            'next_check_time': next_check_time.isoformat() if next_check_time else None,
            'last_check_time': monitor.last_check_time.isoformat() if monitor.last_check_time else None,
            'push_mode': push_mode,
            'pending_count': monitor.get_pending_count() if push_mode == 'scheduled' else 0,
            'next_push_time': next_push_time.isoformat() if next_push_time else None,
            'scrape_progress': monitor.scrape_progress,
            'news_version': getattr(monitor, 'news_version', 0),
            'unrated_count': monitor.get_unrated_count() if monitor.config.get('llm_filter', {}).get('enabled', False) else 0
        })

    @app.route('/api/test_notification', methods=['POST'])
    def api_test_notification():
        try:
            conn = sqlite3.connect(str(get_db_path()))
            cursor = conn.cursor()
            cursor.execute('''
                SELECT site_name, title, translated_title, url, date, created_at
                FROM news ORDER BY created_at DESC LIMIT 5
            ''')
            news_rows = cursor.fetchall()
            conn.close()

            if not news_rows:
                return jsonify({'success': False, 'message': '数据库中没有新闻数据，请先运行新闻检查或添加新闻源'})

            test_news_list = []
            for row in news_rows:
                test_news_list.append({
                    'site_name': row[0], 'title': row[1],
                    'translated_title': row[2], 'url': row[3],
                    'date': row[4], 'created_at': row[5]
                })

            monitor.send_notification_with_details(test_news_list)
            return jsonify({'success': True, 'message': f'测试通知已发送！包含 {len(test_news_list)} 条新闻'})
        except Exception as e:
            logger.error(f"测试通知发送失败: {str(e)}")
            return jsonify({'success': False, 'message': f'发送失败: {str(e)}'})

    return app


def run_app(monitor, port=None):
    """Start the Flask app with browser auto-open."""
    if port is None:
        port = find_available_port()

    app = create_app(monitor)

    # Auto-open browser
    def open_browser():
        import webbrowser
        time.sleep(2)
        url = f'http://localhost:{port}'
        logger.info(f'自动打开浏览器: {url}')
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host='0.0.0.0', port=port, debug=False)
