# 美股基金通 - 后端部署指南

## Railway 部署（推荐）

Railway 提供免费额度，支持自动 HTTPS，不需要域名备案，适合快速上线。

### 前置准备

1. 注册 [GitHub](https://github.com) 账号
2. 注册 [Railway](https://railway.app) 账号（可以用 GitHub 直接登录）
3. 把 `backend/` 目录推到一个独立的 GitHub 仓库

### 目录结构要求

GitHub 仓库根目录必须是 `backend/` 的内容，即：

```
us-fund-backend/
├── app.py
├── config.py
├── data/
├── services/
├── requirements.txt
├── Procfile
├── runtime.txt
└── .gitignore
```

### 部署步骤

1. **新建 GitHub 仓库**
   - 仓库名例如 `us-fund-backend`
   - 把本目录所有文件上传

2. **登录 Railway**
   - 访问 https://railway.app
   - 用 GitHub 账号登录

3. **创建项目**
   - 点击 "New Project"
   - 选择 "Deploy from GitHub repo"
   - 选择你的 `us-fund-backend` 仓库

4. **配置环境变量**
   - 进入项目 → 选择你的服务 → Variables
   - 添加以下变量：
     ```
     ADMIN_TOKEN=你的强密码
     LIMITS_SYNC_INTERVAL_SECONDS=3600
     CACHE_WARM_INTERVAL_SECONDS=10
     LIMITS_RELOAD_INTERVAL_SECONDS=60
     ```

5. **等待自动部署**
   - Railway 会自动识别 `Procfile` 和 `requirements.txt`
   - 构建完成后会生成一个 HTTPS 域名，例如：
     ```
     https://us-fund-backend-production.up.railway.app
     ```

6. **测试接口**
   - 浏览器访问：
     ```
     https://你的域名/api/health
     ```
   - 应返回：
     ```json
     {"status":"ok","tracked_count":61,"auto_reload_interval_seconds":60}
     ```

7. **配置小程序**
   - 修改 `app.js`：
     ```javascript
     apiBase: 'https://你的域名'
     ```
   - 微信公众平台 → 开发 → 开发管理 → 服务器域名 → request合法域名
   - 添加你的 Railway 域名

### 免费版限制

- 一段时间无人访问会进入休眠，首次访问需要 5-15 秒唤醒
- 每月有 500 小时免费执行时间
- 如果用户多或要稳定，建议升级到 Hobby 计划（约 5 美元/月）

## 本地开发

Windows 上 gunicorn 无法运行，用 Flask 自带服务器：

```bash
cd backend
venv\Scripts\activate.bat
python app.py
```

Linux/Mac 本地可以用 gunicorn 测试：

```bash
cd backend
source venv/bin/activate
gunicorn -w 2 -b 0.0.0.0:8000 app:app
```
