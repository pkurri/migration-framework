from migration_framework.config import (
    AuditColumn,
    ColumnMapping,
    JoinFilter,
    JoinSpec,
    MigrationConfig,
    SourceSpec,
    TargetSpec,
    ValidationSpec,
)


def _sample_config() -> MigrationConfig:
    return MigrationConfig(
        job_name="po_header_apac",
        source=SourceSpec(
            connector="sqlalchemy",
            connection={"connection_url": "sqlite:///source.db"},
            table="dw_po_hdr",
            joins=[
                JoinSpec(
                    alias="dtl",
                    table="dw_po_dtl",
                    join_on={"left": "PO_HDR_SNUM", "right": "PO_HDR_SNUM"},
                    mode="semi",
                    filter=JoinFilter(
                        column="BANNER_GEO",
                        equals="APAC",
                        via_table="dim_location_t",
                        via_join_on={"left": "STR_SNUM", "right": "LOC_NUM"},
                    ),
                )
            ],
        ),
        target=TargetSpec(
            connector="sqlalchemy",
            connection={"connection_url": "sqlite:///target.db"},
            table="PO_MF_HEADER_APAC_T",
            mode="append",
        ),
        columns=[
            ColumnMapping(target="PO_HDR_SNUM", source="PO_HDR_SNUM", trim=True, matched_by="auto"),
            ColumnMapping(
                target="EDIT_PHASE_IND",
                derived={"when": [{"condition": "PO_VERSION in ('E','B')", "then": "Y"}], "otherwise": None},
                matched_by="human_defined",
            ),
        ],
        audit_columns=[AuditColumn(name="BATCH_ID", generator="batch_id")],
        validation=ValidationSpec(expected_column_count=2),
    )


def test_round_trip_through_dict():
    config = _sample_config()
    restored = MigrationConfig.from_dict(config.to_dict())
    assert restored.job_name == config.job_name
    assert restored.source.joins[0].filter.via_table == "dim_location_t"
    assert restored.columns[1].derived["when"][0]["condition"] == "PO_VERSION in ('E','B')"


def test_round_trip_through_yaml_file(tmp_path):
    config = _sample_config()
    path = tmp_path / "job.yaml"
    config.save(str(path))

    loaded = MigrationConfig.load(str(path))
    assert loaded.job_name == config.job_name
    assert loaded.target.table == config.target.table
    assert len(loaded.columns) == len(config.columns)
