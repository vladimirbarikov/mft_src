# pylint: disable=too-many-lines
# pylint: disable=protected-access
# pylint: disable=redefined-outer-name
# pylint: disable=unused-argument
# pylint: disable=missing-function-docstring
# pylint: disable=missing-class-docstring
# pylint: disable=too-few-public-methods
"""
Unit tests for the MFT loader module (dags/tasks/mft_loader.py).

All database interactions are replaced with fakes:
    - FakeEngine / FakeConnection mimic engine.begin() and connection.execute()
      and record every statement passed to the database;
    - StubMapper mimics MFTObjectMapper (get_id, map_junction_records,
      mapping getters, cache management) without a real session.

The tests cover:
    - foreign key management (disable_foreign_keys / enable_foreign_keys);
    - _bulk_insert_dataframe: empty input, required-column validation,
      NULL foreign key validation, ON CONFLICT target selection
      (including the composite part_data target), rowcount handling
      and the fallback to a regular insert;
    - _process_dependent_entity_with_mapper: FK resolution, NULL filtering,
      deduplication and version_number injection for part_data;
    - _prepare_junction_dataframes: all six junction types and deduplication;
    - load_core_entity_tables / load_junction_tables orchestration.
"""

from typing import cast

from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, ProgrammingError, SQLAlchemyError
from sqlalchemy.sql.elements import TextClause
import polars as pl
import pytest

from database.database import (
    BoxToPallet,
    ColorData,
    ConfigurationToTransmission,
    LineData,
    PartData,
    PartToBox,
    PartToColor,
    PartToLine,
    PartToModel,
    SupplierData,
    TransmissionData,
)
from dags.tasks import mft_loader
from dags.tasks.mft_mapper import MFTObjectMapper
from dags.tasks.mft_loader import (
    _bulk_insert_dataframe,
    _prepare_junction_dataframes,
    _process_dependent_entity_with_mapper,
    disable_foreign_keys,
    enable_foreign_keys,
    load_core_entity_tables,
    load_junction_tables,
)


# ---------------------------------------------------------------------------
# Fakes and stubs
# ---------------------------------------------------------------------------

class FakeResult:
    """Mimic of the SQLAlchemy Result object for execute() calls."""

    def __init__(self, rowcount=None, scalar_value=None):
        self.rowcount = rowcount
        self._scalar_value = scalar_value

    def scalar(self):
        """Return the canned scalar value (for COUNT(*) queries)."""
        return self._scalar_value


class FakeConnection:
    """
    Records executed statements and returns canned results.

    Args:
        rowcount: rowcount returned for INSERT statements
        scalar_counts: mapping of 'FROM <table>' substrings to COUNT(*) values
        insert_error: exception raised for the first INSERT statement
            (simulates a failing ON CONFLICT clause)
    """

    def __init__(
        self,
        rowcount: int | None = 0,
        scalar_counts: dict[str, int] | None = None,
        insert_error: BaseException | None = None
    ):
        self.rowcount = rowcount
        self.scalar_counts = scalar_counts or {}
        self.insert_error = insert_error
        self._insert_error_pending = insert_error is not None
        self.executed = []

    def execute(self, statement, params=None):
        """Record the statement and return a canned result."""
        self.executed.append(statement)

        if isinstance(statement, TextClause):
            statement_text = str(statement)
            for substring, count in self.scalar_counts.items():
                if substring in statement_text:
                    return FakeResult(scalar_value=count)
            return FakeResult(scalar_value=1)

        if self._insert_error_pending and self.insert_error is not None:
            self._insert_error_pending = False
            raise self.insert_error

        return FakeResult(rowcount=self.rowcount)


class FakeTransaction:
    """Context manager returned by FakeEngine.begin()."""

    def __init__(self, connection):
        self._connection = connection

    def __enter__(self):
        return self._connection

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class FakeEngine:
    """Minimal engine replacement exposing begin()."""

    def __init__(self, connection):
        self.connection = connection

    def begin(self):
        """Return a fake transaction bound to the fake connection."""
        return FakeTransaction(self.connection)


def make_engine(connection: FakeConnection) -> Engine:
    """Return the fake engine typed as a SQLAlchemy Engine."""
    return cast(Engine, FakeEngine(connection))


