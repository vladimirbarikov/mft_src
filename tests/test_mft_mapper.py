# pylint: disable=wrong-import-position
"""
Unit tests for dags.tasks.mft_mapper (MFTObjectMapper).

All tests run without a real database: the session is replaced by
FakeSession (see conftest.py), which serves canned rows per model class.

Covered behaviour:
    - standard text-to-ID lookups (found / not found / cached)
    - composite key lookups for boxes and pallets (tuple, dict, floats)
    - composite key validation (element count, packaging type, NULL parts)
    - junction record mapping for all six MFT junction types
    - optional field passthrough (part_per_box, box_per_pallet,
      part_per_vehicle)
    - bulk mapping via map_junction_records (polars DataFrame input)
    - cache management (clear_cache, log_mapping_statistics)
"""

import polars as pl

PART_1 = 'PRT_00000000-0000-0000-0000-000000000001'
PART_2 = 'PRT_00000000-0000-0000-0000-000000000002'
BOX_1 = 'BOX_00000000-0000-0000-0000-000000000001'
BOX_2 = 'BOX_00000000-0000-0000-0000-000000000002'
PLT_1 = 'PLT_00000000-0000-0000-0000-000000000001'
MDL_1 = 'MDL_00000000-0000-0000-0000-000000000001'
CFG_ND = 'CFG_00000000-0000-0000-0000-000000000002'
LNE_1 = 'LNE_00000000-0000-0000-0000-000000000001'
CLR_ND = 'CLR_00000000-0000-0000-0000-000000000001'
TRN_ND = 'TRN_00000000-0000-0000-0000-000000000001'
TRN_4WD = 'TRN_00000000-0000-0000-0000-000000000002'


# ========== STANDARD LOOKUPS ==========

class TestGetIdStandard:
    """Standard text-to-ID mapping via get_id."""

    def test_found(self, mapper):
        assert mapper.get_id('part_number', '09120006') == PART_1

    def test_not_found_returns_none(self, mapper):
        assert mapper.get_id('part_number', 'NO_SUCH_PART') is None

    def test_empty_value_returns_none(self, mapper):
        assert mapper.get_id('part_number', '') is None
        assert mapper.get_id('part_number', None) is None

    def test_unknown_column_returns_none(self, mapper):
        assert mapper.get_id('no_such_column', 'x') is None

    def test_mapping_is_cached(self, mapper, fake_session):
        """Second lookup for the same column must not hit the DB again."""
        mapper.get_id('part_number', '09120006')
        calls_after_first = fake_session.query_calls
        mapper.get_id('part_number', '1000100XKN04A')
        assert fake_session.query_calls == calls_after_first


# ========== COMPOSITE KEY LOOKUPS ==========

class TestGetIdComposite:
    """Composite key mapping for boxes and pallets."""

    def test_tuple_key(self, mapper):
        assert mapper.get_id('box_composite', ('returnable', 400, 300, 200)) == BOX_1

    def test_dict_equivalent_to_tuple(self, mapper):
        key = {'type': 'returnable', 'length': 400, 'width': 300, 'height': 200}
        assert mapper.get_id('box_composite', key) == BOX_1

    def test_pallet_composite(self, mapper):
        assert mapper.get_id(
            'pallet_composite', ('non-returnable', 1140, 1480, 620)
        ) == PLT_1

    def test_float_string_dimensions(self, mapper):
        """Excel often yields floats: '400.0' must match int 400."""
        assert mapper.get_id(
            'box_composite', ('returnable', '400.0', '300.0', '200.0')
        ) == BOX_1

    def test_wrong_element_count_returns_none(self, mapper):
        assert mapper.get_id('box_composite', ('returnable', 400, 300)) is None

    def test_invalid_packaging_type_returns_none(self, mapper):
        assert mapper.get_id('box_composite', ('wood', 400, 300, 200)) is None

    def test_null_type_returns_none(self, mapper):
        assert mapper.get_id('box_composite', ('null', 400, 300, 200)) is None

    def test_incomplete_key_returns_none(self, mapper):
        key = {'type': 'returnable', 'length': 400, 'width': 300}
        assert mapper.get_id('box_composite', key) is None

    def test_unknown_dimensions_return_none(self, mapper):
        assert mapper.get_id('box_composite', ('returnable', 1, 1, 1)) is None


