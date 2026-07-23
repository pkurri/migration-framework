import pytest

from migration_framework.conditions import Condition, ConditionError


def test_in_condition():
    cond = Condition.parse("hdr.PO_VERSION in ('E', 'B')")
    assert cond.evaluate({"PO_VERSION": "E"}) is True
    assert cond.evaluate({"PO_VERSION": "A"}) is False


def test_not_in_condition():
    cond = Condition.parse("PO_VERSION not in ('E', 'B')")
    assert cond.evaluate({"PO_VERSION": "A"}) is True
    assert cond.evaluate({"PO_VERSION": "E"}) is False


def test_eq_and_ne():
    assert Condition.parse("PO_VERSION == 'A'").evaluate({"PO_VERSION": "A"}) is True
    assert Condition.parse("PO_VERSION != 'A'").evaluate({"PO_VERSION": "A"}) is False


def test_numeric_literal():
    cond = Condition.parse("QTY == 5")
    assert cond.evaluate({"QTY": 5}) is True
    assert cond.evaluate({"QTY": 6}) is False


def test_is_null():
    assert Condition.parse("COL is null").evaluate({"COL": None}) is True
    assert Condition.parse("COL is not null").evaluate({"COL": "x"}) is True
    assert Condition.parse("COL is not null").evaluate({"COL": None}) is False


def test_unparseable_condition_raises():
    with pytest.raises(ConditionError):
        Condition.parse("this is not a real condition at all")