class StubMapper:
    """
    Duck-typed replacement for MFTObjectMapper.

    Args:
        id_mapping: mapping of (column_name, value) to database ID
        junction_records: mapping of junction_type to mapped record dicts
    """

    def __init__(self, id_mapping=None, junction_records=None):
        self.id_mapping = id_mapping or {}
        self.junction_records = junction_records or {}
        self.junction_calls = []
        self.cache_cleared = False

    def get_id(self, column_name, value):
        """Resolve a text value to a database ID."""
        return self.id_mapping.get((column_name, value))

    def map_junction_records(self, junction_df, junction_type):
        """Return canned mapped records for the junction type."""
        self.junction_calls.append(junction_type)
        return self.junction_records.get(junction_type, [])

    def log_mapping_statistics(self):
        """Pretend to log mapping statistics."""
        return 0

    def clear_cache(self):
        """Record cache clearing."""
        self.cache_cleared = True

    def _static_mapping(self):
        return {'value': 'id'}

    def get_supplier_mapping(self):
        """Return a canned supplier mapping."""
        return self._static_mapping()

    def get_part_mapping(self):
        """Return a canned part mapping."""
        return self._static_mapping()

    def get_box_mapping(self):
        """Return a canned box mapping."""
        return self._static_mapping()

    def get_pallet_mapping(self):
        """Return a canned pallet mapping."""
        return self._static_mapping()

    def get_model_mapping(self):
        """Return a canned model mapping."""
        return self._static_mapping()

    def get_configuration_mapping(self):
        """Return a canned configuration mapping."""
        return self._static_mapping()

    def get_workshop_mapping(self):
        """Return a canned workshop mapping."""
        return self._static_mapping()

    def get_line_mapping(self):
        """Return a canned line mapping."""
        return self._static_mapping()

    def get_color_mapping(self):
        """Return a canned color mapping."""
        return self._static_mapping()

    def get_transmission_mapping(self):
        """Return a canned transmission mapping."""
        return self._static_mapping()


def make_mapper(stub: StubMapper) -> MFTObjectMapper:
    """Return the stub mapper typed as MFTObjectMapper."""
    return cast(MFTObjectMapper, stub)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_connection():
    """Fake connection with rowcount=1 for inserts."""
    return FakeConnection(rowcount=1)


@pytest.fixture
def fake_engine(fake_connection):
    """Fake engine bound to the fake connection."""
    return make_engine(fake_connection)


@pytest.fixture
def supplier_df():
    """Valid supplier_data DataFrame."""
    return pl.DataFrame({
        'supplier_name': ['Test Supplier'],
        'location': ['Test Location'],
        'city': ['Test City'],
        'street': ['Test Street'],
        'building': ['1'],
        'latitude': [55.0],
        'longitude': [37.0],
        'localization': ['RU'],
    })


@pytest.fixture
def part_df():
    """Valid part_data DataFrame with resolved supplier_id."""
    return pl.DataFrame({
        'part_number': ['PN-001', 'PN-002'],
        'part_name': ['Part One', 'Part Two'],
        'part_weight_kg': [1.5, 2.5],
        'supplier_id': ['SUP-1', 'SUP-1'],
        'version_number': [1, 1],
    })


@pytest.fixture
def junction_dfs():
    """Raw junction DataFrames for all six junction types."""
    return {
        'part_to_box': pl.DataFrame({'part_number': ['PN-001']}),
        'box_to_pallet': pl.DataFrame({'part_number': ['PN-001']}),
        'part_to_model': pl.DataFrame({'part_number': ['PN-001']}),
        'part_to_line': pl.DataFrame({'part_number': ['PN-001']}),
        'part_to_color': pl.DataFrame({'part_number': ['PN-001']}),
        'configuration_to_transmission': pl.DataFrame({'configuration': ['4WD']}),
    }


def compiled_sql(statement) -> str:
    """Compile a captured INSERT statement to a SQL string."""
    return str(statement.compile(dialect=postgresql.dialect()))


# ---------------------------------------------------------------------------
# Foreign key management
# ---------------------------------------------------------------------------

