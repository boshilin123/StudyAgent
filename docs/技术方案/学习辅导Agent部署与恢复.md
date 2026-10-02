# 学习辅导 Agent：部署、存储和恢复

实现版本：`tutor-v1`。入口为 `/api/tutor/*`，非流式 HTTP 提交。
本模块使用 `langchain.agents.create_agent`、`ToolRuntime[TutorContext]`、`Command` 状态更新和 `ToolStrategy(TutorAnswerDraft)`。
四个工具都是只读业务查询。模型自行选择工具；权限、预算、引用和最终业务提交由程序验证。

## 部署顺序

1. 使用 `apps/api/requirements.lock` 安装依赖。Python 需要 3.12 或更新的项目支持版本。
2. 为业务数据库执行 `alembic upgrade head`，建立 `0005` 的三个辅导业务表。
3. 在同一应用配置下执行 `python -m study_agent.infrastructure.checkpointer`，由框架建立 PostgreSQL 检查点表。
4. 启动 API 和前端。先访问原有健康检查，再创建一个辅导会话，检索资料并发送第二轮追问。

应用启动只做检查点表的只读探测，绝不自动 `setup()`。若检查点存储未初始化或无法连接，
辅导新运行返回 `TUTOR_CHECKPOINT_UNAVAILABLE`，原学习与资料功能仍可启动。
探测连接和获取等待限制为 3 秒；不会在启动或每轮请求中调用真实模型付费探测。

Windows 下 psycopg 异步连接需要 Selector event loop。检查点 CLI 已使用
`asyncio.Runner(loop_factory=study_agent.runtime.create_event_loop)`。
Uvicorn 启动请使用项目 README 中的 Windows 命令和
`--loop study_agent.runtime:create_event_loop`，不要使用默认 Proactor loop。

## 模型与配置

`TUTOR_LLM_BASE_URL / TUTOR_LLM_API_KEY / TUTOR_LLM_MODEL` 按字段继承普通 `LLM_*` 配置。
辅导统一调用 `get_chat_model(settings, purpose="tutoring")`。默认模型输出上限 1500 Token，
SDK 重试关闭，避免其隐式重试绕过调用计数。
模型必须支持工具循环和结构化输出组合；不支持或 provider 拒绝该组合时明确报错，
不会静默改成普通聊天、第二个格式化模型或内存持久化。
真实兼容性需要运行验收脚本确认，`bind_tools()` 方法存在不能证明服务商已经兼容。

官方 DeepSeek endpoint 的辅导用途使用原生 `thinking: {type: "disabled"|"enabled"}` 参数，
由现有 `LLM_ENABLE_THINKING` 或辅导覆盖值决定；其他用途保留既有 adapter 行为。
DeepSeek 的 thinking 默认开启，`enable_thinking:false` 不是它的原生关闭参数。
首版 ToolStrategy 使用强制工具选择，官方接口只在非思考模式支持该组合。
保持默认 false 即可使用非思考模式；显式开启 thinking 或关闭参数发送时，
若服务器拒绝该组合，返回 `TUTOR_MODEL_CONFIGURATION_INVALID`，不悄悄修改用户偏好。
其他 provider 400 返回 `TUTOR_PROVIDER_REQUEST_REJECTED`；不把所有参数错误都当作模型不支持工具。
依据：[DeepSeek Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)。

- `TUTOR_ENABLED`：辅导开关，默认开启。
- `TUTOR_TIMEOUT_SECONDS`：整轮期限，默认 90 秒。
- `TUTOR_MAX_TOOL_CALLS`：业务工具调用预算，默认 6。
- `TUTOR_MAX_TOOL_RESULT_CHARS`：累计工具结果上下文预算，默认 16000 字符。
- `TUTOR_MAX_MESSAGES`：最多读取 20 条已完成轮次的用户/助手业务消息。
- `TUTOR_CHECKPOINTER_DB_URL`：可选检查点数据库，默认业务数据库。应用自动转换 asyncpg URL 为 psycopg URL。
- 单轮固定最多 6 次模型调用、2 次检索、一次结构化修复；单次模型最多 30 秒、工具最多 10 秒，均受剩余整轮期限约束。
- 不可得用量显示 `known=false, total_tokens=null`。框架结构化输出虚拟工具和业务工具分开计数。

## 并发与存储

