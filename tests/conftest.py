# pylint: disable=wrong-import-position
"""
Shared pytest fixtures for MFT Database unit tests.

Provides a fake SQLAlchemy session that serves canned rows per model class,
so mapper/loader logic can be tested without a real PostgreSQL database.

The fixture approach:
    - MFTObjectMapper calls ``session.query(Model.col_a, Model.col_b).all()``
    - FakeSession inspects the first queried column (``columns[0].class_``)
      and returns rows registered for that model class
    - Query counting allows asserting cache behaviour
"""

import sys
from pathlib import Path

import pytest

# Ensure the project root is importable when pytest runs from any directory
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.database import (  # noqa: E402
    SupplierData, PartData, BoxData, PalletData, ModelData,
    ConfigurationData, TransmissionData, ColorData, LineData,
)


class FakeQuery:
    """Minimal stand-in for sqlalchemy.orm.Query (only .all() is used)."""

    def __init__(self, rows: list):
        self._rows = rows

    def all(self) -> list:
        """Return the canned rows."""
        return list(self._rows)


class FakeSession:
    """
    Minimal stand-in for sqlalchemy.orm.Session.

    Args:
        tables: Mapping of ORM model class to a list of row tuples.
                Column order inside each tuple must match the order
                requested by the mapper for that model.
    """

    def __init__(self, tables: dict):
        self._tables = tables
        self.query_calls = 0

    def query(self, *columns) -> FakeQuery:
        """Serve canned rows for the model class of the first column."""
        self.query_calls += 1
        model_cls = columns[0].class_
        return FakeQuery(self._tables.get(model_cls, []))


@pytest.fixture
def fake_db_rows() -> dict:
    """
    Canned database content for all entity types used by MFTObjectMapper.

    Row layouts mirror the mapper's queries:
        - standard lookups: (lookup_value, id)
        - composite lookups: (type, length, width, height, id)
    """
    return {
        SupplierData: [
            ('Ningbo Minda', 'SUP_00000000-0000-0000-0000-000000000001'),
            ('Nobo Automotive', 'SUP_00000000-0000-0000-0000-000000000002'),
        ],
        PartData: [
            ('09120006', 'PRT_00000000-0000-0000-0000-000000000001'),
            ('1000100XKN04A', 'PRT_00000000-0000-0000-0000-000000000002'),
        ],
        BoxData: [
            ('returnable', 400, 300, 200, 'BOX_00000000-0000-0000-0000-000000000001'),
            ('non-returnable', 275, 240, 260, 'BOX_00000000-0000-0000-0000-000000000002'),
        ],
        PalletData: [
            ('non-returnable', 1140, 1480, 620, 'PLT_00000000-0000-0000-0000-000000000001'),
        ],
        ModelData: [
            ('CC7150BA24C', 'MDL_00000000-0000-0000-0000-000000000001'),
            ('CC6450BA26B', 'MDL_00000000-0000-0000-0000-000000000002'),
        ],
        ConfigurationData: [
            ('comfort', 'CFG_00000000-0000-0000-0000-000000000001'),
            ('no data', 'CFG_00000000-0000-0000-0000-000000000002'),
        ],
        TransmissionData: [
            ('no data', 'TRN_00000000-0000-0000-0000-000000000001'),
            ('4wd', 'TRN_00000000-0000-0000-0000-000000000002'),
        ],
        ColorData: [
            ('no data', 'CLR_00000000-0000-0000-0000-000000000001'),
            ('7137M', 'CLR_00000000-0000-0000-0000-000000000002'),
        ],
        LineData: [
            ('HAA102', 'LNE_00000000-0000-0000-0000-000000000001'),
            ('HAC204', 'LNE_00000000-0000-0000-0000-000000000002'),
        ],
    }


@pytest.fixture
def fake_session(fake_db_rows) -> FakeSession:
    """Fake session pre-loaded with canned rows."""
    return FakeSession(fake_db_rows)


@pytest.fixture
def mapper(fake_session):
    """MFTObjectMapper instance backed by the fake session."""
    from dags.tasks.mft_mapper import MFTObjectMapper
    return MFTObjectMapper(fake_session)
