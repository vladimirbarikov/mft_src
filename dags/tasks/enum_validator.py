# pylint: disable=too-many-lines
# pylint: disable=line-too-long
# pylint: disable=wrong-import-position
"""
Universal ENUM Validation Module for Material Flow Table Database.

This module provides comprehensive ENUM validation functionality for the ETL pipeline,
serving as a critical data quality layer that ensures all ENUM values conform to
database constraints before loading. It is designed to be used in both MFT and BP
DAGs during the transformation phase.

Key Features:
    - Database-synchronized validation (ENUM values imported directly from database.py)
    - Config-driven column mapping (single source of truth:
      config.columns_config.ENUM_COLUMN_MAPPING, no hardcoded column names)
    - Simple function interface matching existing transformation functions
    - Automatic handling of NULL values, case variations, and whitespace
    - Comprehensive logging with invalid value sampling
    - Support for all ENUM types in the database schema
    - Support for BP pipeline columns (before/after variants, breakpoint status)

Architecture:
    The module follows a simple functional design pattern:
    1. ENUM Resolution: ENUM objects are resolved from database.py by name
       (getattr), ensuring schema synchronization; an unknown ENUM name
       produces an explicit startup error instead of a silent skip
    2. Column Mapping: _COLUMN_TO_ENUM is built from
       config.columns_config.ENUM_COLUMN_MAPPING, with keys registered
       in both UPPERCASE and lowercase
    3. Validation Logic: Core validation with cleaning, masking, and replacement
    4. Logging Layer: Detailed DEBUG/INFO/WARNING logging for monitoring

Configuration Source:
    ENUM types are resolved by name from database.py (via getattr), based on
    config.columns_config.ENUM_COLUMN_MAPPING:
        - LOCALIZATION_ENUM: Supplier localization status (yes/no/no data)
        - PACKAGING_TYPE_ENUM: Returnable/non-returnable packaging
        - BOM_PRODUCT_CODE_ENUM: Vehicle platform codes ('a01g-r-bom', 'a08-r-bom', 'b02-r-bom', etc.)
        - MODEL_NAMES_ENUM: Vehicle marketing names (jolion, h3, f7, etc.)
        - WORKSHOP_CODES_ENUM: Production workshop codes (as, comp, paint, etc.)
        - WORKSHOP_NAMES_ENUM: Full workshop names (assembly, component, etc.)
        - CONFIGURATION_ENUM: Vehicle trim levels (comfort, elite, tech-plus, premium, s_version)
        - BREAKPOINT_STATUS_ENUM: Engineering change status types (approved, published, closed)

Column Mapping Support:
    The column-to-ENUM mapping is NOT hardcoded in this module. It is built
    at import time from config.columns_config.ENUM_COLUMN_MAPPING, the single
    source of truth for ENUM-backed columns in both pipelines (MFT and BP,
    including *_AFTER variants). Keys are registered in both UPPERCASE and
    lowercase, so validation works before and after columns_to_lowercase().
    Columns without a mapping are skipped with a DEBUG log entry. To add a
    new ENUM-backed column, update only ENUM_COLUMN_MAPPING in
    columns_config.py.
    
    MFT Pipeline:
        - LOCALIZATION, localization
        - BOX_TYPE, box_type, PALLET_TYPE, pallet_type
        - MODEL_CODE, model_code, MODEL_NAME, model_name
        - WORKSHOP_CODE, workshop_code, WORKSHOP_NAME, workshop_name
        - CONFIGURATION, configuration
    
    BP Pipeline:
        - localization_before, LOCALIZATION_BEFORE
        - localization_after, LOCALIZATION_AFTER
        - box_before, BOX_BEFORE, box_after, BOX_AFTER
        - pallet_before, PALLET_BEFORE, pallet_after, PALLET_AFTER
        - workshop_before, WORKSHOP_BEFORE, workshop_after, WORKSHOP_AFTER
        - bom_product, BOM_PRODUCT
        - breakpoint_status, STATUS, status

Dependencies:
    - Polars for DataFrame operations
    - SQLAlchemy for ENUM access (via database.py)
    - PostgreSQL 13+ as the target database

Usage Example:
    from dags.tasks.enum_validator import enum_validate, enum_validate_all

    # Single-column usage
    df = pl.DataFrame({"localization": ["yes", "no", "invalid", "YES", None]})
    validated_df = enum_validate(df, "localization")
    # Result: ["yes", "no", "no data", "yes", "no data"]

    # Whole-DataFrame usage (intended for DAG transform tasks):
    # validates every ENUM-backed column found in the DataFrame
    df = pl.DataFrame({
        "status": ["approved", "published", "invalid", "closed"],
        "workshop_code_after": ["as", "comp", "invalid", "paint"]
    })
    validated_df = enum_validate_all(df)
    # Invalid values replaced with 'no data'

Integration Notes:
    - Must be used AFTER convert_to_string() and basic_clean_text()
    - Can be used in both MFT and BP pipeline transformation phases
    - Use enum_validate_all(df) in DAG transform tasks to validate all
      ENUM-backed columns of a DataFrame in one call
    - No database connection required (ENUM definitions are resolved
      from database.py at import time)
    - Column names are matched in both UPPERCASE and lowercase
    - NULL and empty values are replaced with 'no data' (the ENUM fallback)
    - BP pipeline *_AFTER columns are supported via ENUM_COLUMN_MAPPING
      (before-variants are not extracted by the pipeline)

Performance Considerations:
    - Vectorized operations via Polars (no row-by-row loops)
    - Single pass per column with minimal temporary columns
    - Memory efficient with in-place updates where possible
    - Scales linearly to millions of rows

Error Handling:
    - Missing columns: Logs warning and returns DataFrame unchanged
    - No ENUM mapping: Logs debug and skips validation
    - Empty allowed values: Logs warning and skips validation
    - NULL values: Gracefully converted to empty strings
    - Invalid values: Replaced with 'no data', logged with samples

Version: 1.1.0
Compatibility: Python 3.14.4+, Polars 1.36.1
Maintainer: PLD Engineering Center
Created: 2026-03-18
Last Modified: 2026-11-25
License: MIT
Status: Production
"""
# Standard library imports
from pathlib import Path
import sys
from typing import List