应用生命周期内建立独立辅导 advisory-lock 连接池：4 条连接、无 overflow、获取等待 0.1 秒。
整轮运行占用一条锁连接，与普通业务 SQLAlchemy 池分离。达到上限返回
`TUTOR_CONCURRENCY_LIMIT`，不会无限占满业务池。
每轮工具显式串行化，供应商一次返回多个 tool calls 也共享同一预算。

同会话 PostgreSQL session advisory lock 保护完整运行；不同会话独立。
`(conversation_id, client_message_id)` 数据库唯一约束和请求哈希共同实现幂等。
相同 ID、相同载荷重放完成结果，运行中返回 202；不同载荷返回 409。
锁持有者提交幂等记录前存在一个短窗口：竞争请求只读地等待该记录可见，绝不再次进入图。
不同新 ID 竞争同会话时返回 `TUTOR_THREAD_BUSY`。

会话范围由服务端绑定；请求 Schema 禁止提交 history、system prompt、工具配置、thread 或 checkpoint ID。
答后入口须对应数据库真实答题记录。当前知识库存在 active mock_exam 时，创建、运行、工具和最终提交都检查并拒绝。

`tutor_conversations`、`tutor_turns`、`tutor_messages` 保存业务绑定、轮次状态和已验证回复。
会话持有最后已接受 checkpoint ID；每轮从这个指针分支，并重置本轮 evidence、flags 和最终 structured_response。
模型失败、非法引用、超时等中间输出不进入已提交历史；失败用户消息仍可在业务界面查看。

## 中断后恢复

刷新后调用 `GET /api/tutor/conversations/{conversation_id}/turns/{turn_id}`。
同 ID POST 重试也会查询原轮次，不重新付费运行失败轮次。
客户端未收到 turn ID 时应保留原 client_message_id 和载荷，重发同一请求。

只有成功获取会话运行锁时，恢复器才判断遗留 running：

1. 最终 checkpoint 已写入但业务提交未完成：检查 snapshot 无待执行节点、turn ID 匹配且存在本轮结构草稿，重新验证范围、考试和引用，完成短事务提交。
2. 模型或工具中途退出，无法证明最终草稿完整：标记 `TUTOR_INTERRUPTED`；原已接受指针保留。
3. 显式重新尝试必须使用新 client_message_id，从原已接受业务历史开始。

用户消息、助手消息、轮次完成状态和已接受 checkpoint 指针在同一个短业务事务中提交。
检查点写入由框架独立事务管理，不宣称两套事务天然原子。
每轮 trace 包含 `execution_kind=agent`、版本和真实模型/业务工具调用条目；恢复用量未知时不填虚假零成本。

## 运维边界

- 检查点持久化和业务表必须同时备份；只保留前端消息不足以恢复。
- `RESTRICT` 外键保留会话绑定对象。维护性硬删除时先按明确会话范围删除辅导业务记录，再删除学习会话/题目/知识库；同时使用所锁版本的 checkpoint 清理 API 清理图线程。
- 本版没有自动 TTL 清理。设计草案中的“会话 30 天、轨迹 14 天”仍是建议，未实现定时任务。
- 图/状态版本不兼容时拒绝旧会话新运行并要求新建，不盲目迁移 checkpoint。
- 没有 durable task broker；浏览器断开不保证后台任务继续运行。取消时记录 cancelled，重启遗留轮次按上述恢复规则处理。
- 资料可能在最终引用复核后再次变化。历史引用展示再次复核并标注失效，不承诺永久实时一致。
- 自由资料问答中的改写题干语义识别和每句回答的事实忠实度不是确定性权限证明；需独立真实模型/人工质量集评测。
- 对话和必要引用写入 PostgreSQL/checkpoint，问题与资料片段会发送配置的模型服务；本功能不是不落地或纯本地推理。

## 已提供的确定性开发验证

`test_tutor_agent.py` 和 `test_tutor_budget.py` 使用脚本化模型驱动真实 v1 Agent 图，
覆盖工具请求→匹配 ToolMessage→结构化回复、非法引用、必需工具、额外参数/范围注入、
并行工具预算、重复检索、结构化修复、超时、未知用量、二轮状态重置和失败 checkpoint 分支隔离。
这些验证证明框架控制流程，不替代真实 provider 能力验证，也不证明自然语言质量。
独立验收 Agent 提供更完整的 PostgreSQL/HTTP/故障/真实模型报告，以最终报告为执行结果依据。
