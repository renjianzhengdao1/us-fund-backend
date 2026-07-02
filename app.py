import json
import os
import threading
import time
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from flask_cors import CORS

import config
from services.cache import Cache
from services import fund_client, limit_sync

app = Flask(__name__)
CORS(app, origins=config.CORS_ORIGINS)

cache = Cache(ttl_seconds=config.CACHE_TTL_SECONDS)

# 跟踪基金元数据（支持动态热重载）
_TRACKED_FUNDS_PATH = os.path.join(os.path.dirname(__file__), 'data', 'tracked_funds.json')
_TRACKED_FUNDS = []
_TRACKED_BY_CODE = {}
_LIMITS_LOCK = threading.RLock()
_LAST_RELOAD_TS = 0


def _load_limits_from_file():
    """从 JSON 文件加载基金元数据，并记录文件修改时间。"""
    global _TRACKED_FUNDS, _TRACKED_BY_CODE, _LAST_RELOAD_TS
    try:
        with open(_TRACKED_FUNDS_PATH, 'r', encoding='utf-8') as f:
            funds = json.load(f)
        with _LIMITS_LOCK:
            _TRACKED_FUNDS = funds
            _TRACKED_BY_CODE = {item['code']: item for item in funds}
            _LAST_RELOAD_TS = time.time()
    except Exception as e:
        print(f'[app] 加载限额文件失败: {e}')


def _save_limits_to_file():
    """把当前内存中的基金元数据写回 JSON 文件。"""
    with _LIMITS_LOCK:
        funds = list(_TRACKED_BY_CODE.values())
    with open(_TRACKED_FUNDS_PATH, 'w', encoding='utf-8') as f:
        json.dump(funds, f, ensure_ascii=False, indent=2)


def _maybe_reload_limits():
    """如果配置了自动重载，且距离上次重载超过间隔，则检查文件并reload。"""
    if config.LIMITS_RELOAD_INTERVAL_SECONDS <= 0:
        return
    with _LIMITS_LOCK:
        last = _LAST_RELOAD_TS
    if time.time() - last < config.LIMITS_RELOAD_INTERVAL_SECONDS:
        return
    try:
        mtime = os.path.getmtime(_TRACKED_FUNDS_PATH)
    except OSError:
        return
    # 简单策略：超过间隔就reload；文件修改时间变化不是必须的（避免时钟问题）
    _load_limits_from_file()


def _clear_api_cache():
    """限额变更后清理相关缓存，确保前端立即看到新值。"""
    cache.clear()


# 启动时加载一次
_load_limits_from_file()


def _require_admin_token():
    """简单的管理接口鉴权。"""
    auth_header = request.headers.get('Authorization', '')
    token = ''
    if auth_header.lower().startswith('bearer '):
        token = auth_header[7:]
    else:
        token = request.headers.get('X-Admin-Token', '') or request.args.get('token', '')

    if token != config.ADMIN_TOKEN:
        return jsonify({'success': False, 'message': '未授权'}), 401
    return None


def _format_limit(value):
    """金额格式化，支持特殊状态。"""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return '-'
    if value == 0:
        return '暂停申购'
    if value >= 100_000_000:
        return '不限购'
    if value >= 10000:
        return f'{value // 10000}万'
    return str(value)


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _merge_fund_data(meta, realtime):
    """把天天基金实时数据与本地元数据合并成前端需要的结构。"""
    base_price = _to_float(realtime.get('dwjz'), 0.0)
    price = _to_float(realtime.get('gsz'), base_price)
    change_pct = _to_float(realtime.get('gszzl'), 0.0)
    change = round(price - base_price, 4)

    with _LIMITS_LOCK:
        limit = _TRACKED_BY_CODE.get(meta['code'], {}).get('limit', meta.get('limit', 0))

    return {
        'code': realtime.get('fundcode', meta['code']),
        'name': realtime.get('name', meta['name']),
        'category': meta.get('category', '其他'),
        'basePrice': base_price,
        'limit': limit,
        'price': price,
        'change': change,
        'changePct': change_pct,
        'limitText': _format_limit(limit),
        'updateTime': realtime.get('gztime', '')
    }


