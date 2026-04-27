# news_writer backend

AI 新闻写作助手后端（FastAPI + PostgreSQL + Redis + MinIO）。

## Quick start

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env，至少设置 AUTH_INITIAL_API_TOKEN、LLM_API_KEY、EMBEDDING_API_KEY

# 2. 起中间件
docker compose up -d postgres redis minio

# 3. 安装依赖
pip install -e ".[dev]"
# 或：uv sync

# 4. 执行迁移
alembic upgrade head

# 5. 启动
uvicorn app.main:app --reload

# 6. 冒烟
curl http://localhost:8000/api/v1/health
```

## 契约文档

两份**只读**契约：

- `../docs/specs/2026-04-23-shared-conventions.md`
- `../docs/specs/2026-04-23-api-contract.md`

## 目录

```
app/
├── api/v1/          路由层
├── core/            配置、日志、错误、鉴权
├── db/              SQLAlchemy base/session
├── models/          ORM 模型
├── providers/       LLM / Embedding / 新闻 / 搜图 / 存储 抽象
├── prompts/         LLM prompt 模板（markdown）
├── repositories/    数据访问
├── schemas/         Pydantic schema
├── services/        业务逻辑
├── tasks/           APScheduler 定时任务
├── utils/           工具
└── data/            种子数据
alembic/             迁移
tests/               测试
scripts/             端到端冒烟脚本
```
