#!/usr/bin/env python3
"""Acceptance run 骨架工具（acceptance-testing 的助手，不是权威）。

用法：
    python skills/acceptance-testing/scripts/acceptance_run.py init <run-id> --goal "<验收目标>" [--simulated]
    python skills/acceptance-testing/scripts/acceptance_run.py check <run-id>
    python skills/acceptance-testing/scripts/acceptance_run.py status <run-id>
    python skills/acceptance-testing/scripts/acceptance_run.py check-models [--catalog <opencodex-catalog.json>]

- init：创建 runs/acceptance/<run-id>/ 骨架与 manifest.md。
- check：校验一个 run 的结构完整性（必填文件、EXP/TASK 索引、manifest 状态）。
- status：打印 manifest 当前状态。
- check-models：校验 config/agent-models.toml（四角色 + fallback 齐全、model 与
  reasoning_effort 非空、模型存在于模型目录、推理档位受模型支持、与
  agents/codex-roles/*.md frontmatter 一致）。模型目录默认
  ~/.codex/opencodex-catalog.json，不存在时跳过模型存在性校验并告警。

本脚本只做骨架与完整性检查；状态机推进由编排者（Main Agent）按
skills/acceptance-testing/SKILL.md 执行。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

STATES = [
    "PLANNING",
    "EXPERIMENTING",
    "ANALYZING",
    "NEED_MORE_EVIDENCE",
    "ROOT_CAUSE_CONFIRMED",
    "SOLUTION_PLANNING",
    "EXECUTING",
    "REVALIDATING",
    "VERIFIED_PASS",
    "VERIFIED_FAIL",
    "NOT_VERIFIED",
    "EVIDENCE_INSUFFICIENT",
    "BLOCKED",
    "OUT_OF_SCOPE",
]

ROLE_KEYS = ["experimenter", "analyst", "solution_planner", "executor"]
ROLE_FILES = {
    "experimenter": "experimenter.md",
    "analyst": "analyst.md",
    "solution_planner": "solution-planner.md",
    "executor": "executor.md",
}

MANIFEST_TEMPLATE = """# Acceptance Run Manifest

- Run ID: {run_id}
- Created: {created}
- Acceptance Goal: {goal}
- Simulated: {simulated}   # true 表示桌面演练，所有报告不是真实运行证据
- State: PLANNING
- Loop Budget: 补充实验 <=3/次分析；task 修复 <=3 轮；整循环 <=3 次
- Experiments:
- Tasks:
- Final State: (未完成)
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_repo_root() -> Path:
    # 在仓库根（存在 skills/acceptance-testing 或 .git 的祖先）定位仓库根
    cur = Path.cwd().resolve()
    for anc in [cur, *cur.parents]:
        if (anc / "skills" / "acceptance-testing").is_dir() or (anc / ".git").exists():
            return anc
    return cur


def find_run_root() -> Path:
    return find_repo_root() / "runs" / "acceptance"


def cmd_init(args: argparse.Namespace) -> int:
    root = find_run_root()
    run_dir = root / args.run_id
    if run_dir.exists():
        print(f"ERROR: run 已存在: {run_dir}")
        return 1
    (run_dir / "experiments").mkdir(parents=True)
    (run_dir / "investigation").mkdir()
    (run_dir / "solution" / "tasks").mkdir(parents=True)
    (run_dir / "execution").mkdir()
    manifest = run_dir / "manifest.md"
    manifest.write_text(
        MANIFEST_TEMPLATE.format(
            run_id=args.run_id,
            created=utc_now(),
            goal=args.goal,
            simulated="true" if args.simulated else "false",
        ),
        encoding="utf-8",
    )
    print(f"created: {run_dir}")
    print(f"manifest: {manifest}")
    print(f"run_id: {args.run_id}")
    return 0


