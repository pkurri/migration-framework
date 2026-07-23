from migration_framework.cli import _expand_shorthand, build_parser, main


def test_shorthand_expansion_converts_source_and_target():
    argv = [
        "--source", "sqlalchemy:orders",
        "--target", "bigquery:orders_fact",
        "--source-connection", "{}",
        "--target-connection", "{}",
        "--job-name", "demo",
        "--out", "demo.yaml",
    ]
    expanded = _expand_shorthand(argv)
    assert expanded[0] == "discover"
    assert expanded[expanded.index("--source-connector") + 1] == "sqlalchemy"
    assert expanded[expanded.index("--source-table") + 1] == "orders"
    assert expanded[expanded.index("--target-connector") + 1] == "bigquery"
    assert expanded[expanded.index("--target-table") + 1] == "orders_fact"


def test_shorthand_requires_colon_separator():
    import pytest
    with pytest.raises(ValueError):
        _expand_shorthand(["--source", "badvalue"])


def test_full_discover_command_is_left_untouched():
    argv = ["discover", "--source-connector", "sqlalchemy"]
    assert _expand_shorthand(argv) == argv


def test_run_command_is_left_untouched():
    argv = ["run", "--config", "demo.yaml"]
    assert _expand_shorthand(argv) == argv


def test_parser_accepts_shorthand_args_after_expansion():
    parser = build_parser()
    argv = _expand_shorthand(
        [
            "--source", "sqlalchemy:orders",
            "--target", "bigquery:orders_fact",
            "--source-connection", "{}",
            "--target-connection", "{}",
            "--job-name", "demo",
            "--out", "demo.yaml",
        ]
    )
    args = parser.parse_args(argv)
    assert args.command == "discover"
    assert args.source_connector == "sqlalchemy"
    assert args.source_table == "orders"
    assert args.target_connector == "bigquery"
    assert args.target_table == "orders_fact"


def test_shorthand_leaves_skill_command_untouched():
    argv = ["skill", "--list"]
    assert _expand_shorthand(argv) == argv


def test_shorthand_leaves_workflow_command_untouched():
    argv = ["workflow", "--list"]
    assert _expand_shorthand(argv) == argv


def test_parser_has_skill_and_workflow_subcommands():
    parser = build_parser()
    args = parser.parse_args(["skill", "--list"])
    assert args.command == "skill"
    assert args.list is True
    args = parser.parse_args(["workflow", "map-verify-codegen", "--inputs", '{}'])
    assert args.command == "workflow"
    assert args.name == "map-verify-codegen"
