import math


def sync_limits_from_akshare(funds):
    """使用 AKShare 的 fund_purchase_em 接口同步基金单日累计限购额度。

    参数:
        funds: list[dict] 当前基金列表，每个元素至少包含 'code' 和 'limit'

    返回:
        updated: list[dict] 已更新的基金（含旧值和新值）
        failed: list[str] 未找到限购数据的基金代码
    """
    try:
        import akshare as ak
    except ImportError:
        raise ImportError('请安装 akshare: pip install akshare')

    df = ak.fund_purchase_em()
    if df.empty:
        raise RuntimeError('AKShare 未返回限购数据')

    # 列索引：1=基金代码，10=单日累计限购
    code_col = df.columns[1]
    limit_col = df.columns[10]

    # 构建查询表
    limit_map = {}
    for _, row in df.iterrows():
        code = str(row[code_col]).strip()
        limit = row[limit_col]
        if isinstance(limit, (int, float)) and not math.isnan(limit):
            limit_map[code] = int(limit)

    updated = []
    failed = []
    for item in funds:
        code = item.get('code', '').strip()
        old_limit = item.get('limit', 0)
        if code in limit_map:
            new_limit = limit_map[code]
            if new_limit != old_limit:
                updated.append({
                    'code': code,
                    'name': item.get('name', ''),
                    'old_limit': old_limit,
                    'new_limit': new_limit
                })
            item['limit'] = new_limit
        else:
            failed.append(code)

    return updated, failed
