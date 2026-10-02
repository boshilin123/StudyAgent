# LangChain v1、命名规范与学习辅导 Agent 开发方案

日期：2026-10-01。版本：设计基线 v0.1。状态：用户已于 2026-10-01 授权开始三项升级与独立验收，正在实施。

实施授权：用户要求设计四个 subagent，前三个分别完成命名规范、LangChain v1、学习辅导助手，第四个在整体代码完成后设计详细用例并跑通流程。本文件的建议默认范围作为本次实施基线；测试通过与实现状态以新的验收报告为准。

本文是开发设计基线，不是当前能力说明或测试报告。草案编写轮次只新增了方案与文档索引；当前实施轮次已获用户授权修改代码与依赖。Agent 的工具、状态、持久化、接口、安全和验收细节见 [学习辅导 Agent 详细设计](学习辅导Agent详细设计.md)。

## 1. 本期目标与范围

本期确定三个开发目标：

1. 从 LangChain 0.3 系列迁移到 LangChain v1，并恢复精确版本锁与干净环境可复现。
2. 尽量对齐飞书课程的 Model、Messages、Prompt、Chain、Tool、Agent、Context、State、Store 命名，便于对照源码学习。
3. 实现一个真正使用 `create_agent` 和 Tool Calling 的学习辅导单 Agent，支持资料问答、答后追问、薄弱点分析与复习建议。

业务边界：

- 原有资料上传、题库生成、四种学习模式、确定性判分、幂等提交、掌握度和复习任务继续工作。
- Agent 可以自主选择只读工具，但不能提交答案、修改分数、修改掌握度、写复习任务、启用题目或删除资料。
- 允许 application service 写入辅导会话、消息、运行记录和检查点。这是辅导自身持久化，不是 Agent 获得业务写入工具。
- 初版沿用单用户产品边界和共享 Bearer 门禁，不虚构多租户或账号级隔离。

不包含在本期：

- 将出题流程整体改为 LangGraph、长文档分批出题、Evaluator-Optimizer 出题修复；这些另行立项。
- 默认引入 BM25/RRF/Reranker、HyDE、MCP、多 Agent、Deep Agents 或外部网页搜索。
- 生成式判分、自动学习计划落库、任意 SQL、文件读写、Shell 或浏览器操作工具。
- 修改简历、自动提交 Git、推送 GitHub、删除现有数据或存储卷。

## 2. 当前实现基线与待解决问题

以下结论来自 2026-10-01 的源码和锁文件检查，不代表本轮重新运行过测试。

### 2.1 依赖

- `apps/api/pyproject.toml` 限制 `langchain>=0.3,<1`，明确排除 v1。
- 运行锁与开发锁均固定 `langchain==0.3.30`、`langchain-core==0.3.86`、`langchain-openai==0.3.35`。
- 锁文件由 `uv pip compile` 生成，应重新解析，不能手工替换锁文件中的几个版本号。
- 当前 Python 要求 `>=3.12`，保留 Python 3.12 作为迁移验证环境。

### 2.2 模型与工作流

- `question_generation/chains.py` 使用 LCEL、`ChatPromptTemplate`、Pydantic parser 或 `with_structured_output`。
- `application/study_explanations.py` 独立初始化 `ChatOpenAI`，存在模型配置重复。
- `agents/__init__.py`、`llm/__init__.py` 目前只是占位说明，没有 Agent 工厂或统一模型模块。
- 未实现 `create_agent`、Tool Calling 循环或学习辅导图。
- `AgentRunModel`、`AgentStepModel` 是自定义轨迹记录，不是 Agent 实现证据。
- 旧实施文档将规则驱动的自适应流程称为“受控 Agent”，需要在新的能力说明中澄清。

### 2.3 需要保护的可靠性

- 确定性判分及填空答案归一化规则。
- PostgreSQL 提交幂等、会话锁、知识点并发统计更新。
- 模型讲解在答题主事务之外执行，讲解失败不回滚已提交的学习事实。
- Redis 快照丢失或损坏时从 PostgreSQL 重建。
- 检索结果在数据库侧再次过滤失效来源，不能只相信 Milvus 返回的 ID。
- Celery 长任务、来源失效处理、向量索引清理、干净环境验证与启动脚本。

历史证据参考 [P10 可靠性加固与回归验证](P10可靠性加固与回归验证.md)。历史 62 项后端测试、8 项浏览器测试等结果不能冒充迁移后的验证结果。

## 3. 目标架构与职责

保留 `api → application → domain` 的业务依赖方向，infrastructure 负责数据库、缓存与外部系统适配。

