# StudyAgent 学习入口

更新日期：2026-10-07（Asia/Shanghai）。八章正式 PDF 已完成，共 **130 页、59 幅截图与图解、53 张表格**。源码基准：`72dea46` 加当前工作区修改；默认 Python 3.12、LangChain 1.4.3、LangGraph 1.2.12。

## 正式教材与阅读顺序

1. [第01章：项目全貌与学习闭环](第01章_项目全貌与学习闭环.pdf)（13 页）：业务入口、分层结构、命名规范、学习路径和证据边界。
2. [第02章：资料解析、字符分块与元数据](第02章_资料解析与字符分块及元数据.pdf)（15 页）：解析器、Document、字符与 Token、稳定 ID、页码与标题。
3. [第03章：Embedding、Milvus 与 RAG 检索](第03章_Embedding与Milvus及RAG检索.pdf)（18 页）：向量化、COSINE、范围过滤、来源复核与证据封装。
4. [第04章：LCEL 出题、结构化输出与质量门禁](第04章_LCEL出题与结构化输出及质量门禁.pdf)（17 页）：两条固定链、Schema、材料覆盖限制、拒绝原因和题库审核。
5. [第05章：辅导 Agent、工具与 Middleware](第05章_辅导Agent与工具及Middleware.pdf)（17 页）：ToolRuntime、工具调用、Command、证据账本、预算和引用校验。
6. [第06章：LangGraph 节点、条件边与中断恢复](第06章_LangGraph节点与条件边及中断恢复.pdf)（14 页）：独立教学图、reducer、Overwrite、interrupt、同线程恢复及生产映射。
7. [第07章：业务状态、检查点与幂等恢复](第07章_业务状态与检查点及幂等恢复.pdf)（18 页）：业务接受指针、重复请求、执行锁、短事务、失败草稿隔离和 Redis 快照。
8. [第08章：自适应学习与评估复盘](第08章_自适应学习与评估复盘.pdf)（18 页）：判分、掌握度、SM-2 风格复习、确定性选题和评估指标。

建议按编号顺序阅读。每章按“场景 → 名词 → 应用 → 流程 → 源码 → 实验 → 结果 → 练习”组织，有可点击目录和书签、函数解释、代码行号及参考思路。源码节选用于定位；标为完整可运行的代码含全部导入，并说明工作目录与输出。

## 本次教材验证

12 个完整离线实验已在默认 `.venv` 重新执行，预期输出全部通过。正式八章的 130 页已全部渲染并完成视觉检查，代码、截图、流程图和表格页另行放大复核；字体、边界、页脚、目录、文本提取和图表编号通过检查。记录与 PDF 哈希见 [PDF 教材验证记录](../evaluation/results/2026-10-07-PDF教材验证.json)。

59 幅图中有 22 处项目界面截图（13 组截图按教学主题复用）和 37 幅矢量流程或关系图。真实页面显示现有业务数据；答后反馈与错题辅导两组图使用真实 Vue 页面配合隔离 HTTP fixture，图注明确标注，未调用模型或写入真实学习记录。TCP 文本是教学样本，导入的 API 部署笔记是另一份实际资料。

历史测试和供应商验收只作为已有证据引用，本次制教材没有再次调用真实模型。独立 LangGraph 人工审核图属于教学实验，当前产品图仍由 `create_agent` 构建。

已有 [第0章：学习前检查与讲解规范](第0章_学习前检查与讲解规范.pdf) 是五项准备执行前的检查快照和格式样章，其中旧环境状态已更新。当前学习以以上准备说明及 [课程知识点与源码导读](../docs/技术方案/课程知识点与源码导读.md) 为准。

## 当前结论

默认 `apps/api/.venv` 已按开发锁对齐 LangChain 1.4.3、LangGraph 1.2.12，`pip check` 通过。项目编辑器配置和命令使用同一解释器，长期学习不再依赖 `tmp/v1-dev`。

默认环境中 149 项离线测试和 19 项真实 PostgreSQL 辅导验收通过，三个新增实验已运行。真实供应商与浏览器结果、版本、源码哈希和样本输出见 [本次验证记录](../evaluation/results/2026-10-07-学习准备验证.json)。未重算覆盖率。

从任意 PowerShell 位置运行首个 Agent 实验：

```powershell
Set-Location D:\Study\StudyAgent\apps\api
& '.\.venv\Scripts\python.exe' -m pytest `
  tests/test_tutor_agent.py::test_real_create_agent_tool_runtime_command_and_structured_output `
  -o 'addopts=' -q
```

可重复准备与验证默认学习环境：

```powershell
Set-Location D:\Study\StudyAgent
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\准备学习环境.ps1
& '.\apps\api\.venv\Scripts\python.exe' '.\examples\learning\agent_tool_loop.py'
```

已安装时可给准备脚本添加 `-SkipInstall`。实验运行方式与练习见 [三个学习实验](../examples/learning/README.md)。

## 教材内容与排版规范

需求与真实输入 → 中英文名词及职责 → 应用场景与取舍 → 实现流程 → 精确源码入口 → 标注类型的代码 → 结果解释与易错点 → 练习及参考思路。

按项目依赖组织章节，保留飞书资料的编号、短段落、代码行号、蓝色强调、对照表和矢量流程图。源码事实、当次执行、历史结果、待验证结论分别标注。

出题是固定 Chain；辅导 Agent 会调用资料检索和学习记录工具；确定性程序负责判分、掌握度与复习调度。资料/题库双索引不是 Dense/BM25 双路召回；Redis 学习快照不是 LangGraph Checkpoint。

五项学习前准备的执行过程、版本与历史验收边界见 [学习准备与章节计划](../docs/技术方案/学习准备与章节计划.md)。
