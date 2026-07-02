import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

import config


def _parse_jsonp(text):
    """从天天基金 JSONP 响应中提取 JSON 对象。

    响应格式示例：
        jsonpgz({"fundcode":"040046","name":"...",...});
    """
    text = text.strip()
    if not text:
        return None
    match = re.search(r'\((\{.*?\})\);?$', text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def fetch_estimate(code):
    """获取单只基金的实时估值。

    返回字典字段：
        fundcode, name, jzrq, dwjz, gsz, gszzl, gztime
    """
    url = config.TIANTIAN_ESTIMATE_URL.format(code=code)
    try:
        resp = requests.get(url, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = _parse_jsonp(resp.text)
        if not data:
            raise ValueError(f'无法解析基金 {code} 的响应')
        return data
    except Exception as e:
        raise RuntimeError(f'获取基金 {code} 失败: {e}')


def fetch_all_estimates(codes, max_workers=16):
    """批量获取多只基金的实时估值（并行）。

    参数:
        codes: 基金代码列表
        max_workers: 最大并发线程数，默认 16

    返回:
        results: {code: realtime_data}
        errors: {code: error_message}
    """
    results = {}
    errors = {}

    if not codes:
        return results, errors

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_code = {
            executor.submit(fetch_estimate, code): code
            for code in codes
        }
        for future in as_completed(future_to_code):
            code = future_to_code[future]
            try:
                results[code] = future.result()
            except Exception as e:
                errors[code] = str(e)

    return results, errors