- `llm/`：统一模型创建、模型用途选择、能力配置、Prompt 与调用统计。
- `question_generation/`：继续使用受控 Chain，不因为升级 v1 就改为 Agent。
- `agents/tutor/`：真正的学习辅导 Agent、工具定义、状态、Prompt 与运行限制。
- `application/tutoring.py`：授权范围校验、会话与轮次编排、请求幂等、调用 Agent、最终结果验证。
- `application/learning_queries.py`：面向工具的只读业务查询；不允许工具拼 SQL。
- `application/retrieval.py`：抽取检索与来源有效性检查，供原 HTTP 检索和 Agent 复用。
- `infrastructure/tutoring.py`、`infrastructure/checkpointer.py`：辅导持久化与图检查点适配。
- `api/routes/tutoring.py`：独立辅导 API，保留现有 `/study/*` 契约。
- Vue 新增辅导页面与答后入口，不改变原作答确认及重试逻辑。

核心划分：Agent 负责“读什么、查什么、怎样解释”；application 负责“允许读什么、何时执行、如何保存”；现有 study service 负责“判分与学习事实”。

## 4. LangChain v1 迁移设计

### 4.1 版本策略

- LangChain 主包目标范围为 `>=1,<2`，实施时选择经验证的稳定 v1 版本并精确锁定，不追逐未经验证的最新版本。
- 直接声明代码实际使用的 `langchain-core`、`langchain-openai`、`langgraph` 与持久化集成依赖，版本组合由解析器和兼容验证确定。
- `langchain-community`、`langchain-milvus` 等独立包不机械地使用相同主版本号。清查未使用依赖后再决定保留、升级或移除。
- 当前直接使用 pymilvus；若移除间接提供它的包，必须先显式声明实际所需 pymilvus 依赖。
- 优先使用 v1/core 的现有组件；确实用到移入 `langchain-classic` 的旧功能时才引入 classic，不为迁移临时堆兼容包。
- 不在主运行环境同时维持 v0/v1 两套 LangChain。

复用锁生成方式，在 `apps/api` 的隔离环境中执行：

```powershell
uv pip compile pyproject.toml --python-version 3.12 --universal --output-file requirements.lock
uv pip compile pyproject.toml --extra dev --python-version 3.12 --universal --output-file requirements-dev.lock
```

上面是未来实施命令，不表示本轮已经执行。Windows 与 Linux 均需按新锁安装，并执行 `pip check`、应用导入与现有功能回归。

### 4.2 统一模型入口

拟新增 `llm/models.py`，使用 `get_chat_model(settings, *, purpose)` 统一创建模型。

- 默认按课程使用 `init_chat_model`；OpenAI-compatible 自定义端点保留正确的 provider adapter。
- 如果统一初始化不完整支持现有 provider 参数，允许在同一个工厂内部使用 `ChatOpenAI`，不在业务模块重复初始化。
- `purpose` 初版区分 `question_generation`、`study_explanation`、`tutoring`，调用方不得传入任意 endpoint 或 API key。
- 保留既有 `LLM_*` 配置。辅导可使用独立 `TUTOR_LLM_*` 配置，未设置时显式继承现有配置。
- `enable_thinking` 等供应商扩展参数按能力和配置发送，不强制给所有供应商发送同一扩展参数。
- 保留现有 Chain 的 parser 配置，不把所有模型强制改成 JSON Schema。
- 工厂在进程级缓存中只保存安全可复用的模型/图配置；不得缓存上一个会话的 Context、工具账本或数据库 Session。

### 4.3 模型能力与 Agent 准入

LangChain v1 不会让原模型自动支持 Tool Calling。需要独立记录：工具调用、工具结果回传、组合工具与结构化输出、异步调用等能力。

- Mock 能力测试用于 CI，真实模型能力探测单独执行并记录供应商、模型、日期和结果。
- 实施时先验证工具 Schema 绑定、一次工具调用以及带 ToolMessage 的下一次调用。
- 不支持工具调用时，辅导端点返回明确的 `TUTOR_MODEL_UNSUPPORTED`，原出题/讲解功能继续按既有模式运行。
- 不通过解析自然语言中的“我要调用某工具”伪造 Tool Calling；不静默把普通 Chat 标成 Agent。
- 真实能力探测不放入每次 readiness，避免重复费用和启动失败；运行时配置错误仍需清晰报告。

## 5. 命名对齐与兼容策略

### 5.1 约定

