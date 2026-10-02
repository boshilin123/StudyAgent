# StudyAgent

## LangChain v1 与学习辅导升级

本轮新增 LangChain v1 依赖锁、统一模型入口、课程命名对齐和学习辅导单 Agent。辅导页面位于 `/tutor`，支持资料问答、答后追问、学习进度及错题分析；工具只读，最终回复需要取证与引用校验。完整测试结果见本轮验收报告，历史 P8/P9/P10 结果不替代新版本验收。

角色分工见 [四个 Subagent 实施分工](docs/技术方案/四个Subagent实施分工.md)，学习入口见 [课程知识点与源码导读](docs/技术方案/课程知识点与源码导读.md)，接口见 [学习辅导接口](docs/接口文档/学习辅导接口.md)。

辅导模型可通过 `TUTOR_LLM_*` 独立配置，留空则继承 `LLM_*`。它必须支持工具调用及所选结构化输出组合；旧出题 parser 可用不代表模型能用于辅导。

依赖升级后需要重建应用镜像。数据库正常迁移后，首次启用辅导须显式初始化 PostgreSQL 检查点：

```powershell
docker compose build api worker web
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m study_agent.infrastructure.checkpointer
docker compose up -d api worker web
```

该初始化只管理框架检查点表。API 启动仅探测，不自动建表；检查点不可用时辅导明确报错，原学习业务继续运行。

## P10 可靠性加固

已修复填空语义符号丢失、任务派发失败阻塞、并发提交与知识点统计竞争、资料来源失效及旧向量残留。
新增真实依赖就绪检查、Worker 健康检查、后端精确依赖锁、PostgreSQL 并发回归和浏览器端到端测试。
详细验证与复现命令见 [P10 可靠性加固与回归验证](docs/技术方案/P10可靠性加固与回归验证.md)。

开发端口默认仅绑定本机。生产部署必须设置 32 位以上 URL-safe `API_ACCESS_TOKEN`；前端右上角“访问令牌”可录入，公网部署还需 HTTPS 反向代理。

面向个人职业学习和考试备考的 AI 自适应学习陪练平台。

当前仓库已完成 P0～P8：工程与数据基础、资料解析与双索引、题库生成 RAG、客观题学习闭环、自适应选题、LangChain 引用讲解、Redis 可恢复运行态、Vue 前端闭环、生产部署方案，以及外部 Embedding 与真实模型评测收尾。

P9 增加了 GitHub Actions 干净环境验证和全面真实链路验收，覆盖错误契约、资料去重、重建索引、题库审核、幂等作答与归档保护。

## 技术栈

- 后端：Python 3.12、FastAPI、SQLAlchemy、Alembic、Celery、LangChain v1、LangGraph。
- 前端：Vue 3、TypeScript、Vite、Pinia、Element Plus。
- 数据：PostgreSQL、Milvus、Redis、S3 兼容对象存储（本地使用 RustFS）。
- 部署：Docker Compose。

## 目录

```text
apps/api/       FastAPI、Worker、数据库迁移和测试
apps/web/       Vue 3 前端
docs/           中文技术、接口和部署文档
infra/          后续基础设施配置
scripts/        本地开发脚本
data/           本地运行数据目录
compose.yaml    开发环境服务编排
```

## 快速开始

### Docker Compose

```powershell
Copy-Item .env.example .env
docker compose up -d --wait --wait-timeout 180
docker compose exec -T api python -m study_agent.infrastructure.checkpointer
docker compose restart api
docker compose up -d --no-deps --wait --wait-timeout 180 api
```

启动后：

- Web：<http://localhost:55173>
- API 文档：<http://localhost:58000/docs>
- API 存活检查：<http://localhost:58000/api/health/live>
- 对象存储控制台：<http://localhost:59001>
- Milvus：`localhost:59530`
- PostgreSQL：`localhost:55432`
- Redis：`localhost:56379`

也可以执行：

```powershell
.\scripts\dev.ps1
```

Windows 任意目录的一行启动命令（先启动 Docker Desktop）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\Study\StudyAgent\scripts\dev.ps1
```

脚本默认后台启动全部开发服务，等待容器及 Web/API 就绪后自动打开浏览器；可以关闭终端，服务仍会运行。首次运行会从 `.env.example` 创建 `.env`，缺少镜像时自动构建，真实模型功能需填写密钥。页面端口取实际 Compose 配置（默认示例为 `55173`）。

首次启用辅导时，还须执行上述检查点初始化、API 重启及等待命令；后续运行无需重复初始化。`dev.ps1` 负责服务启动，检查点仍通过显式部署命令管理。

可选参数：`-NoBrowser` 不自动打开页面；`-FollowLogs` 仅跟踪 API、Worker 和 Web 日志；修改依赖或 Dockerfile 后使用 `-Rebuild` 重建镜像。直接用 Compose 后台启动则不会自动打开页面：

```powershell
docker compose --project-directory D:\Study\StudyAgent up -d --build
```

Milvus 的 `INFO` 日志是后台同步、调度和数据维护信息，不代表启动失败。日常启动不再持续输出这些日志；排查时按需查看：

```powershell
docker compose --project-directory D:\Study\StudyAgent logs --tail 100 api worker web
docker compose --project-directory D:\Study\StudyAgent logs --tail 100 milvus
```

停止服务但保留数据：

```powershell
docker compose --project-directory D:\Study\StudyAgent stop
```

启动脚本的 Windows PowerShell 5.1 回归：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\tests\Test-DevStartup.ps1
```