def _build_all_funds():
    _maybe_reload_limits()
    with _LIMITS_LOCK:
        by_code = dict(_TRACKED_BY_CODE)

    codes = list(by_code.keys())
    results, errors = fund_client.fetch_all_estimates(codes)

    data = []
    for code, meta in by_code.items():
        realtime = results.get(code)
        if realtime:
            data.append(_merge_fund_data(meta, realtime))
        else:
            with _LIMITS_LOCK:
                limit = _TRACKED_BY_CODE.get(code, meta).get('limit', 0)
            data.append({
                'code': meta['code'],
                'name': meta['name'],
                'category': meta.get('category', '其他'),
                'basePrice': 0.0,
                'limit': limit,
                'price': 0.0,
                'change': 0.0,
                'changePct': 0.0,
                'limitText': _format_limit(limit),
                'updateTime': '',
                'error': errors.get(code, '数据暂不可用')
            })

    return data, errors


def _now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat()


@app.route('/api/health', methods=['GET'])
def health():
    _maybe_reload_limits()
    return jsonify({
        'status': 'ok',
        'timestamp': _now_iso(),
        'tracked_count': len(_TRACKED_FUNDS),
        'auto_reload_interval_seconds': config.LIMITS_RELOAD_INTERVAL_SECONDS
    })


@app.route('/api/funds', methods=['GET'])
def get_funds():
    cached = cache.get('all_funds')
    if cached:
        return jsonify(cached)

    data, errors = _build_all_funds()
    payload = {
        'success': True,
        'data': data,
        'source': 'tiantian',
        'cachedAt': _now_iso()
    }
    if errors:
        payload['errors'] = errors

    cache.set('all_funds', payload)
    return jsonify(payload)


@app.route('/api/funds/<code>', methods=['GET'])
def get_fund(code):
    _maybe_reload_limits()
    code = code.strip()
    with _LIMITS_LOCK:
        meta = _TRACKED_BY_CODE.get(code)
    if not meta:
        return jsonify({'success': False, 'message': '未跟踪该基金'}), 404

    cache_key = f'fund:{code}'
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached)

    try:
        realtime = fund_client.fetch_estimate(code)
        data = _merge_fund_data(meta, realtime)
        payload = {
            'success': True,
            'data': data,
            'source': 'tiantian',
            'cachedAt': _now_iso()
        }
        cache.set(cache_key, payload)
        return jsonify(payload)
    except Exception as e:
        # 对无实时估值的基金（如 FOF、暂停申购基金）返回占位数据，避免详情页空白
        with _LIMITS_LOCK:
            limit = _TRACKED_BY_CODE.get(code, meta).get('limit', 0)
        data = {
            'code': meta['code'],
            'name': meta['name'],
            'category': meta.get('category', '其他'),
            'basePrice': 0.0,
            'limit': limit,
            'price': 0.0,
            'change': 0.0,
            'changePct': 0.0,
            'limitText': _format_limit(limit),
            'updateTime': '',
            'error': f'实时估值暂不可用: {e}'
        }
        payload = {
            'success': True,
            'data': data,
            'source': 'fallback',
            'cachedAt': _now_iso()
        }
        cache.set(cache_key, payload)
        return jsonify(payload)


# ==================== 管理接口 ====================

@app.route('/api/admin/limits', methods=['GET'])
def admin_list_limits():
    """查询当前所有基金的限额配置。"""
    auth_error = _require_admin_token()
    if auth_error:
        return auth_error

    _maybe_reload_limits()
    with _LIMITS_LOCK:
        items = [
            {
                'code': item['code'],
                'name': item['name'],
                'category': item.get('category', '其他'),
                'limit': item.get('limit', 0)
            }
            for item in _TRACKED_FUNDS
        ]
    return jsonify({'success': True, 'data': items, 'count': len(items)})


