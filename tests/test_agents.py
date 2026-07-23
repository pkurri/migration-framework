from migration_framework.agents import DiscoveryWorkflow, LocalMappingAgent, LocalVerifierAgent
from migration_framework.agents.base import AgentContext
from migration_framework.connectors.base import ColumnInfo, TableSchema


def _schema(name, columns_and_samples):
    columns = [ColumnInfo(name=n, canonical_type=t, native_type=t) for n, t, _ in columns_and_samples]
    sample_rows = []
    max_len = max((len(s) for _, _, s in columns_and_samples), default=0)
    for i in range(max_len):
        row = {}
        for n, _t, samples in columns_and_samples:
            row[n] = samples[i] if i < len(samples) else None
        sample_rows.append(row)
    return TableSchema(name=name, columns=columns, sample_rows=sample_rows)


def test_mapping_agent_flags_generic_numbered_columns():
    source = _schema(
        "src",
        [
            ("PO_HDR_COL_01", "string", ["2021-05-01", "2021-06-01"]),
            ("PO_HDR_COL_02", "string", ["2021-07-01", "2021-08-01"]),
        ],
    )
    target = _schema(
        "tgt",
        [
            ("SHIP_START_DT", "date", []),
            ("SHIP_CANCEL_DT", "date", []),
        ],
    )

    agent = LocalMappingAgent()
    context = AgentContext(
        source_connector="test",
        source_connection={},
        source_table="src",
        target_connector="test",
        target_connection={},
        target_table="tgt",
        source_schema=source,
        target_schema=target,
    )
    result = agent.run(context)
    proposal = result.data

    assert all(c.status == "flagged" for c in proposal.columns)


def test_verifier_downgrades_generic_source_names():
    source = _schema(
        "src",
        [
            ("COL_01", "string", ["x"]),
            ("COL_02", "string", ["y"]),
        ],
    )
    target = _schema(
        "tgt",
        [
            ("COL_01", "integer", []),
            ("COL_02", "integer", []),
        ],
    )

    mapper = LocalMappingAgent(auto_accept_threshold=0.5)
    context = AgentContext(
        source_connector="test",
        source_connection={},
        source_table="src",
        target_connector="test",
        target_connection={},
        target_table="tgt",
        source_schema=source,
        target_schema=target,
    )
    mapping_result = mapper.run(context)
    context.candidate_proposals = {"mapping_proposal": mapping_result.data}

    verifier = LocalVerifierAgent()
    verified_result = verifier.run(context)
    proposal = verified_result.data

    assert all(c.status == "flagged" for c in proposal.columns)
    assert any("generic" in (c.reason or "").lower() for c in proposal.columns)


def test_mapping_agent_auto_matches_obvious_name_and_shape():
    source = _schema(
        "src",
        [
            ("ORDER_ID", "string", ["O1"]),
            ("ORDER_DT", "string", ["2022-01-05"]),
        ],
    )
    target = _schema(
        "tgt",
        [
            ("order_id", "string", []),
            ("order_date", "date", []),
        ],
    )

    agent = LocalMappingAgent()
    context = AgentContext(
        source_connector="test",
        source_connection={},
        source_table="src",
        target_connector="test",
        target_connection={},
        target_table="tgt",
        source_schema=source,
        target_schema=target,
    )
    result = agent.run(context)
    proposal = result.data

    by_target = {c.target_column: c for c in proposal.columns}
    assert by_target["order_id"].status == "auto"
    assert by_target["order_date"].status == "auto"
