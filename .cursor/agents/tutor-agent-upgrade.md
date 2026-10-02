---
name: tutor-agent-upgrade
description: Implement StudyAgent read-only learning tutor with LangChain create_agent, bounded tools, verified citations and durable conversations.
---

Read docs/技术方案/学习辅导Agent详细设计.md and repository rules. Implement the authorized first version with four read-only tools: material retrieval, answered-question context, progress and recent mistakes.

Use create_agent, actual tool calls and ToolMessage feedback. Keep immutable server-bound scope in runtime Context; use serializable State and per-turn evidence/call budgets. Models must not change grades, mastery, review tasks, questions or materials.

Validate ownership and actual answered records in application queries. Restrict mock-exam tutoring at execution and evidence boundaries. Retrieve only current database-valid sources and verify final citation identifiers/hashes against evidence actually returned this turn.

Persist business conversations, turns and messages plus PostgreSQL checkpoints. Stable client_message_id and request hash must prevent duplicate model execution; serialize each conversation while avoiding long answer transactions. Failed intermediate checkpoints must not contaminate accepted history. Handle timeouts, restart, archives and unsupported models explicitly.

Implement APIs and integrate frontend/lifecycle through agreed interfaces. Keep original study submission behavior intact. Do not substitute in-memory persistence for production recovery or ordinary chat for an Agent.

Add meaningful tool, loop, scope, budget and persistence tests. Publish API shapes, settings and lifecycle hooks early. Coordinate existing ORM/config/router ownership. Never expose credentials, clear business data, commit or push without authorization.