@app.route('/api/admin/limits', methods=['POST'])
def admin_update_limits():
    """更新一只或多只基金的限额。

    请求体示例（单只）：
        {"code": "015299", "limit": 200}
    请求体示例（批量）：
        {"items": [{"code": "015299", "limit": 200}, {"code": "019172", "limit": 20}]}
    """
    auth_error = _require_admin_token()
    if auth_error:
        return auth_error

    body = request.get_json(silent=True) or {}
    updates = []

    if 'items' in body and isinstance(body['items'], list):
        updates = body['items']
    elif 'code' in body and 'limit' in body:
        updates = [{'code': body['code'], 'limit': body['limit']}]
    else:
        return jsonify({
            'success': False,
            'message': '请求格式错误，请提供 {"code","limit"} 或 {"items":[...]}'
        }), 400

    updated = []
    failed = []
    with _LIMITS_LOCK:
        for upd in updates:
            code = str(upd.get('code', '')).strip()
            limit = upd.get('limit')
            if code not in _TRACKED_BY_CODE:
                failed.append({'code': code, 'reason': '未跟踪该基金'})
                continue
            try:
                limit = int(limit)
                if limit < 0:
                    raise ValueError('limit 不能为负数')
            except (TypeError, ValueError):
                failed.append({'code': code, 'reason': 'limit 必须是正整数'})
                continue

            _TRACKED_BY_CODE[code]['limit'] = limit
            updated.append({'code': code, 'name': _TRACKED_BY_CODE[code]['name'], 'limit': limit})

    if updated:
        _save_limits_to_file()
        _clear_api_cache()

    return jsonify({
        'success': len(failed) == 0,
        'updated': updated,
        'failed': failed,
        'count': len(updated)
    })


@app.route('/api/admin/limits/reload', methods=['POST'])
def admin_reload_limits():
    """强制从 JSON 文件重新加载限额配置。"""
    auth_error = _require_admin_token()
    if auth_error:
        return auth_error

    _load_limits_from_file()
    _clear_api_cache()
    return jsonify({
        'success': True,
        'message': '限额配置已重新加载',
        'count': len(_TRACKED_FUNDS)
    })


@app.route('/api/admin/limits/sync', methods=['POST'])
def admin_sync_limits():
    """从 AKShare（天天基金数据源）同步最新限购额度并持久化。"""
    global _TRACKED_FUNDS, _TRACKED_BY_CODE
    auth_error = _require_admin_token()
    if auth_error:
        return auth_error

    try:
        with _LIMITS_LOCK:
            funds = list(_TRACKED_FUNDS)
        updated, failed = limit_sync.sync_limits_from_akshare(funds)

        if updated or failed:
            with _LIMITS_LOCK:
                _TRACKED_FUNDS = funds
                _TRACKED_BY_CODE = {item['code']: item for item in funds}
            _save_limits_to_file()
            _clear_api_cache()

        return jsonify({
            'success': True,
            'message': '限额同步完成',
            'updated': updated,
            'failed': failed,
            'updated_count': len(updated),
            'failed_count': len(failed)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'同步失败: {e}'
        }), 500


@app.errorhandler(Exception)
def handle_error(e):
    return jsonify({
        'success': False,
        'message': f'服务器内部错误: {e}'
    }), 500


# ==================== 定时自动同步限额 ====================

_sync_stop_event = threading.Event()
_sync_thread = None


