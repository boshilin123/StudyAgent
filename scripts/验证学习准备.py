"""Reproducible learning baseline; real services/provider are explicit opt-ins.

No credentials are written to logs or reports. PostgreSQL acceptance uses only
the existing guarded study_agent_test_upgrade preparation script.
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"
LOGS = ROOT / "tmp" / "learning-validation"


def execute(
    name: str, args: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None
) -> dict[str, object]:
    started = time.monotonic()
    log = LOGS / f"{name}.txt"
    xml_path = LOGS / f"{name}.xml"
    if xml_path.exists():
        xml_path.unlink()
    print(f"Running {name} ...", flush=True)
    with log.open("w", encoding="utf-8") as stream:
        completed = subprocess.run(
            args,
            cwd=cwd,
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
            timeout=600,
            check=False,
        )
    result: dict[str, object] = {
        "exit_code": completed.returncode,
        "seconds": round(time.monotonic() - started, 3),
        "log": log.relative_to(ROOT).as_posix(),
    }
    if xml_path.exists():
        suites = ET.parse(xml_path).getroot()
        result["counts"] = {
            key: sum(int(s.get(key, "0")) for s in suites.iter("testsuite"))
            for key in ["tests", "failures", "errors", "skipped"]
        }
    print(f"{name}: exit {completed.returncode}", flush=True)
    return result


def check_lock() -> dict[str, str]:
    versions = {}
    for line in (API / "requirements-dev.lock").read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        actual = importlib.metadata.version(requirement.name)
        assert actual in requirement.specifier, f"Locked version mismatch: {requirement.name}"
        versions[requirement.name] = actual
    return versions


def main() -> None:
    global LOGS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-services", action="store_true")
    parser.add_argument("--with-live", action="store_true")
    args = parser.parse_args()
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S-%f")
    LOGS = LOGS / stamp
    LOGS.mkdir(parents=True, exist_ok=True)
    output = ROOT / "evaluation" / "results" / f"{stamp}-学习准备验证.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "checked_at": datetime.now().astimezone().isoformat(),
        "interpreter": (
            Path(sys.executable).relative_to(ROOT).as_posix()
            if Path(sys.executable).is_relative_to(ROOT)
            else Path(sys.executable).name
        ),
        "python": sys.version.split()[0],
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "working_tree_note": "Includes pre-existing local edits and this learning preparation.",
        "versions": check_lock(),
        "source_sha256": {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in [
                "apps/api/requirements-dev.lock",
                "apps/api/study_agent/agents/tutor/agent.py",
                "apps/api/study_agent/agents/tutor/prompts.py",
                "apps/api/study_agent/agents/tutor/middleware.py",
                "apps/api/study_agent/application/retrieval.py",
                "apps/api/study_agent/question_generation/tasks.py",
                "examples/learning/langgraph_review.py",
                "examples/learning/agent_tool_loop.py",
                "examples/learning/rag_context.py",
                "apps/api/tests/test_tutor_live_acceptance.py",
            ]
        },
    }
    checks = {}
    report["checks"] = checks
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        checks["pip_check"] = execute("pip-check", [sys.executable, "-m", "pip", "check"], env=env)
        experiments = {}
        report["experiments"] = experiments
        for name in ["rag_context", "agent_tool_loop", "langgraph_review"]:
            checks[name] = execute(
                name, [sys.executable, str(ROOT / "examples/learning" / f"{name}.py")], env=env
            )
            if checks[name]["exit_code"] == 0:
                experiments[name] = json.loads((LOGS / f"{name}.txt").read_text(encoding="utf-8"))
        checks["offline"] = execute(
            "offline",
            [
                sys.executable,
                "-m",
                "pytest",
                "-m",
                "not integration",
                "--junitxml",
                str(LOGS / "offline.xml"),
            ],
            cwd=API,
            env=env,
        )
        checks["ruff"] = execute(
            "ruff",
            [sys.executable, "-m", "ruff", "check", "study_agent", "tests"],
            cwd=API,
            env=env,
        )
        if args.with_services or args.with_live:
            checks["postgres"] = execute(
                "postgres",
                [
                    sys.executable,
                    str(ROOT / "scripts/prepare_upgrade_test_database.py"),
                    "tests/test_tutor_postgres_acceptance.py",
                    "--junitxml",
                    str(LOGS / "postgres.xml"),
                ],
                env=env,
            )
        if args.with_live:
            checks["live"] = execute(
                "live",
                [
                    sys.executable,
                    str(ROOT / "scripts/prepare_upgrade_test_database.py"),
                    "tests/test_tutor_live_acceptance.py",
                    "--junitxml",
                    str(LOGS / "live.xml"),
                ],
                env={**env, "RUN_LIVE_TUTOR": "1"},
            )
            evidence = ROOT / "tmp/upgrade-acceptance/live-provider.json"
            counts = checks["live"].get("counts", {})
            if (
                checks["live"]["exit_code"] == 0
                and counts.get("tests")
                and not counts.get("skipped")
                and evidence.exists()
            ):
                report["live_evidence"] = json.loads(evidence.read_text(encoding="utf-8"))
        report["passed"] = all(check["exit_code"] == 0 for check in checks.values())
    finally:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report: {output}", flush=True)
    if not report.get("passed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