# Third-party imports
import polars as pl

# The relative path to the root project directory
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Add the project path to sys.path
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Local imports
from config import get_logger
from config.columns_config import ENUM_COLUMN_MAPPING
import database.database as db_models

# Logger setup
logger = get_logger(__name__)


# Column-to-ENUM mapping, built from columns_config.ENUM_COLUMN_MAPPING
# (single source of truth). Keys are registered in both original and
# lowercase form, because transform tasks run after columns_to_lowercase().
_COLUMN_TO_ENUM: dict = {}
for _col_name, _enum_name in ENUM_COLUMN_MAPPING.items():
    try:
        _enum_obj = getattr(db_models, _enum_name)
    except AttributeError:
        logger.error(
            "ENUM '%s' mapped for column '%s' not found in database.py; "
            "fix ENUM_COLUMN_MAPPING in columns_config.py",
            _enum_name, _col_name
        )
        continue
    _COLUMN_TO_ENUM[_col_name] = _enum_obj
    _COLUMN_TO_ENUM[_col_name.lower()] = _enum_obj


def _get_enum_values(enum_obj) -> List[str]:
    """
    Extract allowed values from SQLAlchemy Enum object.
    
    Args:
        enum_obj: SQLAlchemy Enum object from database.py
        
    Returns:
        List of allowed string values
    """
    if hasattr(enum_obj, 'enums'):
        # For SQLAlchemy Enum
        return list(enum_obj.enums)
    elif hasattr(enum_obj, 'values'):
        # Alternative access method
        return list(enum_obj.values)
    else:
        logger.error("Could not extract values from enum: %s", enum_obj)
        return []


