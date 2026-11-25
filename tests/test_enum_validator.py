# pylint: disable=wrong-import-position
"""
Unit tests for dags/tasks/enum_validator.py.

Covers:
    - _COLUMN_TO_ENUM: mapping built from config.columns_config.ENUM_COLUMN_MAPPING
      with both UPPERCASE and lowercase keys
    - enum_validate(): single-column ENUM validation
      (cleaning, invalid -> 'no data', NULL -> 'no data', edge cases)
    - enum_validate_all(): whole-DataFrame validation of all mapped columns

No database connection is required: ENUM definitions are imported from
database.py, and all validation runs on in-memory Polars DataFrames.

Run with: pytest tests/test_enum_validator.py --no-cov
"""
# Third-party imports
import polars as pl

# Local imports
from dags.tasks.enum_validator import (
    _COLUMN_TO_ENUM,
    enum_validate,
    enum_validate_all,
)


class TestColumnToEnumMapping:
    """Tests for the column-to-ENUM mapping built from columns_config."""

    def test_uppercase_and_lowercase_keys_registered(self):
        """Both UPPERCASE and lowercase keys must exist for each mapped column."""
        for col in ('LOCALIZATION', 'BOX_TYPE', 'PALLET_TYPE', 'CONFIGURATION',
                    'BOM_PRODUCT_CODE', 'MODEL_NAME', 'WORKSHOP_CODE',
                    'WORKSHOP_NAME', 'STATUS'):
            assert col in _COLUMN_TO_ENUM, f"Missing UPPERCASE key: {col}"
            assert col.lower() in _COLUMN_TO_ENUM, f"Missing lowercase key: {col}"

    def test_bp_after_variants_registered(self):
        """BP pipeline *_AFTER columns must be mapped."""
        for col in ('localization_after', 'box_type_after', 'pallet_type_after',
                    'workshop_code_after', 'workshop_name_after'):
            assert col in _COLUMN_TO_ENUM, f"Missing BP key: {col}"

    def test_enum_objects_have_values(self):
        """Every mapped ENUM object must expose a non-empty value list."""
        for col, enum_obj in _COLUMN_TO_ENUM.items():
            assert hasattr(enum_obj, 'enums'), f"No .enums attribute for {col}"
            assert len(enum_obj.enums) > 0, f"Empty ENUM values for {col}"


class TestEnumValidate:
    """Tests for enum_validate() — single-column validation."""

    def test_valid_values_pass_unchanged(self):
        """All valid values stay as-is (lowercased)."""
        df = pl.DataFrame({'localization': ['yes', 'no', 'no data']})
        result = enum_validate(df, 'localization')
        assert result['localization'].to_list() == ['yes', 'no', 'no data']

    def test_uppercase_and_whitespace_normalized(self):
        """Uppercase and padded values are cleaned, not replaced."""
        df = pl.DataFrame({'localization': ['  YES  ', 'No', 'NO DATA']})
        result = enum_validate(df, 'localization')
        assert result['localization'].to_list() == ['yes', 'no', 'no data']

    def test_invalid_values_replaced_with_no_data(self):
        """Garbage values are replaced with 'no data'."""
        df = pl.DataFrame({'localization': ['yes', 'local', 'yess', 'no']})
        result = enum_validate(df, 'localization')
        assert result['localization'].to_list() == ['yes', 'no data', 'no data', 'no']

    def test_none_becomes_no_data(self):
        """NULL values are replaced with 'no data' (documented behavior)."""
        df = pl.DataFrame({'localization': ['yes', None]})
        result = enum_validate(df, 'localization')
        assert result['localization'].to_list() == ['yes', 'no data']

    def test_empty_string_becomes_no_data(self):
        """Empty strings are treated as invalid and replaced."""
        df = pl.DataFrame({'localization': ['yes', '', 'no']})
        result = enum_validate(df, 'localization')
        assert result['localization'].to_list() == ['yes', 'no data', 'no']

    def test_hyphens_preserved(self):
        """Hyphenated ENUM values must survive validation ('a01g-r-bom')."""
        df = pl.DataFrame({'bom_product_code': ['A01G-R-BOM', 'b02-r-bom']})
        result = enum_validate(df, 'bom_product_code')
        assert result['bom_product_code'].to_list() == ['a01g-r-bom', 'b02-r-bom']

    def test_missing_column_returns_unchanged(self):
        """Missing column: warning is logged, DataFrame returned unchanged."""
        df = pl.DataFrame({'other_col': ['a', 'b']})
        result = enum_validate(df, 'localization')
        assert result.equals(df)

    def test_unmapped_column_returns_unchanged(self):
        """Column without ENUM mapping is skipped (no cleaning applied)."""
        df = pl.DataFrame({'part_number': ['  ABC-123  ', 'DEF']})
        result = enum_validate(df, 'part_number')
        assert result['part_number'].to_list() == ['  ABC-123  ', 'DEF']

    def test_other_columns_untouched(self):
        """Validation of one column must not affect the others."""
        df = pl.DataFrame({
            'localization': ['yes', 'invalid'],
            'part_name': ['Bracket', 'Cover'],
        })
        result = enum_validate(df, 'localization')
        assert result['part_name'].to_list() == ['Bracket', 'Cover']

    def test_temporary_column_removed(self):
        """The internal __temp_ column must not leak into the result."""
        df = pl.DataFrame({'localization': ['yes', 'invalid']})
        result = enum_validate(df, 'localization')
        assert '__temp_localization' not in result.columns
        assert result.columns == ['localization']

    def test_breakpoint_status_values(self):
        """STATUS column validated against BREAKPOINT_STATUS_ENUM."""
        df = pl.DataFrame({'status': ['approved', 'PUBLISHED', 'draft', 'closed']})
        result = enum_validate(df, 'status')
        assert result['status'].to_list() == ['approved', 'published', 'no data', 'closed']


class TestEnumValidateAll:
    """Tests for enum_validate_all() — whole-DataFrame validation."""

    def test_validates_multiple_enum_columns(self):
        """All mapped columns in the DataFrame are validated."""
        df = pl.DataFrame({
            'localization': ['yes', 'invalid'],
            'box_type': ['returnable', 'wooden'],
            'part_name': ['Bracket', 'Cover'],
        })
        result = enum_validate_all(df)
        assert result['localization'].to_list() == ['yes', 'no data']
        assert result['box_type'].to_list() == ['returnable', 'no data']
        assert result['part_name'].to_list() == ['Bracket', 'Cover']

    def test_skips_unmapped_columns(self):
        """DataFrame without mapped columns is returned unchanged."""
        df = pl.DataFrame({'part_number': ['ABC'], 'quantity': [5]})
        result = enum_validate_all(df)
        assert result.equals(df)

    def test_empty_dataframe_returns_unchanged(self):
        """Empty DataFrame with no columns passes through safely."""
        df = pl.DataFrame()
        result = enum_validate_all(df)
        assert result.is_empty()

    def test_bp_after_columns_validated(self):
        """BP pipeline *_AFTER columns are validated like regular ones."""
        df = pl.DataFrame({
            'localization_after': ['YES', 'unknown'],
            'workshop_code_after': ['AS', 'assembly'],
        })
        result = enum_validate_all(df)
        assert result['localization_after'].to_list() == ['yes', 'no data']
        # 'assembly' is a workshop NAME, not a CODE -> invalid for this column
        assert result['workshop_code_after'].to_list() == ['as', 'no data']