class TestForeignKeyManagement:
    """Tests for disable_foreign_keys / enable_foreign_keys."""

    def test_disable_sets_replica_role(self, fake_engine, fake_connection):
        disable_foreign_keys(fake_engine)
        assert len(fake_connection.executed) == 1
        assert 'session_replication_role = replica' in str(
            fake_connection.executed[0]
        )

    def test_enable_restores_default_role(self, fake_engine, fake_connection):
        enable_foreign_keys(fake_engine)
        assert len(fake_connection.executed) == 1
        assert 'session_replication_role = DEFAULT' in str(
            fake_connection.executed[0]
        )

    def test_disable_swallows_sqlalchemy_error(self):
        class FailingConnection(FakeConnection):
            def execute(self, statement, params=None):
                raise SQLAlchemyError("boom")

        engine = make_engine(FailingConnection())
        # Must not raise
        disable_foreign_keys(engine)

    def test_enable_raises_sqlalchemy_error(self):
        class FailingConnection(FakeConnection):
            def execute(self, statement, params=None):
                raise SQLAlchemyError("boom")

        engine = make_engine(FailingConnection())
        with pytest.raises(SQLAlchemyError):
            enable_foreign_keys(engine)


# ---------------------------------------------------------------------------
# _bulk_insert_dataframe
# ---------------------------------------------------------------------------