def enum_validate(df: pl.DataFrame, column_name: str) -> pl.DataFrame:
    """
    Validate a column against its corresponding ENUM type.

    This function automatically detects the appropriate ENUM type based on
    the column name and validates all values in the column. Invalid values
    are replaced with 'no data'.

    Args:
        df: Polars DataFrame
        column_name: Name of column to validate (e.g., 'LOCALIZATION', 'BOX_TYPE')

    Returns:
        DataFrame with validated column

    Example:
        >>> import polars as pl
        >>> from dags.tasks.enum_validator import enum_validate
        >>> 
        >>> df = pl.DataFrame({
        ...     "LOCALIZATION": ["yes", "no", "invalid", "YES", None],
        ...     "OTHER_COL": [1, 2, 3, 4, 5]
        ... })
        >>> 
        >>> # Simple usage - just like convert_to_string()
        >>> validated_df = enum_validate(df, "LOCALIZATION")
        >>> 
        >>> print(validated_df)
        shape: (5, 2)
        ┌──────────────┬───────────┐
        │ LOCALIZATION ┆ OTHER_COL │
        │ ---          ┆ ---       │
        │ str          ┆ i64       │
        ╞══════════════╪═══════════╡
        │ yes          ┆ 1         │
        │ no           ┆ 2         │
        │ no data      ┆ 3         │
        │ yes          ┆ 4         │
        │ no data      ┆ 5         │
        └──────────────┴───────────┘
    """
    # Check if column exists
    if column_name not in df.columns:
        logger.warning("Column '%s' not found in DataFrame", column_name)
        return df

    # Get the appropriate ENUM for this column
    enum_obj = _COLUMN_TO_ENUM.get(column_name)

    if enum_obj is None:
        logger.debug(
            "No ENUM mapping found for column '%s', skipping validation",
            column_name
        )
        return df

    # Get allowed values from the ENUM
    allowed_values = _get_enum_values(enum_obj)

    if not allowed_values:
        logger.warning("No allowed values found for column '%s'", column_name)
        return df

    # Create a temporary column with cleaned values
    # Handle null values by converting to string first
    temp_col = f"__temp_{column_name}"
    df = df.with_columns(
        pl.when(pl.col(column_name).is_null())
        .then(pl.lit(""))
        .otherwise(pl.col(column_name))
        .cast(pl.Utf8)
        .str.strip_chars()
        .str.to_lowercase()
        .alias(temp_col)
    )

    # Find invalid values (empty string or not in allowed values)
    invalid_mask = (
        (pl.col(temp_col) == "") |
        (~pl.col(temp_col).is_in(allowed_values))
    )
    invalid_count = df.filter(invalid_mask).height

    if invalid_count > 0:
        # Get sample of invalid values for logging
        invalid_samples = (
            df.filter(invalid_mask & (pl.col(temp_col) != ""))
            .select(temp_col)
            .unique()
            .head(5)
            .to_series()
            .to_list()
        )

        logger.warning(
            "Found %d invalid value(s) in column '%s'. "
            "Allowed values: %s. Sample: %s",
            invalid_count, column_name, allowed_values, invalid_samples
        )

        # Replace invalid values with 'no data'
        df = df.with_columns(
            pl.when(invalid_mask)
            .then(pl.lit('no data'))
            .otherwise(pl.col(temp_col))
            .alias(column_name)
        )
    else:
        # All values are valid, use cleaned values
        df = df.with_columns(
            pl.col(temp_col).alias(column_name)
        )

    # Remove temporary column
    df = df.drop(temp_col)

    return df


def enum_validate_all(df: pl.DataFrame) -> pl.DataFrame:
    """
    Validate all ENUM-backed columns present in the DataFrame.

    Iterates over the mapping from columns_config.ENUM_COLUMN_MAPPING and
    applies enum_validate() to every mapped column found in the DataFrame.
    Designed as a single call in DAG transform tasks, after text cleaning.

    Args:
        df: Polars DataFrame (column names already lowercased)

    Returns:
        DataFrame with all ENUM columns validated
    """
    validated = 0
    for col in df.columns:
        if col in _COLUMN_TO_ENUM:
            df = enum_validate(df, col)
            validated += 1

    logger.debug("ENUM validation applied to %d column(s)", validated)
    return df
