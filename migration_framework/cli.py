"""The one entrypoint anything - Databricks Jobs, Airflow, cron, dbt, or a
person - can call to run this framework.

    migrate discover --source-connector sqlalchemy --source-connection '{"connection_url": "..."}' \\
                      --source-table orders --target-connector sqlalchemy \\
                      --target-connection '{"connection_url": "..."}' --target-table orders_fact \\
                      --job-name my_job --out configs/my_job.yaml

    migrate run --config configs/my_job.yaml [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any

import yaml

from .agents import DiscoveryWorkflow
from .audit_defaults import guess_audit_generator
from .codegen import generate_for
from .config import AuditColumn, MigrationConfig, SourceSpec, TargetSpec, ValidationSpec
from .engine import ReconciliationError, ValidationError, run_migration
from .hitl import UnresolvedColumnsError, resolve_interactive, resolve_with_answers
from .skills import SkillContext, get_skill, list_skills


def _print_proposal_summary(proposal, print_fn=print) -> None:
    print_fn(f"{len(proposal.auto_mapped)}/{len(proposal.columns)} columns auto-mapped.")
    for col in proposal.flagged:
        print_fn(f"  flagged: {col.target_column} ({col.reason})")


def cmd_discover(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    source_connection: dict[str, Any] = json.loads(args.source_connection)
    target_connection: dict[str, Any] = json.loads(args.target_connection)

    audit_names = {n.strip() for n in (args.audit_columns or "").split(",") if n.strip()}
    audit_columns = [AuditColumn(name=n, generator=guess_audit_generator(n)) for n in sorted(audit_names)]

    workflow = DiscoveryWorkflow()
    proposal = workflow.run(
        args.source_connector,
        source_connection,
        args.source_table,
        args.target_connector,
        target_connection,
        args.target_table,
        sample_size=args.sample_size,
    )
    # Re-attach audit columns so the proposal object reflects the real target.
    proposal.columns = [c for c in proposal.columns if c.target_column not in audit_names]
    _print_proposal_summary(proposal)

    if proposal.flagged and args.answers:
        with open(args.answers) as f:
            answers = yaml.safe_load(f) or {}
        columns = resolve_with_answers(proposal, answers)
    elif proposal.flagged and args.auto_only:
        print(f"{len(proposal.flagged)} column(s) need a decision and --auto-only was set; not writing a config.")
        for col in proposal.flagged:
            print(f"  {col.target_column}: {col.reason}")
        return 1
    elif proposal.flagged:
        columns = resolve_interactive(proposal)
    else:
        columns = resolve_with_answers(proposal, {})

    config = MigrationConfig(
        job_name=args.job_name,
        source=SourceSpec(connector=args.source_connector, connection=source_connection, table=args.source_table),
        target=TargetSpec(connector=args.target_connector, connection=target_connection, table=args.target_table),
        columns=columns,
        audit_columns=audit_columns,
        validation=ValidationSpec(expected_column_count=len(columns) + len(audit_columns)),
    )

    # Generate the runnable load script for this specific source/target pair.
    generated = generate_for(config)
    generated_dir = os.path.dirname(args.out)
    if generated_dir:
        os.makedirs(generated_dir, exist_ok=True)
    generated_path = os.path.join(os.path.dirname(args.out) or ".", os.path.basename(generated.path))
    with open(generated_path, "w") as f:
        f.write(generated.body)

    config.save(args.out)
    print(f"\nwrote {args.out}")
    print(f"wrote generated load script: {generated_path}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config = MigrationConfig.load(args.config)
    try:
        result = run_migration(config, dry_run=args.dry_run)
    except (ValidationError, ReconciliationError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    if result.dry_run:
        print(f"dry run ok: {result.rows_read} source rows would produce {result.rows_read} target rows")
    else:
        print(
            f"wrote {result.rows_written} rows to {config.target.table} "
            f"({result.target_row_count_before} -> {result.target_row_count_after})"
        )
        if result.reconciled is not None:
            print(f"reconciled: {result.reconciled}")
    return 0


def _print_skill_result(result) -> None:
    if not result.success:
        print(f"FAILED: {result.error}", file=sys.stderr)
        return
    if "generated" in result.outputs:
        generated = result.outputs["generated"]
        print(f"generated {generated['language']} load script")
    print(json.dumps(result.outputs, default=str, indent=2))


def _cmd_list_skills() -> int:
    print("Available skills:")
    for name, desc in list_skills().items():
        print(f"  {name:24s} {desc}")
    return 0


def cmd_skill(args: argparse.Namespace) -> int:
    if args.list:
        return _cmd_list_skills()

    skill_cls = get_skill(args.name)
    if skill_cls is None:
        print(f"Unknown skill {args.name!r}. Run 'migrate skill --list' to see options.", file=sys.stderr)
        return 1

    inputs: dict[str, Any] = {}
    if args.inputs:
        inputs = json.loads(args.inputs)
    elif args.inputs_file:
        with open(args.inputs_file) as f:
            inputs = json.load(f)

    result = skill_cls().run(SkillContext(inputs=inputs))
    _print_skill_result(result)
    return 0 if result.success else 1


def cmd_workflow(args: argparse.Namespace) -> int:
    if args.list:
        return _cmd_list_skills()

    workflow_cls = get_skill(args.name)
    if workflow_cls is None:
        print(f"Unknown workflow {args.name!r}. Run 'migrate workflow --list' to see options.", file=sys.stderr)
        return 1

    inputs: dict[str, Any] = {}
    if args.inputs:
        inputs = json.loads(args.inputs)
    elif args.inputs_file:
        with open(args.inputs_file) as f:
            inputs = json.load(f)

    result = workflow_cls().run(SkillContext(inputs=inputs))
    _print_skill_result(result)
    return 0 if result.success else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="migrate", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser("discover", help="read a source/target pair, propose a mapping, ask about the rest")
    discover.add_argument("--source-connector", default="sqlalchemy")
    discover.add_argument("--source-connection", required=True, help="JSON kwargs for the source connector")
    discover.add_argument("--source-table", required=True)
    discover.add_argument("--target-connector", default="sqlalchemy")
    discover.add_argument("--target-connection", required=True, help="JSON kwargs for the target connector")
    discover.add_argument("--target-table", required=True)
    discover.add_argument("--job-name", required=True)
    discover.add_argument("--out", required=True, help="where to write the resulting config YAML")
    discover.add_argument("--sample-size", type=int, default=50)
    discover.add_argument("--answers", help="YAML/JSON file answering flagged columns non-interactively")
    discover.add_argument("--auto-only", action="store_true", help="fail instead of prompting if anything is flagged")
    discover.add_argument(
        "--audit-columns",
        default="",
        help="comma-separated target columns that are pipeline bookkeeping, not a source copy (e.g. batch_id,etl_load_ts)",
    )
    discover.set_defaults(func=cmd_discover)

    run = subparsers.add_parser("run", help="run a migration from a config file")
    run.add_argument("--config", required=True)
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=cmd_run)

    skill = subparsers.add_parser("skill", help="run a standalone reusable skill")
    skill.add_argument("name", nargs="?", help="name of the skill to run")
    skill.add_argument("--list", action="store_true", help="list available skills")
    skill.add_argument("--inputs", help="JSON inputs for the skill")
    skill.add_argument("--inputs-file", help="path to a JSON file containing skill inputs")
    skill.set_defaults(func=cmd_skill)

    workflow = subparsers.add_parser("workflow", help="run a reusable workflow")
    workflow.add_argument("name", nargs="?", help="name of the workflow to run")
    workflow.add_argument("--list", action="store_true", help="list available skills/workflows")
    workflow.add_argument("--inputs", help="JSON inputs for the workflow")
    workflow.add_argument("--inputs-file", help="path to a JSON file containing workflow inputs")
    workflow.set_defaults(func=cmd_workflow)

    return parser


def _parse_shorthand(value: str) -> tuple[str, str]:
    if ":" not in value:
        raise ValueError(f"shorthand must be connector:table, got {value!r}")
    connector, table = value.split(":", 1)
    if not connector or not table:
        raise ValueError(f"shorthand must be connector:table, got {value!r}")
    return connector, table


def _expand_shorthand(argv: list[str]) -> list[str]:
    """Convert `migrate --source X:Y --target A:B` into full `discover` args."""
    if not argv or argv[0] in ("discover", "run", "skill", "workflow"):
        return argv
    expanded = ["discover"]
    it = iter(argv)
    for arg in it:
        if arg in ("--source", "-s"):
            connector, table = _parse_shorthand(next(it))
            expanded.extend(["--source-connector", connector, "--source-table", table])
        elif arg in ("--target", "-t"):
            connector, table = _parse_shorthand(next(it))
            expanded.extend(["--target-connector", connector, "--target-table", table])
        else:
            expanded.append(arg)
    return expanded


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    argv = _expand_shorthand(argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except UnresolvedColumnsError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