def parse_manifest(run_dir: Path) -> dict[str, str]:
    text = (run_dir / "manifest.md").read_text(encoding="utf-8")
    fields = {}
    for line in text.splitlines():
        m = re.match(r"^- ([A-Za-z /]+):\s*(.*)$", line.strip())
        if m:
            fields[m.group(1).strip()] = m.group(2).strip()
    return fields


def cmd_check(args: argparse.Namespace) -> int:
    run_dir = find_run_root() / args.run_id
    if not run_dir.is_dir():
        print(f"ERROR: run 不存在: {run_dir}")
        return 1
    problems: list[str] = []
    manifest = run_dir / "manifest.md"
    if not manifest.exists():
        problems.append("缺少 manifest.md")
        fields = {}
    else:
        fields = parse_manifest(run_dir)
        state = fields.get("State", "")
        if state not in STATES:
            problems.append(f"manifest State 不是合法终态/状态: {state!r}")

    # 实验目录：EXP-nnn 必须成对出现 request.md + raw-report.md
    exp_dirs = sorted((run_dir / "experiments").glob("EXP-*"))
    for d in exp_dirs:
        for required in ("request.md", "raw-report.md"):
            if not (d / required).exists():
                problems.append(f"{d.relative_to(run_dir)} 缺少 {required}")

    # 状态 >= ROOT_CAUSE_CONFIRMED 时应存在 investigation 报告
    state = fields.get("State", "")
    order = {s: i for i, s in enumerate(STATES)}
    if state in order and order[state] >= order["ROOT_CAUSE_CONFIRMED"]:
        if not (run_dir / "investigation" / "report.md").exists():
            problems.append("State >= ROOT_CAUSE_CONFIRMED 但缺少 investigation/report.md")

    # 状态 >= SOLUTION_PLANNING 时应存在方案与 tasks
    if state in order and order[state] >= order["SOLUTION_PLANNING"]:
        if not (run_dir / "solution" / "solution.md").exists():
            problems.append("State >= SOLUTION_PLANNING 但缺少 solution/solution.md")
        for t in sorted((run_dir / "solution" / "tasks").glob("TASK-*.md")):
            if not (run_dir / "execution" / f"{t.stem}-report.md").exists():
                problems.append(f"task 缺少对应 execution report: {t.stem}")

    # 终局必须有 final-report.md
    if state in ("VERIFIED_PASS", "VERIFIED_FAIL", "NOT_VERIFIED", "EVIDENCE_INSUFFICIENT", "BLOCKED", "OUT_OF_SCOPE"):
        if not (run_dir / "final-report.md").exists():
            problems.append("已达终态但缺少 final-report.md")

    if problems:
        print(f"FAIL ({len(problems)} problems):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"OK: {run_dir}")
    print(f"state: {fields.get('State', '(无 manifest)')}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    run_dir = find_run_root() / args.run_id
    if not run_dir.is_dir():
        print(f"ERROR: run 不存在: {run_dir}")
        return 1
    fields = parse_manifest(run_dir)
    print(f"run: {args.run_id}")
    for key in ("State", "Simulated", "Acceptance Goal", "Final State"):
        print(f"  {key}: {fields.get(key, '(缺失)')}")
    exps = sorted((run_dir / "experiments").glob("EXP-*"))
    tasks = sorted((run_dir / "solution" / "tasks").glob("TASK-*.md"))
    print(f"  experiments: {', '.join(d.name for d in exps) or '(无)'}")
    print(f"  tasks: {', '.join(t.stem for t in tasks) or '(无)'}")
    return 0


def load_catalog(catalog_path: Path) -> dict | None:
    """返回 {slug: {levels: [...]}}；目录不可达返回 None。"""
    if not catalog_path.exists():
        return None
    with catalog_path.open(encoding="utf-8") as f:
        data = json.load(f)
    out = {}
    for m in data.get("models", []):
        levels = [lvl["effort"] for lvl in m.get("supported_reasoning_levels", [])]
        out[m["slug"]] = {"levels": levels}
    return out


def parse_frontmatter_model(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"(?ms)^---\n(.*?)\n---", text)
    if not m:
        return None
    mm = re.search(r"(?m)^model:\s*(\S+)", m.group(1))
    return mm.group(1) if mm else None


def cmd_check_models(args: argparse.Namespace) -> int:
    repo = find_repo_root()
    config = repo / "skills" / "acceptance-testing" / "config" / "agent-models.toml"
    if not config.exists():
        print(f"ERROR: 模型分配配置不存在: {config}")
        return 1

    with config.open("rb") as f:
        alloc = tomllib.load(f)

    problems: list[str] = []

    # 1) 角色与 fallback 齐全，字段非空
    for key in ROLE_KEYS + ["fallback"]:
        sec = alloc.get(key)
        if not isinstance(sec, dict):
            problems.append(f"缺少 [{key}] 表")
            continue
        for field in ("model", "reasoning_effort"):
            if not isinstance(sec.get(field), str) or not sec[field].strip():
                problems.append(f"[{key}] 缺少或为空: {field}")

    # 2) 模型存在性与推理档位（目录可达时）
    catalog_path = args.catalog.expanduser()
    catalog = load_catalog(catalog_path)
    if catalog is None:
        print(f"WARN: 模型目录不可达（{catalog_path}），跳过模型存在性与档位校验")
    else:
        for key in ROLE_KEYS + ["fallback"]:
            sec = alloc.get(key)
            if not isinstance(sec, dict):
                continue
            model = sec.get("model")
            if model not in catalog:
                problems.append(f"[{key}] model {model!r} 不在模型目录中")
                continue
            effort = sec.get("reasoning_effort")
            if effort not in catalog[model]["levels"]:
                levels = ", ".join(catalog[model]["levels"])
                problems.append(f"[{key}] reasoning_effort {effort!r} 不受 {model} 支持（支持: {levels}）")

    # 3) codex-roles frontmatter 一致性
    roles_dir = repo / "skills" / "acceptance-testing" / "agents" / "codex-roles"
    for key in ROLE_KEYS:
        role_file = roles_dir / ROLE_FILES[key]
        if not role_file.exists():
            problems.append(f"缺少角色文件: {ROLE_FILES[key]}")
            continue
        fm_model = parse_frontmatter_model(role_file)
        cfg_model = alloc.get(key, {}).get("model")
        if fm_model != cfg_model:
            problems.append(f"{ROLE_FILES[key]} frontmatter model={fm_model!r} 与 config [{key}] model={cfg_model!r} 不一致")

    if problems:
        print(f"FAIL ({len(problems)} problems):")
        for p in problems:
            print(f"  - {p}")
        return 1

    print(f"OK: {config.relative_to(repo)}")
    for key in ROLE_KEYS + ["fallback"]:
        sec = alloc[key]
        print(f"  {key}: model={sec['model']} reasoning_effort={sec['reasoning_effort']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="acceptance-testing run 骨架助手")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="创建 run 骨架")
    p_init.add_argument("run_id")
    p_init.add_argument("--goal", required=True, help="验收目标")
    p_init.add_argument("--simulated", action="store_true", help="标记为桌面演练（非真实运行证据）")
    p_init.set_defaults(fn=cmd_init)

    p_check = sub.add_parser("check", help="校验 run 结构完整性")
    p_check.add_argument("run_id")
    p_check.set_defaults(fn=cmd_check)

    p_status = sub.add_parser("status", help="打印 run 状态")
    p_status.add_argument("run_id")
    p_status.set_defaults(fn=cmd_status)

    p_models = sub.add_parser("check-models", help="校验模型分配配置")
    p_models.add_argument(
        "--catalog",
        type=Path,
        default=Path("~/.codex/opencodex-catalog.json"),
        help="模型目录路径（默认 ~/.codex/opencodex-catalog.json）",
    )
    p_models.set_defaults(fn=cmd_check_models)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