class TestBulkInsertDataframe:
    """Tests for the internal bulk insert function."""

    def test_none_dataframe_returns_zero(self, fake_engine):
        result = _bulk_insert_dataframe(
            fake_engine, cast(pl.DataFrame, None), 'supplier_data', SupplierData
        )
        assert result == 0

    def test_empty_dataframe_returns_zero(self, fake_engine, fake_connection):
        empty_df = pl.DataFrame({'supplier_name': []})
        result = _bulk_insert_dataframe(
            fake_engine, empty_df, 'supplier_data', SupplierData
        )
        assert result == 0
        assert fake_connection.executed == []

    def test_missing_required_columns_returns_zero(
        self, fake_engine, fake_connection
    ):
        df = pl.DataFrame({'supplier_name': ['Test Supplier']})
        result = _bulk_insert_dataframe(
            fake_engine, df, 'supplier_data', SupplierData,
            required_columns_check=True
        )
        assert result == 0
        assert fake_connection.executed == []

    def test_null_supplier_id_returns_zero(self, fake_engine, fake_connection):
        df = pl.DataFrame({
            'part_number': ['PN-001'],
            'part_name': ['Part One'],
            'part_weight_kg': [1.5],
            'supplier_id': [None],
        })
        result = _bulk_insert_dataframe(
            fake_engine, df, 'part_data', PartData,
            required_columns_check=True
        )
        assert result == 0
        assert fake_connection.executed == []

    def test_null_workshop_id_returns_zero(self, fake_engine, fake_connection):
        df = pl.DataFrame({
            'line_code': ['L1'],
            'line_name': ['Line One'],
            'workshop_id': [None],
        })
        result = _bulk_insert_dataframe(
            fake_engine, df, 'line_data', LineData,
            required_columns_check=True
        )
        assert result == 0
        assert fake_connection.executed == []

    def test_explicit_conflict_columns_used(
        self, fake_engine, fake_connection, supplier_df
    ):
        result = _bulk_insert_dataframe(
            fake_engine, supplier_df, 'supplier_data', SupplierData,
            conflict_columns=['supplier_name']
        )
        assert result == 1
        sql = compiled_sql(fake_connection.executed[0])
        assert 'ON CONFLICT (supplier_name) DO NOTHING' in sql

    def test_part_data_composite_conflict_columns(
        self, fake_engine, fake_connection, part_df
    ):
        """part_data must use the composite (part_number, version_number) target."""
        result = _bulk_insert_dataframe(
            fake_engine, part_df, 'part_data', PartData,
            conflict_columns=['part_number', 'version_number']
        )
        assert result == 1
        sql = compiled_sql(fake_connection.executed[0])
        assert 'ON CONFLICT (part_number, version_number) DO NOTHING' in sql

    def test_part_data_auto_detected_conflict_columns(
        self, fake_engine, fake_connection, part_df
    ):
        """Without explicit columns part_data falls back to the composite key."""
        result = _bulk_insert_dataframe(
            fake_engine, part_df, 'part_data', PartData
        )
        assert result == 1
        sql = compiled_sql(fake_connection.executed[0])
        assert 'ON CONFLICT (part_number, version_number) DO NOTHING' in sql

    def test_junction_uses_pkey_constraint(
        self, fake_engine, fake_connection
    ):
        df = pl.DataFrame({
            'part_id': ['PRT-1'],
            'color_id': ['CLR-1'],
        })
        result = _bulk_insert_dataframe(
            fake_engine, df, 'part_to_color', PartToColor,
            required_columns_check=False
        )
        assert result == 1
        sql = compiled_sql(fake_connection.executed[0])
        assert 'ON CONFLICT ON CONSTRAINT part_to_color_pkey' in sql

    def test_configuration_to_transmission_uses_pkey_constraint(
        self, fake_engine, fake_connection
    ):
        df = pl.DataFrame({
            'configuration_id': ['CFG-1'],
            'transmission_id': ['TRM-1'],
        })
        result = _bulk_insert_dataframe(
            fake_engine, df, 'configuration_to_transmission',
            ConfigurationToTransmission,
            required_columns_check=False
        )
        assert result == 1
        sql = compiled_sql(fake_connection.executed[0])
        assert (
            'ON CONFLICT ON CONSTRAINT configuration_to_transmission_pkey'
            in sql
        )

    def test_transmission_data_conflict_columns(
        self, fake_engine, fake_connection
    ):
        df = pl.DataFrame({'transmission': ['AT']})
        result = _bulk_insert_dataframe(
            fake_engine, df, 'transmission_data', TransmissionData,
            conflict_columns=['transmission']
        )
        assert result == 1
        sql = compiled_sql(fake_connection.executed[0])
        assert 'ON CONFLICT (transmission) DO NOTHING' in sql

    def test_color_data_conflict_columns(
        self, fake_engine, fake_connection
    ):
        df = pl.DataFrame({
            'color_code': ['BK'],
            'color_name': ['Black'],
        })
        result = _bulk_insert_dataframe(
            fake_engine, df, 'color_data', ColorData,
            conflict_columns=['color_code']
        )
        assert result == 1
        sql = compiled_sql(fake_connection.executed[0])
        assert 'ON CONFLICT (color_code) DO NOTHING' in sql

    def test_rowcount_returned(self, fake_connection, supplier_df):
        connection = FakeConnection(rowcount=5)
        engine = make_engine(connection)
        result = _bulk_insert_dataframe(
            engine, supplier_df, 'supplier_data', SupplierData
        )
        assert result == 5

    def test_none_rowcount_returns_record_count(
        self, fake_connection, supplier_df
    ):
        connection = FakeConnection(rowcount=None)
        engine = make_engine(connection)
        result = _bulk_insert_dataframe(
            engine, supplier_df, 'supplier_data', SupplierData
        )
        assert result == 1

    def test_missing_constraint_falls_back_to_regular_insert(
        self, supplier_df
    ):
        error = ProgrammingError(
            "INSERT INTO supplier_data ...",
            {},
            Exception('constraint "supplier_data_pkey" does not exist')
        )
        connection = FakeConnection(insert_error=error)
        engine = make_engine(connection)
        result = _bulk_insert_dataframe(
            engine, supplier_df, 'supplier_data', SupplierData
        )
        assert result == 1
        # First attempt (ON CONFLICT) + fallback regular insert
        assert len(connection.executed) == 2

    def test_integrity_error_returns_zero(self, supplier_df):
        error = IntegrityError(
            "INSERT INTO supplier_data ...",
            {},
            Exception('duplicate key value violates unique constraint')
        )
        connection = FakeConnection(insert_error=error)
        engine = make_engine(connection)
        result = _bulk_insert_dataframe(
            engine, supplier_df, 'supplier_data', SupplierData
        )
        assert result == 0


# ---------------------------------------------------------------------------
# _process_dependent_entity_with_mapper
# ---------------------------------------------------------------------------

