"""Reproduces the original script's region filter: keep header rows that have
at least one detail row whose store maps to the requested region, without a
person hand-writing that join in Python."""

from sqlalchemy import Column, Float, MetaData, String, Table, create_engine

from migration_framework.config import ColumnMapping, JoinFilter, JoinSpec, MigrationConfig, SourceSpec, TargetSpec
from migration_framework.engine import run_migration


def _make_source_db(path) -> None:
    engine = create_engine(f"sqlite:///{path}")
    metadata = MetaData()
    header = Table("dw_po_hdr", metadata, Column("PO_HDR_SNUM", String, primary_key=True), Column("VND_SNUM", String))
    detail = Table("dw_po_dtl", metadata, Column("PO_HDR_SNUM", String), Column("STR_SNUM", String))
    location = Table("dim_location_t", metadata, Column("LOC_NUM", String, primary_key=True), Column("BANNER_GEO", String))
    metadata.create_all(engine)

    with engine.begin() as conn:
        conn.execute(header.insert(), [
            {"PO_HDR_SNUM": "PO1", "VND_SNUM": "V1"},   # ships to an APAC store
            {"PO_HDR_SNUM": "PO2", "VND_SNUM": "V2"},   # ships to a NA store
        ])
        conn.execute(detail.insert(), [
            {"PO_HDR_SNUM": "PO1", "STR_SNUM": "S100"},
            {"PO_HDR_SNUM": "PO2", "STR_SNUM": "S200"},
        ])
        conn.execute(location.insert(), [
            {"LOC_NUM": "S100", "BANNER_GEO": "APAC"},
            {"LOC_NUM": "S200", "BANNER_GEO": "NA"},
        ])
    engine.dispose()


def _make_target_db(path) -> None:
    engine = create_engine(f"sqlite:///{path}")
    metadata = MetaData()
    Table("po_header_apac", metadata, Column("po_hdr_snum", String, primary_key=True), Column("vendor", String))
    metadata.create_all(engine)
    engine.dispose()


def test_region_semi_join_keeps_only_matching_header_rows(tmp_path):
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"
    _make_source_db(source_path)
    _make_target_db(target_path)

    config = MigrationConfig(
        job_name="po_header_apac",
        source=SourceSpec(
            connector="sqlalchemy",
            connection={"connection_url": f"sqlite:///{source_path}"},
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
            connection={"connection_url": f"sqlite:///{target_path}"},
            table="po_header_apac",
            mode="append",
        ),
        columns=[
            ColumnMapping(target="po_hdr_snum", source="PO_HDR_SNUM"),
            ColumnMapping(target="vendor", source="VND_SNUM"),
        ],
    )

    result = run_migration(config)

    assert result.rows_read == 1  # only PO1 ships to an APAC store
    assert result.rows_written == 1
