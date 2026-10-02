---
name: langchain-v1-upgrade
description: Implement and validate StudyAgent LangChain v1 dependency migration and shared model initialization.
---

Read docs/技术方案/LangChain-v1与学习辅导Agent开发方案.md and applicable repository rules. Execute authorized migration, rather than only proposing it.

Own pyproject.toml, both generated requirements locks, llm modules, model configuration and existing Chain/model initialization call sites. Coordinate shared files before editing.

Resolve compatible LangChain v1, langchain-core, provider, LangGraph and PostgreSQL checkpointer dependencies using the package resolver. Do not manually substitute lock versions. Keep Python 3.12 compatibility and provider-specific structured-output options.

Provide get_chat_model(settings, *, purpose), including explicit tutoring configuration inheritance. Avoid carrying per-conversation state in model caches. Check real tool-call compatibility separately from offline unit tests.

Validate installation, dependency consistency, imports and original generation/explanation behavior. Report precise versions, commands and outcomes. Never equate old test reports with current validation.

Do not change public API fields, delete data, commit or push unless explicitly instructed. Do not expose secrets or raw .env content. Report scope, changed files, integration interface, evidence and remaining failures to the coordinating agent.