class TestProcessDependentEntityWithMapper:
    """Tests for dependent entity processing with FK resolution."""

    def test_part_data_supplier_resolution(self, fake_engine):
        df = pl.DataFrame({
            'part_number': ['PN-001'],
            'part_name': ['Part One'],
            'part_weight_kg': [1.5],
            'supplier_name': ['Test Supplier'],
        })
        mapper = StubMapper(
            id_mapping={('supplier_name', 'Test Supplier'): 'SUP-1'}
        )
        result = _process_dependent_entity_with_mapper(
            fake_engine, df, 'part_data', make_mapper(mapper), 'part_number',
            return_df=True
        )
        assert isinstance(result, pl.DataFrame)
        assert result['supplier_id'].to_list() == ['SUP-1']
        assert 'supplier_name' not in result.columns

    def test_part_data_version_number_injected(self, fake_engine):
        """version_number=1 must be added when the column is missing."""
        df = pl.DataFrame({
            'part_number': ['PN-001'],
            'supplier_name': ['Test Supplier'],
        })
        mapper = StubMapper(
            id_mapping={('supplier_name', 'Test Supplier'): 'SUP-1'}
        )
        result = _process_dependent_entity_with_mapper(
            fake_engine, df, 'part_data', make_mapper(mapper), 'part_number',
            return_df=True
        )
        assert isinstance(result, pl.DataFrame)
        assert 'version_number' in result.columns
        assert result['version_number'].to_list() == [1]

    def test_part_data_existing_version_number_preserved(self, fake_engine):
        df = pl.DataFrame({
            'part_number': ['PN-001'],
            'supplier_name': ['Test Supplier'],
            'version_number': [3],
        })
        mapper = StubMapper(
            id_mapping={('supplier_name', 'Test Supplier'): 'SUP-1'}
        )
        result = _process_dependent_entity_with_mapper(
            fake_engine, df, 'part_data', make_mapper(mapper), 'part_number',
            return_df=True
        )
        assert isinstance(result, pl.DataFrame)
        assert result['version_number'].to_list() == [3]

    def test_unknown_supplier_filtered_out(self, fake_engine):
        df = pl.DataFrame({
            'part_number': ['PN-001', 'PN-002'],
            'supplier_name': ['Known', 'Unknown'],
        })
        mapper = StubMapper(id_mapping={('supplier_name', 'Known'): 'SUP-1'})
        result = _process_dependent_entity_with_mapper(
            fake_engine, df, 'part_data', make_mapper(mapper), 'part_number',
            return_df=True
        )
        assert isinstance(result, pl.DataFrame)
        assert result.height == 1
        assert result['part_number'].to_list() == ['PN-001']

    def test_line_data_workshop_resolution(self, fake_engine):
        df = pl.DataFrame({
            'line_code': ['L1'],
            'line_name': ['Line One'],
            'workshop_code': ['W1'],
        })
        mapper = StubMapper(
            id_mapping={('workshop_code', 'W1'): 'WRK-1'}
        )
        result = _process_dependent_entity_with_mapper(
            fake_engine, df, 'line_data', make_mapper(mapper), 'line_code',
            return_df=True
        )
        assert isinstance(result, pl.DataFrame)
        assert result['workshop_id'].to_list() == ['WRK-1']
        assert 'workshop_code' not in result.columns

    def test_line_data_no_version_number_added(self, fake_engine):
        """version_number injection must apply to part_data only."""
        df = pl.DataFrame({
            'line_code': ['L1'],
            'workshop_code': ['W1'],
        })
        mapper = StubMapper(
            id_mapping={('workshop_code', 'W1'): 'WRK-1'}
        )
        result = _process_dependent_entity_with_mapper(
            fake_engine, df, 'line_data', make_mapper(mapper), 'line_code',
            return_df=True
        )
        assert isinstance(result, pl.DataFrame)
        assert 'version_number' not in result.columns

    def test_duplicates_removed(self, fake_engine):
        df = pl.DataFrame({
            'part_number': ['PN-001', 'PN-001'],
            'supplier_name': ['Test Supplier', 'Test Supplier'],
        })
        mapper = StubMapper(
            id_mapping={('supplier_name', 'Test Supplier'): 'SUP-1'}
        )
        result = _process_dependent_entity_with_mapper(
            fake_engine, df, 'part_data', make_mapper(mapper), 'part_number',
            return_df=True
        )
        assert isinstance(result, pl.DataFrame)
        assert result.height == 1

    def test_empty_dataframe_returns_zero(self, fake_engine):
        empty_df = pl.DataFrame({'part_number': []})
        mapper = StubMapper()
        result = _process_dependent_entity_with_mapper(
            fake_engine, empty_df, 'part_data', make_mapper(mapper), 'part_number'
        )
        assert isinstance(result, int)
        assert result == 0

    def test_return_df_false_loads_to_database(self):
        connection = FakeConnection(rowcount=1)
        engine = make_engine(connection)
        df = pl.DataFrame({
            'part_number': ['PN-001'],
            'part_name': ['Part One'],
            'part_weight_kg': [1.5],
            'supplier_name': ['Test Supplier'],
        })
        mapper = StubMapper(
            id_mapping={('supplier_name', 'Test Supplier'): 'SUP-1'}
        )
        result = _process_dependent_entity_with_mapper(
            engine, df, 'part_data', make_mapper(mapper), 'part_number',
            return_df=False
        )
        assert isinstance(result, int)
        assert result == 1
        assert len(connection.executed) == 1