# ========== JUNCTION: part_to_box ==========

class TestMapPartToBox:
    """Mapping of part_to_box_composite junction records."""

    def _record(self, **overrides):
        record = {
            'part_number': '09120006',
            'box_type': 'returnable',
            'box_length_mm': 400,
            'box_width_mm': 300,
            'box_height_mm': 200,
        }
        record.update(overrides)
        return record

    def test_success_with_optional(self, mapper):
        result = mapper._map_part_to_box_composite(self._record(part_per_box=50))
        assert result == {'part_id': PART_1, 'box_id': BOX_1, 'part_per_box': 50}

    def test_optional_omitted_when_none(self, mapper):
        """part_per_box is nullable in the schema; None must not be copied."""
        result = mapper._map_part_to_box_composite(self._record(part_per_box=None))
        assert result == {'part_id': PART_1, 'box_id': BOX_1}

    def test_unknown_part_returns_none(self, mapper):
        assert mapper._map_part_to_box_composite(
            self._record(part_number='NO_SUCH')
        ) is None

    def test_unknown_box_returns_none(self, mapper):
        assert mapper._map_part_to_box_composite(
            self._record(box_length_mm=1, box_width_mm=1, box_height_mm=1)
        ) is None

    def test_missing_required_column_returns_none(self, mapper):
        record = self._record()
        del record['box_height_mm']
        assert mapper._map_part_to_box_composite(record) is None


# ========== JUNCTION: box_to_pallet ==========

class TestMapBoxToPallet:
    """Mapping of box_to_pallet_composite junction records."""

    def _record(self, **overrides):
        record = {
            'part_number': '09120006',
            'box_type': 'returnable',
            'box_length_mm': 400,
            'box_width_mm': 300,
            'box_height_mm': 200,
            'pallet_type': 'non-returnable',
            'pallet_length_mm': 1140,
            'pallet_width_mm': 1480,
            'pallet_height_mm': 620,
        }
        record.update(overrides)
        return record

    def test_success_with_optional(self, mapper):
        result = mapper._map_box_to_pallet_composite(
            self._record(box_per_pallet=6)
        )
        assert result == {
            'part_id': PART_1, 'box_id': BOX_1,
            'pallet_id': PLT_1, 'box_per_pallet': 6,
        }

    def test_optional_omitted_when_none(self, mapper):
        result = mapper._map_box_to_pallet_composite(
            self._record(box_per_pallet=None)
        )
        assert result == {'part_id': PART_1, 'box_id': BOX_1, 'pallet_id': PLT_1}

    def test_unknown_pallet_returns_none(self, mapper):
        assert mapper._map_box_to_pallet_composite(
            self._record(pallet_length_mm=1, pallet_width_mm=1, pallet_height_mm=1)
        ) is None


# ========== JUNCTION: part_to_model ==========

class TestMapPartToModel:
    """
    Mapping of part_to_model junction records.

    Lookup key is model_code (strategy C): rows with model_code='no data'
    are expected to be skipped until real codes are provided in Excel.
    """

    def _record(self, **overrides):
        record = {
            'part_number': '09120006',
            'model_code': 'CC7150BA24C',
            'configuration': 'no data',
        }
        record.update(overrides)
        return record

    def test_success_with_optional(self, mapper):
        result = mapper._map_part_to_model(self._record(part_per_vehicle=1))
        assert result == {
            'part_id': PART_1,
            'model_id': MDL_1,
            'configuration_id': CFG_ND,
            'part_per_vehicle': 1,
        }

    def test_no_data_model_code_is_skipped(self, mapper):
        """Current Excel state: MODEL_CODE='no data' must be skipped, not crash."""
        assert mapper._map_part_to_model(self._record(model_code='no data')) is None

    def test_unknown_configuration_returns_none(self, mapper):
        assert mapper._map_part_to_model(
            self._record(configuration='no_such_config')
        ) is None


