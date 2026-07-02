import os

# 服务端口
PORT = int(os.environ.get('PORT', 5000))

# 调试模式
DEBUG = False

# 缓存 TTL（秒）：天天基金数据是估算净值，不需要每秒都请求上游
CACHE_TTL_SECONDS = 5

# 天天基金实时估值接口
TIANTIAN_ESTIMATE_URL = 'http://fundgz.1234567.com.cn/js/{code}.js'

# 天天基金代码搜索接口
TIANTIAN_SEARCH_URL = 'http://fund.eastmoney.com/js/fundcode_search.js'

# 请求超时（秒）
REQUEST_TIMEOUT = 10

# 管理接口认证令牌（生产环境请务必修改为强密码并通过环境变量传入）
ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', 'dev-token-change-me')

# JSON 限额文件自动重载间隔（秒），0 表示关闭
LIMITS_RELOAD_INTERVAL_SECONDS = int(os.environ.get('LIMITS_RELOAD_INTERVAL_SECONDS', 60))

# AKShare 限额定时同步间隔（秒），0 表示关闭自动同步，默认 1 小时
LIMITS_SYNC_INTERVAL_SECONDS = int(os.environ.get('LIMITS_SYNC_INTERVAL_SECONDS', 3600))

# 基金行情缓存预热间隔（秒），0 表示关闭，默认 10 秒
CACHE_WARM_INTERVAL_SECONDS = int(os.environ.get('CACHE_WARM_INTERVAL_SECONDS', 10))

# 允许的前端来源（生产环境应配置为小程序上线域名）
CORS_ORIGINS = os.environ.get('CORS_ORIGINS', '*').split(',')