# ---------------------------------------------------------------------------
# _prepare_junction_dataframes
# ---------------------------------------------------------------------------

class TestPrepareJunctionDataframes:
    """Tests for junction DataFrame preparation."""

    def _stub_mapper(self):
        return StubMapper(junction_records={
            'part_to_box_composite': [
                {'part_id': 'PRT-1', 'box_id': 'BOX-1', 'part_per_box': 10},
            ],
            'box_to_pallet_composite': [
                {'part_id': 'PRT-1', 'box_id': 'BOX-1', 'pallet_id': 'PAL-1'},
            ],
            'part_to_model': [
                {
                    'part_id': 'PRT-1',
                    'model_id': 'MDL-1',
                    'configuration_id': 'CFG-1',
                },
            ],
            'part_to_line': [
                {'part_id': 'PRT-1', 'line_id': 'LN-1'},
            ],
            'part_to_color': [
                {'part_id': 'PRT-1', 'color_id': 'CLR-1'},
            ],
            'configuration_to_transmission': [
                {'configuration_id': 'CFG-1', 'transmission_id': 'TRM-1'},
            ],
        })

    def test_all_six_junction_types_mapped(self, junction_dfs):
        mapper = self._stub_mapper()
        mapped_data = _prepare_junction_dataframes(junction_dfs, make_mapper(mapper))

        assert set(mapped_data.keys()) == set(junction_dfs.keys())
        assert mapped_data['part_to_box']['model_class'] is PartToBox
        assert mapped_data['box_to_pallet']['model_class'] is BoxToPallet
        assert mapped_data['part_to_model']['model_class'] is PartToModel
        assert mapped_data['part_to_line']['model_class'] is PartToLine
        assert mapped_data['part_to_color']['model_class'] is PartToColor
        assert (
            mapped_data['configuration_to_transmission']['model_class']
            is ConfigurationToTransmission
        )

    def test_mapper_receives_correct_junction_types(self, junction_dfs):
        mapper = self._stub_mapper()
        _prepare_junction_dataframes(junction_dfs, make_mapper(mapper))
        assert set(mapper.junction_calls) == {
            'part_to_box_composite',
            'box_to_pallet_composite',
            'part_to_model',
            'part_to_line',
            'part_to_color',
            'configuration_to_transmission',
        }

    def test_empty_junction_dict_returns_empty(self):
        mapper = self._stub_mapper()
        assert not _prepare_junction_dataframes({}, make_mapper(mapper))

    def test_empty_dataframe_skipped(self):
        mapper = self._stub_mapper()
        junction_dict = {
            'part_to_color': pl.DataFrame({'part_number': []}),
        }
        assert not _prepare_junction_dataframes(junction_dict, make_mapper(mapper))
        assert not mapper.junction_calls

    def test_no_mapped_records_skipped(self):
        mapper = StubMapper(junction_records={})
        junction_dict = {
            'part_to_color': pl.DataFrame({'part_number': ['PN-001']}),
        }
        assert not _prepare_junction_dataframes(junction_dict, make_mapper(mapper))

    def test_part_to_color_deduplication(self):
        mapper = StubMapper(junction_records={
            'part_to_color': [
                {'part_id': 'PRT-1', 'color_id': 'CLR-1'},
                {'part_id': 'PRT-1', 'color_id': 'CLR-1'},
                {'part_id': 'PRT-1', 'color_id': 'CLR-2'},
            ],
        })
        junction_dict = {
            'part_to_color': pl.DataFrame(
                {'part_number': ['PN-001', 'PN-001', 'PN-001']}
            ),
        }
        mapped_data = _prepare_junction_dataframes(junction_dict, make_mapper(mapper))
        df_mapped = mapped_data['part_to_color']['df']
        assert df_mapped.height == 2

    def test_configuration_to_transmission_deduplication(self):
        mapper = StubMapper(junction_records={
            'configuration_to_transmission': [
                {'configuration_id': 'CFG-1', 'transmission_id': 'TRM-1'},
                {'configuration_id': 'CFG-1', 'transmission_id': 'TRM-1'},
            ],
        })
        junction_dict = {
            'configuration_to_transmission': pl.DataFrame(
                {'configuration': ['4WD', '4WD']}
            ),
        }
        mapped_data = _prepare_junction_dataframes(junction_dict, make_mapper(mapper))
        df_mapped = mapped_data['configuration_to_transmission']['df']
        assert df_mapped.height == 1


