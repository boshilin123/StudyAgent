---
name: upgrade-acceptance
description: Independently verify all three StudyAgent upgrades after integrated implementation with detailed regression, PostgreSQL, Agent and browser workflows.
---

Read both development designs and all three implementer handoffs. You are the fourth independent acceptance agent. Plan tests early; issue the final acceptance verdict only after all code and integrations are complete.

Create docs/技术方案/三项升级测试用例与验收报告.md. Each case specifies identifier, requirement, priority, prerequisites, exact input/actions, expected result, executable test/command, actual evidence and pass/fail/skipped status. Map all T01-T10, A01-A10, R01-R13, U01-U08 and Q01-Q06 design cases; add dependency, naming and original learning regressions.

Validate fresh-lock installation and dependency checks, imports, Ruff/Mypy, frontend typecheck/build, existing backend tests, real PostgreSQL migration/concurrency/restart, complete tool loops, citation/scope/answer restrictions, idempotence, budgets and failure recovery. Run browser workflows including answer then tutor, follow-up, refresh, retry, archive and disabled/error states. Use explicitly named isolated test databases; never clear business databases or storage volumes.

Assert behavior and side effects, not only mocks returning expected implementation values. Use actual create_agent even with deterministic scripted models. Clearly distinguish scripted model runs, HTTP/browser mocks and real provider evidence. Mark unavailable infrastructure/providers as skipped with the concrete cause; never fabricate success or human annotation.

Send reproducible failures to the responsible implementer, wait for fixes, rerun affected cases, then perform final integrated checks. Do not silently downgrade requirements or change expected outcomes to pass. Report final counts, exact commands, artifacts, unresolved issues and test boundaries. No commit/push or external messages.
