# 外部 Embedding 配置

状态：P3 已实现  
适用范围：百炼/OpenAI-compatible、Hugging Face TEI、OVMS

## 1. 配置选择

StudyAgent 通过 `EMBEDDING_PROVIDER` 明确选择适配器：

- `local`：确定性开发向量，只用于验证链路，不用于检索效果评测。
- `openai_compatible`：调用 OpenAI-compatible `/embeddings`，适合百炼和提供兼容接口的 OVMS。
- `tei`：直接调用 Hugging Face Text Embeddings Inference 的 `/embed`。

原 EAP 的百炼配置使用 `https://dashscope.aliyuncs.com/compatible-mode/v1`、`text-embedding-v4` 和 1024 维向量；StudyAgent 延续这一接口约定，但把供应商字段统一为通用配置。

## 2. 百炼配置

在根目录 `.env` 中配置：

```dotenv
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_API_KEY=你的百炼_API_Key
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSIONS=1024
EMBEDDING_TIMEOUT_SECONDS=30
```

然后重建 API 和 Worker：

```powershell
docker compose up -d --build api worker
```

## 3. TEI 配置

若沿用 EAP 的 TEI 服务并暴露在宿主机 `13020`：

```dotenv
EMBEDDING_PROVIDER=tei
EMBEDDING_BASE_URL=http://host.docker.internal:13020
EMBEDDING_API_KEY=
EMBEDDING_MODEL=BAAI/bge-base-zh-v1.5
EMBEDDING_DIMENSIONS=768
EMBEDDING_TIMEOUT_SECONDS=30
```

TEI 不要求 OpenAI API Key。StudyAgent 会向 `{EMBEDDING_BASE_URL}/embed` 发送批量 `inputs`。

如果 TEI 本身也在当前 Compose 网络中，应把地址改为容器服务名，例如 `http://embedding:80`。

## 4. OVMS 配置

原 EAP 使用 `BAAI/bge-large-zh-v1.5` 和 `/v3` 端点。若该 OVMS 部署暴露 OpenAI-compatible Embedding 接口，可配置为：

```dotenv
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_BASE_URL=http://host.docker.internal:13020/v3
EMBEDDING_API_KEY=
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
EMBEDDING_DIMENSIONS=1024
EMBEDDING_TIMEOUT_SECONDS=30
```

若实际 OVMS 镜像只暴露原生推理协议而没有 `/v3/embeddings`，需要继续使用 EAP 的 embedding-usvc 作为协议转换层，并将 `EMBEDDING_BASE_URL` 指向该服务的 OpenAI-compatible 地址。

## 5. 切换模型时的 Milvus 处理

Milvus Collection 的向量维度在创建后不可直接修改。当前本地开发索引是 384 维；切换到 768 或 1024 维模型时，必须使用新的 Collection 名称：

```dotenv
MILVUS_DOCUMENT_COLLECTION=study_documents_v2_1024
MILVUS_QUESTION_COLLECTION=study_questions_v2_1024
```

随后通过 `POST /api/materials/{id}/reprocess` 重新处理已有资料，无需删除原文件。重新处理会保留内容未变化片段的稳定 ID 和题目来源关系，只清理失效片段。代码会在写入前检查实际维度，发现不一致时直接失败，不会把错误维度的数据写入旧 Collection。

百炼 `text-embedding-v4` 的当前兼容约束已经在适配器中处理：关闭 LangChain 的 token ID 输入转换，并将单批文本数限制为 10。小文档连通测试不能替代长文档批量验证。

## 6. 验证顺序

1. 先直接调用 Embedding 服务，确认能返回预期维度的向量。
2. 重启 API 和 Worker，检查 Worker 日志没有鉴权或模型名称错误。
3. 上传一份小型 Markdown，等待处理任务达到 `completed`。
4. 调用知识库检索接口，确认能够召回片段。
5. 检查资料片段的 `embedding_model` 已变为外部模型名称。

不要把真实 API Key 写入 `.env.example`、文档、日志或 Git 仓库。

## 7. 百炼真实服务验证记录（2026-09-28）

本次已按脱敏方式核对项目 `.env`：

- Provider：`openai_compatible`
- Model：`text-embedding-v4`
- Dimensions：`1024`
- 文档 Collection：`study_documents_v2_1024`
- 题目 Collection：`study_questions_v2_1024`
- API Key：已设置且不是示例占位符

首次直接调用 Embedding 接口时，百炼返回：

```text
HTTP 403
AccessDenied.Unpurchased
Access to model denied. Please make sure you are eligible for using the model.
```

这说明请求已经到达百炼，当时的阻塞点不是 StudyAgent 的配置解析或网络连接，而是账号、工作空间或 API Key 尚未获得 Embedding 模型调用权限。

通过相同 API Key 查询模型列表时可以看到 `qwen3.7-text-embedding` 和 `qwen3.7-text-embedding-flash`，但实际调用备用模型仍返回相同的 `403 AccessDenied.Unpurchased`。因此“模型可见”不代表“已开通调用权限”，也不是单纯的 `text-embedding-v4` 模型名错误。

权限更新后的复测已经通过：

1. 原始 OpenAI-compatible 请求返回 `HTTP 200`，模型为 `text-embedding-v4`，向量维度为 `1024`，且为有效非零向量。
2. 发现 LangChain `OpenAIEmbeddings` 默认的长文本安全模式会把输入转换成 token ID 数组，而当前百炼工作空间端点仅接受字符串数组，返回 `400 input must be an array of strings`。
3. 适配器已设置 `check_embedding_ctx_length=False`，使 LangChain 直接发送字符串；修复后真实调用成功返回 1024 维向量。
4. API 和 Worker 已重建并正常启动，API 健康检查通过，Worker 已连接 Redis 且任务注册正常。
5. 上传测试 Markdown 后，异步处理任务达到 `completed / 100%`，无错误码。
6. Milvus 已创建 `study_documents_v2_1024`，向量字段维度为 `1024`。
7. 使用测试资料唯一口令进行语义检索，成功召回目标片段，相似度分数约为 `0.795`。

至此，百炼 Embedding、LangChain 适配、Celery 资料处理、Milvus 1024 维入库和知识库检索全链路验证完成。