def _sync_worker():
    """后台线程：按配置间隔自动同步限额。"""
    global _TRACKED_FUNDS, _TRACKED_BY_CODE
    interval = config.LIMITS_SYNC_INTERVAL_SECONDS
    if interval <= 0:
        print('[app] 定时同步已关闭')
        return

    print(f'[app] 定时同步线程启动，间隔 {interval} 秒')
    while not _sync_stop_event.is_set():
        # 等待指定间隔，或被停止
        if _sync_stop_event.wait(interval):
            break

        if config.LIMITS_SYNC_INTERVAL_SECONDS <= 0:
            continue

        try:
            print('[app] 定时同步限额开始...')
            with _LIMITS_LOCK:
                funds = list(_TRACKED_FUNDS)
            updated, failed = limit_sync.sync_limits_from_akshare(funds)

            if updated or failed:
                with _LIMITS_LOCK:
                    _TRACKED_FUNDS = funds
                    _TRACKED_BY_CODE = {item['code']: item for item in funds}
                _save_limits_to_file()
                _clear_api_cache()

            print(f'[app] 定时同步完成，更新 {len(updated)} 只，失败 {len(failed)} 只')
        except Exception as e:
            print(f'[app] 定时同步失败: {e}')


def _should_start_sync_scheduler():
    """避免 Flask Debug 重载器启动两个调度线程。"""
    # WERKZEUG_RUN_MAIN='true' 表示当前是重载后的子进程（真正服务的进程）
    # 非 debug 模式或生产环境直接启动
    return os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not config.DEBUG


def start_sync_scheduler():
    """启动定时同步线程。"""
    global _sync_thread
    if config.LIMITS_SYNC_INTERVAL_SECONDS <= 0:
        return
    if _sync_thread is not None and _sync_thread.is_alive():
        return
    if not _should_start_sync_scheduler():
        return

    _sync_stop_event.clear()
    _sync_thread = threading.Thread(target=_sync_worker, daemon=True)
    _sync_thread.start()
    print(f'[app] 定时同步线程已启动，间隔 {config.LIMITS_SYNC_INTERVAL_SECONDS} 秒')


def stop_sync_scheduler():
    """停止定时同步线程。"""
    _sync_stop_event.set()
    if _sync_thread is not None:
        _sync_thread.join(timeout=5)


# ==================== 缓存预热线程 ====================

_cache_warm_stop_event = threading.Event()
_cache_warm_thread = None


def _cache_warm_worker():
    """后台线程：定期预热 /api/funds 缓存，让用户打开小程序时首屏更快。"""
    interval = config.CACHE_WARM_INTERVAL_SECONDS
    if interval <= 0:
        print('[app] 缓存预热已关闭')
        return

    print(f'[app] 缓存预热线程启动，间隔 {interval} 秒')
    while not _cache_warm_stop_event.is_set():
        if _cache_warm_stop_event.wait(interval):
            break

        if config.CACHE_WARM_INTERVAL_SECONDS <= 0:
            continue

        try:
            cached = cache.get('all_funds')
            if cached is None:
                print('[app] 缓存预热中...')
                data, errors = _build_all_funds()
                payload = {
                    'success': True,
                    'data': data,
                    'source': 'tiantian',
                    'cachedAt': _now_iso()
                }
                if errors:
                    payload['errors'] = errors
                cache.set('all_funds', payload)
                print(f'[app] 缓存预热完成，{len(data)} 只基金')
        except Exception as e:
            print(f'[app] 缓存预热失败: {e}')


def start_cache_warmer():
    """启动缓存预热线程。"""
    global _cache_warm_thread
    if config.CACHE_WARM_INTERVAL_SECONDS <= 0:
        return
    if _cache_warm_thread is not None and _cache_warm_thread.is_alive():
        return
    if not _should_start_sync_scheduler():
        return

    _cache_warm_stop_event.clear()
    _cache_warm_thread = threading.Thread(target=_cache_warm_worker, daemon=True)
    _cache_warm_thread.start()
    print(f'[app] 缓存预热线程已启动，间隔 {config.CACHE_WARM_INTERVAL_SECONDS} 秒')


def stop_cache_warmer():
    """停止缓存预热线程。"""
    _cache_warm_stop_event.set()
    if _cache_warm_thread is not None:
        _cache_warm_thread.join(timeout=5)


start_sync_scheduler()
start_cache_warmer()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=config.PORT, debug=config.DEBUG)