- 函数/变量使用 snake_case，数据结构使用 PascalCase。
- Chain 表示受控模型流水线；Tool 表示 Agent 可调用能力；Node 表示图节点；Agent 表示工具决策循环。
- `Context` 是服务端注入的运行环境，`State` 是图执行与对话状态，跨会话业务事实仍由 repository 管理。
- `checkpointer` 专指图检查点；Redis 学习运行态称为 snapshot/cache。
- 复杂函数可使用少量步骤注释，解释边界、输入输出与设计原因，不逐行翻译代码。

### 5.2 优先调整项

- `question_generation/chains.py::_model` 归并到 `llm/models.py::get_chat_model`。
- `build_knowledge_point_chain` 拟统一为 `create_knowledge_point_chain`；`build_question_chain` 拟统一为 `create_question_generation_chain`。
- `_context` 拟命名为 `build_generation_context`，明确当前仍是字符预算拼接；命名调整不伪装成长资料覆盖优化。
- `validate_generation` 拟命名为 `validate_question_drafts`，保留现有校验语义。
- `get_vector_index` 拟统一为 `get_document_index`，避免资料索引与题目索引含混；现有 factory 同名入口通过清晰 import alias 消除歧义。
- `StudyStateStore`、`RedisStudyStateStore` 拟改为 `LearningSessionSnapshotStore`、`RedisLearningSessionSnapshotStore`；Redis key 保持不变。
- `AgentRunModel`、`AgentStepModel` 拟采用中性 `WorkflowRunModel`、`WorkflowStepModel`。首期保留 `agent_runs`、`agent_steps` 表名和字段，避免无业务收益的历史数据迁移。
- 旧轨迹的 `tool_name=langchain_structured_output` 不再解释为真实工具调用；新的运行类型和 metadata 区分 `chain` 与 `agent`。

上述名称是待审计建议。实施前列出所有引用和测试，必要时短期保留兼容 alias 并注明移除阶段；不批量替换数据库字段、公开 JSON 字段和路由。

### 5.3 学习用文档

交付“课程知识点与源码导读”：列出 Model、LCEL、Structured Output、ToolRuntime、AgentState、Middleware、Checkpointer、Retriever 的源码入口、输入输出和可运行用例。

新旧能力说明同步更新；历史验证文档保留原日期，不改写过去的实现事实。

## 6. 开发阶段及审计门槛

### 阶段 A：方案审计与冻结范围

- 用户审计本方案和 Agent 详细设计，确认第 10 节选择。
- 记录当前 Git 状态、现有 API/OpenAPI 契约、测试集合与数据迁移版本。
- 不因文档存在就开始开发；审计批准后进入下一阶段。

### 阶段 B：v1 迁移与统一模型接入

- 调整 pyproject、两个锁文件、模型工厂及原 Chain/讲解调用点。
- 验证新依赖安装、`pip check`、模块导入、LCEL 和 provider 参数兼容。
- 输出迁移差异及明确测试结果；失败时先修复，不与新 Agent 的失败混合排查。

### 阶段 C：命名对齐

- 按第 5 节逐模块迁移，并同步 imports、类型、Mock、文档与测试。
- 不改数据库物理表名、API 返回字段或原 Redis key。
- 静态检查、导入检查和相关回归通过后结束兼容 alias 过渡。

### 阶段 D：辅导后端最小闭环

- 新增会话、轮次、消息、范围校验、四个只读工具、Agent 工厂和结果验证。
- 先使用脚本化 Fake Model 验证真正的模型/工具循环，再接真实工具调用模型。
- 先完成非流式 POST＋状态查询、请求幂等和真实持久化，不以 InMemorySaver 作为可恢复交付。

### 阶段 E：前端与恢复

- 独立学习辅导页、答后追问入口、引用展开、失败提示、刷新恢复。
- 使用每条辅导请求稳定的 `client_message_id`；网络重试不产生新一轮调用。
- 保留现有作答页面和 Axios 默认行为；辅导超时配置独立。

### 阶段 F：统一验收与源码导读

- 静态、单元、真实 PostgreSQL、浏览器、真实模型能力/业务测试、干净环境和 Compose 验证。
- 按模型与数据集记录结果、耗时、用量、失败与跳过项；不把 Mock 通过写成真实模型通过。
- 用户审计最终实现与证据；是否提交/推送另由用户决定。

## 7. 测试策略与通过标准

