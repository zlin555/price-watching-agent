# Backend

后端预留目录。

建议后续实现模块：

- 用户注册与登录：保存邮箱、手机号或其他联系方式。
- Profile：记录用户关注的链接、股票代码、提醒阈值和通知偏好。
- 定时抓取任务：对商品、旅行页面、股票价格等进行周期性获取。
- 价格历史：保存每次抓取结果，用于绘制趋势。
- 提醒服务：当价格低于或高于用户目标值时触发短信、邮件或站内提醒。

可选技术栈：

- FastAPI 或 Flask
- PostgreSQL 或 SQLite
- Celery/APScheduler 定时任务
- Twilio/SendGrid/邮件 SMTP 通知

## 本地启动 API

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --reload
```