# ---------------------------------------------------------------------------
# load_core_entity_tables
# ---------------------------------------------------------------------------

class TestLoadCoreEntityTables:
    """Tests for core entity table loading orchestration."""

    def test_missing_dataframes_return_zeros(self, fake_engine):
        results = load_core_entity_tables(
            {}, fake_engine, resolve_foreign_keys=False
        )
        assert results['supplier_data'] == 0
        assert results['transmission_data'] == 0
        assert results['color_data'] == 0

    def test_independent_tables_loaded(
        self, fake_engine, fake_connection, supplier_df
    ):
        transformed_data = {
            'transformed_supplier_df': supplier_df,
            'transformed_transmission_df': pl.DataFrame(
                {'transmission': ['AT', 'AT', 'MT']}
            ),
            'transformed_color_df': pl.DataFrame({
                'color_code': ['BK'],
                'color_name': ['Black'],
            }),
        }
        results = load_core_entity_tables(
            transformed_data, fake_engine, resolve_foreign_keys=False
        )
        assert results['supplier_data'] == 1
        assert results['transmission_data'] == 1
        assert results['color_data'] == 1
        # Duplicates removed from transmission_data (AT twice) -> 2 records,
        # but rowcount is fake; check the compiled statement instead
        insert_statements = [
            stmt for stmt in fake_connection.executed
            if not isinstance(stmt, TextClause)
        ]
        assert len(insert_statements) == 3

    def test_transmission_deduplication(self, fake_connection):
        captured = {}

        def fake_bulk_insert(engine, df, table_name, model_class, **kwargs):
            captured[table_name] = df
            return df.height

        original = mft_loader._bulk_insert_dataframe
        mft_loader._bulk_insert_dataframe = fake_bulk_insert
        try:
            transformed_data = {
                'transformed_transmission_df': pl.DataFrame(
                    {'transmission': ['AT', 'AT', 'MT']}
                ),
            }
            results = load_core_entity_tables(
                transformed_data, make_engine(fake_connection),
                resolve_foreign_keys=False
            )
        finally:
            mft_loader._bulk_insert_dataframe = original

        assert captured['transmission_data'].height == 2
        assert results['transmission_data'] == 2

    def test_version_number_injected_for_part_data(self, fake_connection):
        captured = {}

        def fake_bulk_insert(engine, df, table_name, model_class, **kwargs):
            captured[table_name] = df
            return df.height

        stub_mapper = StubMapper(
            id_mapping={('supplier_name', 'Test Supplier'): 'SUP-1'}
        )
        original_insert = mft_loader._bulk_insert_dataframe
        original_factory = mft_loader.create_mft_mapper
        mft_loader._bulk_insert_dataframe = fake_bulk_insert
        mft_loader.create_mft_mapper = lambda engine=None: stub_mapper
        try:
            transformed_data = {
                'transformed_part_df': pl.DataFrame({
                    'part_number': ['PN-001'],
                    'part_name': ['Part One'],
                    'part_weight_kg': [1.5],
                    'supplier_name': ['Test Supplier'],
                }),
            }
            results = load_core_entity_tables(
                transformed_data, make_engine(fake_connection),
                resolve_foreign_keys=True
            )
        finally:
            mft_loader._bulk_insert_dataframe = original_insert
            mft_loader.create_mft_mapper = original_factory

        part_result = captured['part_data']
        assert 'version_number' in part_result.columns
        assert part_result['version_number'].to_list() == [1]
        assert part_result['supplier_id'].to_list() == ['SUP-1']
        assert results['part_data'] == 1


