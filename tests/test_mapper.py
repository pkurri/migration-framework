from migration_framework.connectors.base import ColumnInfo, TableSchema
from migration_framework.mapper import propose_mapping


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


def test_obvious_name_and_type_match_is_auto_mapped():
    source = _schema(
        "src",
        [
            ("PO_HDR_SNUM", "string", ["A1", "A2"]),
            ("Q_PO_CREATE_DT", "string", ["2021-05-01", "2021-06-01"]),
        ],
    )
    target = _schema(
        "tgt",
        [
            ("PO_HDR_SNUM", "string", []),
            ("PO_CREATE_DT", "date", []),
        ],
    )

    proposal = propose_mapping(source, target)

    by_target = {c.target_column: c for c in proposal.columns}
    assert by_target["PO_HDR_SNUM"].status == "auto"
    assert by_target["PO_HDR_SNUM"].best.source_column == "PO_HDR_SNUM"
    assert by_target["PO_CREATE_DT"].status == "auto"
    assert by_target["PO_CREATE_DT"].best.source_column == "Q_PO_CREATE_DT"


def test_generic_numbered_column_gets_flagged_not_guessed():
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

    proposal = propose_mapping(source, target)

    # both source columns look equally date-shaped and have no name signal
    # pointing at either target column - this must NOT be silently guessed.
    assert all(c.status == "flagged" for c in proposal.columns)


def test_no_candidate_columns_are_flagged_as_no_match():
    source = _schema("src", [("UNRELATED_COL", "string", ["hello"])])
    target = _schema("tgt", [("EDIT_PHASE_IND", "string", [])])

    proposal = propose_mapping(source, target)

    assert proposal.columns[0].status == "flagged"


def test_two_target_columns_dont_both_claim_the_same_source_column():
    source = _schema("src", [("VENDOR_NUMBER", "string", ["V1"])])
    target = _schema(
        "tgt",
        [
            ("VENDOR_NUMBER", "string", []),
            ("VENDOR_NUM", "string", []),
        ],
    )

    proposal = propose_mapping(source, target)
    autos = [c for c in proposal.columns if c.status == "auto"]
    auto_sources = [c.best.source_column for c in autos]
    assert len(auto_sources) == len(set(auto_sources))