### 分别运行

后端：

```powershell
Set-Location apps/api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps -e .
uvicorn study_agent.main:app --loop study_agent.runtime:create_event_loop --reload
```

前端：

```powershell
Set-Location apps/web
npm.cmd ci
npm.cmd run dev
```

## 当前可用能力

- FastAPI 应用与 OpenAPI。
- `/api/health/live` 和 `/api/health/ready`。
- 知识库创建、列表、详情和归档更新接口。
- 资料上传、哈希去重、列表、详情、删除和处理任务查询接口。
- PostgreSQL 初始迁移、Repository、Unit of Work 和统一错误响应。
- S3 协议对象存储适配器与本地文件存储替代实现；Compose 本地环境使用 RustFS。
- PDF、DOCX、PPTX、TXT、Markdown、XLSX 解析与 LangChain `Document` 标准化。
- LangChain 文本切块、Celery Chain 异步处理、失败重试和任务进度。
- Milvus 原文向量索引，以及按知识库和资料过滤的检索接口。
- LangChain 知识点抽取与单选、填空、判断题生成链，包含来源校验和题目质量门禁。
- 题库生成异步任务、草稿查询、编辑、启用、停用和 Milvus 题库索引。
- 单选、填空、判断题的确定性判分，以及会话恢复、幂等提交、掌握度和复习任务。
- 基于薄弱度、复习到期、历史新鲜度、难度和题型多样性的可解释自适应选题。
- LangChain 原文引用讲解、失败降级和讲解结果持久化。
- Redis 学习会话快照；缓存丢失时从 PostgreSQL 自动重建，与辅导图检查点独立。
- Vue 首页、知识库与资料管理、题库审核、学习工作台、进度与复习页面。
- 辅导会话、四个只读工具、真实工具调用循环、来源验证、消息幂等与 PostgreSQL 检查点。
- 前端支持资料处理状态轮询、题目筛选/编辑/启停、三类客观题作答、判题讲解与来源展示。
- 活动学习会话写入浏览器本地状态，并通过后端 PostgreSQL/Redis 恢复；刷新后可继续作答。
- PostgreSQL、Milvus、Redis、RustFS、API、Worker 和 Web 的 Compose 编排。
- 检索与题库确定性评测脚本、固定输入集和带配置元数据的 JSON 结果。
- 百炼 `text-embedding-v4` 1024 维真实接入、资料重建索引接口，以及 10 条/批兼容处理。
- 可重复的 P8 端到端验收脚本，覆盖上传、解析、检索、题库生成、启用、学习、掌握度和历史记录。
- Element Plus 按需构建、独立生产 Web 镜像和不暴露基础组件端口的生产 Compose。

## 评测

```powershell
.\apps\api\.venv\Scripts\python.exe .\scripts\评测基线.py retrieval `
  --dataset .\evaluation\datasets\TCP检索基线-v1.jsonl `
  --output .\evaluation\results\TCP检索基线.json
```

当前 3 条 TCP 小样本结果仅作为开发基线，不代表通用检索性能。完整说明见 [评测基线与结果](docs/技术方案/评测基线与结果.md)。

P8 已增加 30 条人工标注查询的外部 `text-embedding-v4` 基线，以及 59 道真实生成题目的确定性审计。运行完整验收：

```powershell
.\apps\api\.venv\Scripts\python.exe .\scripts\P8端到端验收.py `
  --knowledge-base-id <知识库ID> `
  --generation-material-id <资料ID> `
  --output .\evaluation\results\P8端到端验收.json
```

运行 P9 全面验收：

```powershell
.\apps\api\.venv\Scripts\python.exe .\scripts\P9全面验收.py `
  --output .\evaluation\results\P9全面验收.json
```

该脚本会创建并归档一个独立验收知识库，真实验证上传、重复检测、解析、检索、重建索引、三类题目生成、题目修订、学习判分、错答讲解、幂等冲突、掌握度、复习和历史记录。

## 干净环境验证

GitHub Actions 会在全新 Ubuntu、Python 3.12 和 Node.js 22 环境中执行后端测试、覆盖率、Ruff、Mypy、`npm ci`、前端类型检查、生产构建、NPM 审计和 Compose 配置检查。

Windows 本地可执行隔离验证，不依赖已有 `node_modules`：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\验证干净环境.ps1
```

只验证前端时添加 `-SkipBackendInstall`。

## 生产构建

```powershell
docker compose -f compose.production.yaml up -d --build
```

生产配置必须设置 `API_ACCESS_TOKEN`，否则编排与应用拒绝启动。已提供单用户 Bearer 令牌门禁，但不等于账号权限系统；公开部署前仍需限流、上传安全和 HTTPS。详见 [生产部署与故障排查](docs/部署文档/生产部署与故障排查.md)。

## 文档

从 [文档索引](docs/文档索引.md) 开始阅读。接口和数据库变更必须同步更新对应文档。