# ---------------------------------------------------------------------------
# load_junction_tables
# ---------------------------------------------------------------------------

class TestLoadJunctionTables:
    """Tests for junction table loading orchestration."""

    def _stub_mapper(self):
        return StubMapper(junction_records={
            'part_to_color': [
                {'part_id': 'PRT-1', 'color_id': 'CLR-1'},
            ],
            'configuration_to_transmission': [
                {'configuration_id': 'CFG-1', 'transmission_id': 'TRM-1'},
            ],
        })

    def test_empty_critical_table_aborts_loading(self, monkeypatch):
        # part_data is a critical table: empty -> loading must abort
        connection = FakeConnection(scalar_counts={'FROM part_data': 0})
        engine = make_engine(connection)
        monkeypatch.setattr(
            mft_loader, 'create_mft_mapper',
            lambda engine=None: self._stub_mapper()
        )
        results = load_junction_tables(
            {'part_to_color': pl.DataFrame({'part_number': ['PN-001']})},
            engine
        )
        assert not results

    def test_empty_reference_table_does_not_abort(self, monkeypatch):
        # color_data is a reference table: empty -> warning only, no abort
        connection = FakeConnection(
            rowcount=1, scalar_counts={'FROM color_data': 0}
        )
        engine = make_engine(connection)
        monkeypatch.setattr(
            mft_loader, 'create_mft_mapper',
            lambda engine=None: self._stub_mapper()
        )
        results = load_junction_tables(
            {'part_to_color': pl.DataFrame({'part_number': ['PN-001']})},
            engine
        )
        assert results['part_to_color'] == 1

    def test_successful_loading_of_new_junctions(self, monkeypatch):
        connection = FakeConnection(rowcount=1)
        engine = make_engine(connection)
        stub_mapper = self._stub_mapper()
        monkeypatch.setattr(
            mft_loader, 'create_mft_mapper',
            lambda engine=None: stub_mapper
        )
        junction_dict = {
            'part_to_color': pl.DataFrame({'part_number': ['PN-001']}),
            'configuration_to_transmission': pl.DataFrame(
                {'configuration': ['4WD']}
            ),
        }
        results = load_junction_tables(junction_dict, engine)

        assert results['part_to_color'] == 1
        assert results['configuration_to_transmission'] == 1
        assert stub_mapper.cache_cleared is True

    def test_missing_junction_keys_yield_zero_results(self, monkeypatch):
        connection = FakeConnection(rowcount=1)
        engine = make_engine(connection)
        monkeypatch.setattr(
            mft_loader, 'create_mft_mapper',
            lambda engine=None: self._stub_mapper()
        )
        results = load_junction_tables(
            {'part_to_color': pl.DataFrame({'part_number': ['PN-001']})},
            engine
        )
        assert results['part_to_color'] == 1
        assert results['part_to_box'] == 0
        assert results['part_to_model'] == 0

    def test_preserve_cache_keeps_mapper_cache(self, monkeypatch):
        connection = FakeConnection(rowcount=1)
        engine = make_engine(connection)
        stub_mapper = self._stub_mapper()
        monkeypatch.setattr(
            mft_loader, 'create_mft_mapper',
            lambda engine=None: stub_mapper
        )
        load_junction_tables(
            {'part_to_color': pl.DataFrame({'part_number': ['PN-001']})},
            engine,
            preserve_cache=True
        )
        assert stub_mapper.cache_cleared is False

    def test_empty_junction_dict_returns_empty(self, monkeypatch):
        connection = FakeConnection()
        engine = make_engine(connection)
        monkeypatch.setattr(
            mft_loader, 'create_mft_mapper',
            lambda engine=None: self._stub_mapper()
        )
        assert not load_junction_tables({}, engine)
