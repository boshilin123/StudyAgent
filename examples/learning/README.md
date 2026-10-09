# StudyAgent 可运行学习实验

更新日期：2026-10-07。三个实验均使用项目锁定依赖，是后续 PDF 的可执行依据。

## 1. 环境和运行方法

从项目根目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\准备学习环境.ps1
& '.\apps\api\.venv\Scripts\python.exe' '.\examples\learning\rag_context.py'
& '.\apps\api\.venv\Scripts\python.exe' '.\examples\learning\agent_tool_loop.py'
& '.\apps\api\.venv\Scripts\python.exe' '.\examples\learning\langgraph_review.py'
```

环境已准备好时可加 `-SkipInstall`，只做版本与运行验证。命令指定默认 `.venv`，不依赖终端是否激活环境。

## 2. 资料分块与生成上下文

代码：[rag_context.py](rag_context.py)。类型：完整可运行的离线实验，调用生产分块与上下文函数。

输入为带页码、标题 metadata 的 64 页固定文本；参数为 800 字符和 120 字符重叠。重复运行得到相同 chunk ID。24,000 字符预算选入前 37 个片段，最终上下文 23,984 字符，第 64 页没有进入输入。

当前出题为顺序材料拼接，不能保证长资料全面覆盖。字符长度不能当作模型 Token 数量；当前函数保留超预算首片段，计数不包含分隔符。实验没有调用 Embedding 或检索服务。

练习：改变预算或资料顺序，观察选入页码。思考如何用分批生成和批次去重实现完整覆盖。

## 3. Agent 工具循环

代码：[agent_tool_loop.py](agent_tool_loop.py)。类型：完整可运行实验；使用生产 `create_tutor_agent`，模型与工具数据为固定 fixture。

观察 `Model → search_learning_materials → ToolMessage → Model → TutorAnswerDraft`。正常案例返回 `answered` 与 `fixture:tcp:1`；空资料案例返回 `insufficient_evidence`，没有引用。两例各有两次模型调用、一次业务工具调用，并验证 ToolMessage 对应的调用 ID。

`TutorContext` 固定访问范围，工具通过 `Command` 更新证据，`validate_draft` 检查引用。模拟模型没有真实 Token 统计，输出为 `total_tokens: null`、`known: false`。

练习：把引用 ID 改成不存在的值，观察校验失败。实验仅提供资料工具需要的查询接口，学习进度和错题实现应阅读生产 `LearningQueries`。脚本化模型不证明真实供应商能力或答案质量。

## 4. 手写 LangGraph 审核与恢复

代码：[langgraph_review.py](langgraph_review.py)。类型：教学简化的独立图，不接入产品路由或业务数据库。

流程为 `START → retrieve → 条件边 → draft → review → END`；缺资料时走 `missing → END`。State 的 `trace` reducer 累积轨迹，`InMemorySaver` 保存本进程内检查点。

执行到 `interrupt` 后暂停在 `review`。本实验复用同一图对象、保存器和 `thread_id`，通过 `Command(resume=True/False)` 恢复，分别返回 `accepted` / `rejected`。一般恢复需要兼容的图结构、相同线程及可读取原检查点的保存后端，不要求同一个 Python 图对象。缺资料案例返回 `insufficient_evidence`。

恢复会从中断节点开头重新执行，因此中断前的副作用须有幂等保护。内存检查点不证明重启持久性；产品 PostgreSQL 检查点与业务接受指针另有集成验收。这个例子不表示产品新增了人工审核功能。

练习：改用新 thread_id 尝试恢复；再阅读 `TutorService.submit`，解释为何失败轮次不能直接恢复最新 checkpoint。

接口已核对 [Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api) 和 [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)，并在锁定的 LangGraph 1.2.12 实际运行。