- 依赖：两个新锁均可安装，Windows Python 3.12 与 Linux 镜像 `pip check` 通过，不混装 0.3 主包。
- 兼容：原有判分、幂等、并发统计、来源失效、讲解降级、Redis 恢复与四种学习模式回归通过。
- Agent：必须有真实工具选择与 ToolMessage 反馈证据，不能只证明生成了一个回复。
- 安全：范围由服务端绑定；越界 ID、越权工具、未作答题与考试限制等确定性用例全部通过。
- 可靠性：相同消息 ID 重放不重复调用模型；同一会话并发串行化；失败/重启后的轮次状态可解释。
- 引用：已接受的引用必须来自实际工具结果，并经当前数据库有效性复核；结构通过不等于语义正确。
- 质量：人工确认的问答集、错题集和薄弱点场景评分；具体用例及建议门槛见 Agent 详细设计。
- 工程：Ruff、Mypy、前端类型检查/构建通过；后端覆盖率至少保持既有 80% 门槛，新增关键安全分支有直接用例。
- 测试资料与数据库隔离；沿用 `study_agent_test*` 目标检查，不对业务库清理。真实模型测试可能付费，单独开启。

## 8. 交付物

- 经批准的本方案和 Agent 详细设计修订稿。
- v1 锁文件、统一模型工厂、命名迁移清单与兼容验证记录。
- 学习辅导 Agent、只读工具、持久化、API 与前端闭环。
- 评测数据、自动化测试、真实模型运行证据与干净环境验收报告。
- 课程知识点与源码导读、更新后的接口/数据库/部署说明。

## 9. 风险与回退

- 主版本迁移可能改变 imports、输出消息形态和 provider 行为：先完成原功能兼容，再引入 Agent。
- 辅导模型可能不支持组合工具与结构化输出：配置独立模型并通过能力门禁，不假定 OpenAI-compatible 就完全兼容。
- 图检查点与业务库不具备跨事务原子性：轮次状态和最终消息有 application 级提交与故障对账策略。
- 对话历史可能携带失效资料：读取与最终引用验证均再次检查，历史不直接成为有效证据。
- 共享令牌不是多用户隔离：本期不宣称公开部署安全或学习数据的账户级隔离。
- 回退时使用上一组代码及锁文件；先关闭 `TUTOR_ENABLED`，保留新增辅导表，不自动删除数据。已增加的迁移应向后兼容，恢复旧应用前验证。
- 不同时重构旧出题算法、数据库物理命名和 Agent，以便定位失败原因。

## 10. 用户审计清单

以下为建议默认方案，均尚未批准：

- [ ] 同意 LangChain v1 是必选目标，具体稳定小版本在实施时解析和验证。
- [ ] 同意保留业务分层，只规范实际不一致的命名，不整体搬迁目录。
- [ ] 同意 Agent 首期是单 Agent＋四个只读工具，不做多 Agent/MCP。
- [ ] 同意首版禁止未作答题的答案辅导，`mock_exam` 未结束时限制当前知识库的辅导运行。
- [ ] 同意使用 PostgreSQL 持久化 Checkpointer，Redis 学习快照继续独立运行。
- [ ] 同意先做非流式 API；SSE、偏好 Store、混合检索在后续审计中决定。
- [ ] 同意保留原出题链，本期不实施长资料出题和出题评审图。
- [ ] 同意默认预算、保存期限和质量门槛作为待实测调整参数，而非已有性能结论。

用户可直接指出不同意的条目、修改后的边界或需要补充的验收条件。

## 11. 依据与阅读顺序

项目依据：[个人项目最小化改造方案](个人项目最小化改造方案.md)、[数据库设计](数据库设计.md)、[P10 验证记录](P10可靠性加固与回归验证.md)。外部学习依据为用户提供的《LangChain_Agent_RAG_LangGraph_项目改造全量参考手册.md》，该文件位于用户本地资料目录，未作为仓库文件复制。

核对官方文档日期：2026-10-01；实施时仍需根据最终锁定版本复核 API。

- [LangChain v1 迁移指南](https://docs.langchain.com/oss/python/migrate/langchain-v1)：主版本迁移与命名空间。
- [Agents](https://docs.langchain.com/oss/python/langchain/agents)：`create_agent` 工具循环。
- [Tools](https://docs.langchain.com/oss/python/langchain/tools)：`@tool`、`ToolRuntime` 与上下文注入。
- [Structured output](https://docs.langchain.com/oss/python/langchain/structured-output)：ProviderStrategy/ToolStrategy 及能力要求。
- [Middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in)：调用限制等运行约束。
- [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)：检查点与长期存储边界。

审计顺序建议：本文件第 1、3、6、10 节 → Agent 详细设计第 2～7 节 → 持久化/API/故障设计 → 验收用例。
