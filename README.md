---
title: Price Watching Agent
emoji: 💸
colorFrom: green
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# Price Watcher Platform

Price Watcher Platform 是一个用户自定义价格追踪与商品发现网站。用户可以注册/登录，添加商品链接、店铺链接或股票/旅行相关页面，系统会定期检索页面中的候选价格或商品信息，并在看板中展示价格变化和匹配结果。

## 项目特点

- 用户注册/登录：手机号作为用户名，也作为默认通知联系方式。
- 价格追踪：用户输入链接后，系统预览页面中识别到的候选价格，由用户选择要追踪的来源。
- 定时检索：每个追踪任务支持自定义检索间隔，并可手动立即检索。
- 商品发现：支持跟踪店铺链接，结合关键词和用户画像识别可能符合用户偏好的新商品。
- 用户画像原型：根据用户过往追踪、关键词和偏好生成长期画像/提示词 embedding，用于商品匹配评分。
- 看板管理：内部页面支持查看任务、价格趋势、修改检索间隔、删除任务和用户设置。

## 目录结构

- `frontend/`: 静态前端页面，包含首页、登录/注册页、内部看板、价格候选选择和商品发现页面。
- `backend/`: FastAPI 后端，包含用户认证、价格候选提取、定时检索、商品发现和数据库 schema。
- `backend/scrapers/`: 页面价格识别与候选价格提取模块。
- `docs/`: 项目说明、部署说明和报告文档。

## 技术栈

- Frontend: HTML, CSS, JavaScript
- Backend: FastAPI, Pydantic
- Database: Aiven PostgreSQL, pgvector schema prepared
- Deployment: Vercel frontend, Hugging Face Space Docker backend
- Scraping: requests + BeautifulSoup based page extraction prototype

## 当前完成度

已完成：

- 前端首页、认证页和内部看板。
- 用户注册/登录，线上环境支持 PostgreSQL 持久化用户和 hashed password。
- 页面爬虫原型，返回页面中识别到的候选价格并让用户选择追踪来源。
- 价格任务的手动检索、定时检索间隔设置和趋势展示。
- 店铺商品发现原型，结合用户关键词/画像 embedding 进行相似度评分。
- Hugging Face Docker 后端部署配置和 Vercel 静态前端部署配置。

未完成或待增强：

- 真实短信/电话/邮件提醒服务。
- 更强的爬虫能力，例如 Playwright、专业商品/股票/机酒 API 或 LLM 辅助检索。
- 追踪任务完整数据库持久化，目前用户数据已接 PostgreSQL，任务数据仍需进一步迁移。
- 商品、股票、机票、酒店等模块的细分页面和独立策略。

## 本地运行

直接用浏览器打开：

```text
frontend/index.html
```

## 后端本地启动

```powershell
cd backend
pip install -r requirements.txt
uvicorn app:app --reload
```

## Hugging Face 后端部署

项目根目录已提供 `Dockerfile`。创建 Hugging Face Space 时选择 Docker，然后把后端 API 地址配置到前端即可。

后续接 Aiven PostgreSQL 时需要把连接串配置为环境变量：

```text
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DATABASE?sslmode=require
```