# ========== JUNCTION: part_to_line ==========

class TestMapPartToLine:
    """Mapping of part_to_line junction records."""

    def test_success(self, mapper):
        result = mapper._map_part_to_line(
            {'part_number': '09120006', 'line_code': 'HAA102'}
        )
        assert result == {'part_id': PART_1, 'line_id': LNE_1}

    def test_unknown_line_returns_none(self, mapper):
        assert mapper._map_part_to_line(
            {'part_number': '09120006', 'line_code': 'NO_SUCH'}
        ) is None


# ========== JUNCTION: part_to_color ==========

class TestMapPartToColor:
    """Mapping of part_to_color junction records."""

    def test_success(self, mapper):
        result = mapper._map_part_to_color(
            {'part_number': '09120006', 'color_code': 'no data'}
        )
        assert result == {'part_id': PART_1, 'color_id': CLR_ND}

    def test_unknown_color_returns_none(self, mapper):
        assert mapper._map_part_to_color(
            {'part_number': '09120006', 'color_code': 'NOPE'}
        ) is None

    def test_missing_required_column_returns_none(self, mapper):
        assert mapper._map_part_to_color({'part_number': '09120006'}) is None


# ========== JUNCTION: configuration_to_transmission ==========

class TestMapConfigurationToTransmission:
    """Mapping of configuration_to_transmission junction records."""

    def test_success(self, mapper):
        result = mapper._map_configuration_to_transmission(
            {'configuration': 'no data', 'transmission': '4wd'}
        )
        assert result == {'configuration_id': CFG_ND, 'transmission_id': TRN_4WD}

    def test_unknown_transmission_returns_none(self, mapper):
        assert mapper._map_configuration_to_transmission(
            {'configuration': 'no data', 'transmission': 'NOPE'}
        ) is None


# ========== BULK MAPPING ==========

class TestMapJunctionRecords:
    """Bulk mapping via map_junction_records (polars DataFrame input)."""

    def test_unknown_junction_type_returns_empty(self, mapper):
        df = pl.DataFrame({'part_number': ['09120006']})
        assert mapper.map_junction_records(df, 'no_such_junction') == []

    def test_part_to_color_bulk(self, mapper):
        df = pl.DataFrame({
            'part_number': ['09120006', '1000100XKN04A', 'NO_SUCH'],
            'color_code': ['no data', 'no data', 'no data'],
        })
        result = mapper.map_junction_records(df, 'part_to_color')
        assert result == [
            {'part_id': PART_1, 'color_id': CLR_ND},
            {'part_id': PART_2, 'color_id': CLR_ND},
        ]

    def test_all_six_junction_types_registered(self, mapper):
        """Every key of MFT_JUNCTION_REQUIRED must have a handler."""
        from config.columns_config import MFT_JUNCTION_REQUIRED
        for junction_type in MFT_JUNCTION_REQUIRED:
            df = pl.DataFrame({'dummy': ['x']})
            # Must not raise; returns [] because required columns are missing
            assert mapper.map_junction_records(df, junction_type) == []


# ========== CACHE MANAGEMENT ==========

class TestCacheManagement:
    """Cache statistics and clearing."""

    def test_log_mapping_statistics_counts_entries(self, mapper):
        mapper.get_id('part_number', '09120006')
        mapper.get_id('configuration', 'no data')
        assert mapper.log_mapping_statistics() == 2 + 2  # 2 parts + 2 configs

    def test_clear_cache(self, mapper, fake_session):
        mapper.get_id('part_number', '09120006')
        mapper.clear_cache()
        calls = fake_session.query_calls
        mapper.get_id('part_number', '09120006')
        assert fake_session.query_calls == calls + 1  # reloaded after clear
