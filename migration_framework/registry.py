"""Maps a `connector: <name>` string in config to an actual Connector class.

Adding support for a new system - a message queue, a flat-file format,
whatever - means registering one more entry here. Nothing else in the
framework changes.
"""

from __future__ import annotations

from typing import Any

from .connectors.base import Connector
from .connectors.sqlalchemy_connector import SQLAlchemyConnector

CONNECTOR_REGISTRY: dict[str, type[Connector]] = {
    "sqlalchemy": SQLAlchemyConnector,
    # Any SQLAlchemy-dialect database (Postgres, MySQL, SQLite, Snowflake via
    # `snowflake-sqlalchemy`, Databricks via `databricks-sqlalchemy`, ...)
    # is reachable through the one connector above with a different
    # connection string - register dedicated connectors here only when a
    # system doesn't speak SQL at all (an API, a message queue, flat files).
}


def register_connector(name: str, connector_cls: type[Connector]) -> None:
    CONNECTOR_REGISTRY[name] = connector_cls


def build_connector(connector_name: str, connection: dict[str, Any]) -> Connector:
    try:
        connector_cls = CONNECTOR_REGISTRY[connector_name]
    except KeyError:
        raise ValueError(
            f"No connector registered as {connector_name!r}. "
            f"Known connectors: {sorted(CONNECTOR_REGISTRY)}. "
            "Register a new one with migration_framework.registry.register_connector()."
        )
    return connector_cls(**connection)
