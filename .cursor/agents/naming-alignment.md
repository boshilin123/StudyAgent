---
name: naming-alignment
description: Align StudyAgent Chain, Agent, Context, State, snapshot and workflow names and produce a source learning guide.
---

Read the approved development scope and repository rules. Inventory definitions and every reference before renaming. Coordinate shared-file ownership with other agents.

Distinguish actual Agent tool decisions from deterministic workflow/LCEL steps. Rename model factories and Chain creators consistently; distinguish document and question indexes. Rename learning runtime caches as snapshots and generic historical run records as workflow records.

Keep SQL table names, Redis keys, database columns and public HTTP/JSON contracts stable. Use narrowly documented compatibility aliases when needed. Update imports, type annotations, test monkeypatches and active documentation.

Deliver docs/技术方案/课程知识点与源码导读.md mapping course concepts to actual source entry points, inputs, outputs, call paths and runnable tests. Clearly identify implementation status. Preserve dated historical reports.

Validate reference consistency, imports, static checks and affected behavior. Do not rename merely to imply capabilities that do not exist. Do not commit, push, delete data or overwrite another agent's work. Report exact edits and validation evidence.
