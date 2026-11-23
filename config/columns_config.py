# pylint: disable=too-many-lines
# pylint: disable=line-too-long
# pylint: disable=wrong-import-position
"""
Column configuration for Material Flow Table Database.

This module defines all required column names for extracting and transforming
manufacturing data from Excel files. These constants are used throughout the
ETL pipeline to ensure consistent column naming across tasks.

PIPELINE OVERVIEW:
    - MFT pipeline: static master data (suppliers, parts, boxes, pallets,
      models, configurations, transmissions, colors, workshops, lines)
      and their junction tables.
    - BP pipeline: dynamic data (breakpoints, parts before/after, junctions)
      supporting ADD / DELETE / UPDATE / REPLACE actions.

COLUMN LIST CONVENTIONS:
    - ``*_COLS``          — columns actually extracted and used by the pipeline.
    - ``*_IGNORED_COLS``  — columns present in the Excel file but NOT extracted
                            (calculated in DB, resolved via relationships, or
                            duplicated). Kept here for documentation and for
                            validating "unknown column" warnings.
    - Loaders/mappers MUST read only ``*_COLS`` lists.

CORE ENTITY TABLES COLUMNS (UPPERCASE for Excel extraction):

    SUPPLIER_COLS: Columns for supplier entity table
        - SUPPLIER_NAME, LOCATION, CITY, STREET, BUILDING,
          LATITUDE, LONGITUDE, LOCALIZATION

    PART_COLS: Columns for part entity table
        - PART_NUMBER, PART_NAME, PART_WEIGHT_KG, SUPPLIER_NAME

    BOX_COLS: Columns for box entity table (with dimensions)
        - BOX_TYPE, BOX_WEIGHT_KG, BOX_LENGTH_MM, BOX_WIDTH_MM,
          BOX_HEIGHT_MM, BOX_STACKING

    PALLET_COLS: Columns for pallet entity table (with dimensions)
        - PALLET_TYPE, PALLET_WEIGHT_KG, PALLET_LENGTH_MM, PALLET_WIDTH_MM,
          PALLET_HEIGHT_MM, PALLET_STACKING

    MODEL_COLS: Columns for model entity table
        - BOM_PRODUCT_CODE (maps to ModelData.bom_product_code),
          MODEL_CODE (maps to ModelData.model_code),
          MODEL_NAME

    CONFIGURATION_COLS: Columns for configuration entity table
        - CONFIGURATION

    TRANSMISSION_COLS: Columns for transmission entity table
        - TRANSMISSION (maps to TransmissionData.transmission)

    COLOR_COLS: Columns for color entity table
        - COLOR_CODE, COLOR_NAME

    WORKSHOP_COLS: Columns for workshop entity table
        - WORKSHOP_CODE, WORKSHOP_NAME

    LINE_COLS: Columns for production line entity table
        - LINE_CODE, LINE_NAME, WORKSHOP_CODE

    BREAKPOINT_COLS: Columns for breakpoint entity table (used by pipeline)
        - BP_NO, STATUS, BATCH_PLAN, BATCH_FACT, BATCH_FEEDBACK,
          CHANGE_DATE, BOM_PRODUCT_CODE, DESCRIPTION, SOLUTION, COMMENTS

    BREAKPOINT_IGNORED_COLS: Breakpoint columns NOT extracted
        - NEW_PART_AVAILABLE_DATE, BOM_PRODUCT_NAME,
          CONFIGURATION_FOR_OLD_PARTS_USING_OUT,
          BATCHES_FOR_OLD_PARTS_USING_OUT, TRANSMISSION
          (calculated in DB / resolved via BatchData / duplicated in
          PART_BEFORE_COLS)

    PART_BEFORE_COLS (old parts, used by pipeline):
        - PART_NO_BEFORE, CONFIGURATION,
          QUANTITY_PARTS_IN_SS, QUANTITY_BATCHES_IN_SS,
          INTERCHANGEABLE, PRODUCTION_PART_DISPOSAL,
          BOX_LENGTH_BEFORE_MM, BOX_WIDTH_BEFORE_MM, BOX_HEIGHT_BEFORE_MM,
          PALLET_LENGTH_BEFORE_MM, PALLET_WIDTH_BEFORE_MM,
          PALLET_HEIGHT_BEFORE_MM,
          SUPPLIER_NAME_BEFORE,
          SUPPLIER_LATITUDE_BEFORE, SUPPLIER_LONGITUDE_BEFORE

    PART_BEFORE_IGNORED_COLS: Parts-before columns NOT extracted
        - PART_NAME_BEFORE, PART_NET_WEIGHT_BEFORE_KG,
          QUANTITY_PER_VEHICLE_BEFORE, WORKCENTER_CODE_BEFORE,
          WORKCENTER_NAME_BEFORE, WORKSHOP_CODE_BEFORE, WORKSHOP_NAME_BEFORE,
          QUANTITY_PER_BOX_BEFORE, BOX_TYPE_BEFORE,
          BOX_AREA_BEFORE_M2, BOX_VOLUME_BEFORE_M3,
          BOX_NET_WEIGHT_BEFORE_KG, BOX_STACKING_BEFORE_UNITS,
          BOXES_PER_PALLET_BEFORE_UNITS, PALLET_TYPE_BEFORE,
          PALLET_AREA_BEFORE_M2, PALLET_VOLUME_BEFORE_M3,
          PALLET_GROSS_WEIGHT_BEFORE_KG, PALLET_STACKING_BEFORE_UNITS,
          SUPPLIER_LOCATION_BEFORE, SUPPLIER_CITY_BEFORE,
          SUPPLIER_STREET_BEFORE, SUPPLIER_BUILDING_BEFORE,
          LOCALIZATION_BEFORE, COLOR_CODE, COLOR_NAME

    PART_AFTER_COLS (new parts, used by pipeline):
        - PART_NO_AFTER, PART_NAME_AFTER, PART_NET_WEIGHT_AFTER_KG,
          QUANTITY_PER_VEHICLE_AFTER,
          WORKCENTER_CODE_AFTER, WORKCENTER_NAME_AFTER,
          WORKSHOP_CODE_AFTER, WORKSHOP_NAME_AFTER,
          QUANTITY_PER_BOX_AFTER,
          BOX_TYPE_AFTER, BOX_LENGTH_AFTER_MM, BOX_WIDTH_AFTER_MM,
          BOX_HEIGHT_AFTER_MM, BOX_NET_WEIGHT_AFTER_KG,
          BOX_STACKING_AFTER_UNITS, BOXES_PER_PALLET_AFTER_UNITS,
          PALLET_TYPE_AFTER, PALLET_LENGTH_AFTER_MM, PALLET_WIDTH_AFTER_MM,
          PALLET_HEIGHT_AFTER_MM, PALLET_GROSS_WEIGHT_AFTER_KG,
          PALLET_STACKING_AFTER_UNITS,
          SUPPLIER_NAME_AFTER, SUPPLIER_LOCATION_AFTER,
          SUPPLIER_CITY_AFTER, SUPPLIER_STREET_AFTER,
          SUPPLIER_BUILDING_AFTER,
          SUPPLIER_LATITUDE_AFTER, SUPPLIER_LONGITUDE_AFTER,
          LOCALIZATION_AFTER, COLOR_CODE, COLOR_NAME

    PART_AFTER_IGNORED_COLS: Parts-after columns NOT extracted
        - BOX_AREA_AFTER_M2, BOX_VOLUME_AFTER_M3,
          PALLET_AREA_AFTER_M2, PALLET_VOLUME_AFTER_M3
          (calculated in DB)

JUNCTION TABLES COLUMNS (UPPERCASE for Excel extraction):

    PART_TO_BOX_COMPOSITE_COLS: Part-to-box junction (composite key)
        - PART_NUMBER, BOX_TYPE, BOX_LENGTH_MM, BOX_WIDTH_MM,
          BOX_HEIGHT_MM, PART_PER_BOX

    BOX_TO_PALLET_COMPOSITE_COLS: Box-to-pallet junction (composite key)
        - PART_NUMBER, BOX_TYPE, BOX_LENGTH_MM, BOX_WIDTH_MM, BOX_HEIGHT_MM,
          PALLET_TYPE, PALLET_LENGTH_MM, PALLET_WIDTH_MM, PALLET_HEIGHT_MM,
          BOX_PER_PALLET

    PART_TO_MODEL_COLS: Part-to-model junction
        - PART_NUMBER, MODEL_CODE, CONFIGURATION, PART_PER_VEHICLE

    PART_TO_LINE_COLS: Part-to-line junction
        - PART_NUMBER, LINE_CODE

    PART_TO_COLOR_COLS: Part-to-color junction (M:N)
        - PART_NUMBER, COLOR_CODE

    CONFIGURATION_TO_TRANSMISSION_COLS: Configuration-to-transmission
    allow-list (M:N)
        - CONFIGURATION, TRANSMISSION

    PART_TO_BREAKPOINT_COLS: Part-to-breakpoint junction (change history)
        - PART_NO_BEFORE, PART_NO_AFTER, BP_NO, BOM_PRODUCT_CODE,
          CONFIGURATION
        (other attributes such as INTERCHANGEABLE, PRODUCTION_PART_DISPOSAL,
        QUANTITY_PARTS_IN_SS, QUANTITY_BATCHES_IN_SS are read from
        PART_BEFORE_COLS / PART_AFTER_COLS by the mapper)

MFT PIPELINE CONFIGURATION (for mft_dag.py, mft_mapper.py, mft_loader.py)

    MFT_COMPOSITE_COLUMNS: Composite key types requiring special handling
        - 'box_composite', 'pallet_composite'

    MFT_JUNCTION_REQUIRED: Required columns for MFT pipeline junction tables
        - part_to_box_composite: part_number, box_type, box_length_mm,
          box_width_mm, box_height_mm
        - box_to_pallet_composite: part_number, box_type, box_length_mm,
          box_width_mm, box_height_mm, pallet_type, pallet_length_mm,
          pallet_width_mm, pallet_height_mm
        - part_to_model: part_number, model_code, configuration
        - part_to_line: part_number, line_code
        - part_to_color: part_number, color_code
        - configuration_to_transmission: configuration, transmission

    MFT_JUNCTION_OPTIONAL: Optional columns for MFT pipeline junction tables
        - part_to_box_composite: part_per_box
        - box_to_pallet_composite: box_per_pallet
        - part_to_model: part_per_vehicle
        - part_to_line: (none)
        - part_to_color: (none)
        - configuration_to_transmission: (none)

    MFT_TABLE_REQUIREMENTS: Required columns for MFT pipeline core tables
        - supplier_data, part_data, box_data, pallet_data, model_data,
          workshop_data, line_data, configuration_data, transmission_data,
          color_data

BP PIPELINE CONFIGURATION (for bp_dag.py, bp_mapper.py, bp_loader.py)

    BP_JUNCTION_REQUIRED: Required columns for breakpoint junction table
        - part_to_breakpoint: part_no_before, part_no_after, bp_no,
          bom_product_code, configuration

    BP_JUNCTION_OPTIONAL: Optional columns for breakpoint junction table
        - part_to_breakpoint: interchangeable, production_part_disposal,
          quantity_parts_in_ss, quantity_batches_in_ss

    BP_TABLE_REQUIREMENTS: Required columns for BP pipeline core tables
        - breakpoint_data, part_data_before, part_data_after

    BP_ACTION_TYPES: Action types for breakpoint changes
        - ADD: new_part_id NOT NULL, old_part_id NULL
        - DELETE: new_part_id NULL, old_part_id NOT NULL
        - UPDATE: new_part_id = old_part_id (same part)
        - REPLACE: Two records (DELETE old + ADD new) in same breakpoint

    BP_REQUIRED_FIELDS_BY_ACTION: Required fields for each action type
        (logical field names; mapper assembles them from PART_BEFORE_COLS
        and PART_AFTER_COLS)
        - ADD, DELETE, UPDATE, REPLACE

CHANGE CLASSIFICATION CONSTANTS

    CHANGE_DOMAINS: Change domains
        - supplier, packaging, production, spec, config, color, multi

    CHANGE_NATURES: Change natures
        - business, technical, correction

    FIELD_TO_DOMAIN: Maps field names to change domains (used by classifier)

DATABASE MODEL MAPPING (MFT PIPELINE):

    Core Entity Tables:
        supplier_data        ←→ SUPPLIER_COLS
        part_data            ←→ PART_COLS
        box_data             ←→ BOX_COLS
        pallet_data          ←→ PALLET_COLS
        model_data           ←→ MODEL_COLS
        configuration_data   ←→ CONFIGURATION_COLS
        transmission_data    ←→ TRANSMISSION_COLS
        color_data           ←→ COLOR_COLS
        workshop_data        ←→ WORKSHOP_COLS
        line_data            ←→ LINE_COLS

    Junction Tables:
        part_to_box                   ←→ Used only in MFT pipeline
        box_to_pallet                 ←→ Used only in MFT pipeline
        part_to_model                 ←→ Used only in MFT pipeline
        part_to_line                  ←→ Used only in MFT pipeline
        part_to_color                 ←→ Used only in MFT pipeline
        configuration_to_transmission ←→ Used only in MFT pipeline

DATABASE MODEL MAPPING (BREAKPOINT PIPELINE):

    Core Entity Tables:
        breakpoint_data      ←→ BREAKPOINT_COLS
        parts_before_data    ←→ PART_BEFORE_COLS
        parts_after_data     ←→ PART_AFTER_COLS

    Junction Tables:
        part_to_breakpoint   ←→ Used only in BP pipeline

ARCHITECTURE NOTES:

    MFT Pipeline (ETL Pattern):
        - Static data loading (suppliers, parts, boxes, pallets, models,
          configurations, transmissions, colors, workshops, lines)
        - Core tables are pre-loaded, junction tables only link existing records
        - No creation of new records in core tables
        - Mapper performs only ID lookups, no business logic
        - Loader handles INSERT with ON CONFLICT DO NOTHING
        - Transmission is an INDEPENDENT vehicle dimension (not an attribute
          of ConfigurationData); allowed combinations live in
          configuration_to_transmission
        - Color is an INDEPENDENT dimension linked to PartData via M:N
          (part_to_color)

    BP Pipeline (ETL Pattern):
        - Dynamic data loading (breakpoints, parts before/after, junctions)
        - Core tables may be created or updated during pipeline execution
        - Supports four action types: ADD, DELETE, UPDATE, REPLACE
        - Mapper determines action type based on presence of before/after data
        - Mapper performs ID lookups and creates new records when needed
        - Loader handles INSERT, UPDATE, and soft DELETE operations
        - Versioning: Each part change creates new version in part_data
        - Soft deactivation: Parts are deactivated via is_active=False
          in PartToModel
        - Junction table part_to_breakpoint links old and new part versions
        - Box and pallet records are looked up or created as needed
        - All ID lookups use business keys (part_number, supplier_name, etc.)
        - ENUM validation handled by enum_validator.py module
        - Cascade: Breakpoint deactivation triggers part deactivation
          via FK relationships
        - INTERCHANGEABLE, PRODUCTION_PART_DISPOSAL, QUANTITY_PARTS_IN_SS,
          QUANTITY_BATCHES_IN_SS are attributes of PartToBreakpoint;
          INTERCHANGEABLE is a String (not Boolean) to allow new statuses
          without schema migration

Version: 2.0.0
Compatibility: Python 3.14.4
Maintainer: PLD Engineering Center
Created: 2026-02-16
Last Modified: 2026-11-23
License: MIT
Status: Production
"""
# ========== MFT PIPELINE CONFIGURATION =================
# For use in mft_dag.py, mft_mapper.py, and mft_loader.py
# =======================================================

# ========== CORE ENTITY TABLES COLUMNS (UPPERCASE for Excel extraction) ==========
# Supplier entity columns
SUPPLIER_COLS: list[str] = [
    'SUPPLIER_NAME',
    'LOCATION',
    'CITY',
    'STREET',
    'BUILDING',
    'LATITUDE',
    'LONGITUDE',
    'LOCALIZATION',
]

# Part entity columns
PART_COLS: list[str] = [
    'PART_NUMBER',
    'PART_NAME',
    'PART_WEIGHT_KG',
    'SUPPLIER_NAME'
]

# Color entity columns
COLOR_COLS: list[str] = [
    'COLOR_CODE',
    'COLOR_NAME',
]

# Box entity columns (with dimensional composite key)
BOX_COLS: list[str] = [
    'BOX_TYPE',
    'BOX_WEIGHT_KG',
    'BOX_LENGTH_MM',
    'BOX_WIDTH_MM',
    'BOX_HEIGHT_MM',
    'BOX_STACKING',
]

# Pallet entity columns (with dimensional composite key)
PALLET_COLS: list[str] = [
    'PALLET_TYPE',
    'PALLET_WEIGHT_KG',
    'PALLET_LENGTH_MM',
    'PALLET_WIDTH_MM',
    'PALLET_HEIGHT_MM',
    'PALLET_STACKING',
]

# Model entity columns
MODEL_COLS: list[str] = [
    'BOM_PRODUCT_CODE',
    'MODEL_CODE',
    'MODEL_NAME',
]

# Configuration entity columns
CONFIGURATION_COLS: list[str] = [
    'CONFIGURATION',
]

# Transmission entity columns
TRANSMISSION_COLS: list[str] = [
    'TRANSMISSION',
]

# Workshop entity columns
WORKSHOP_COLS: list[str] = [
    'WORKSHOP_CODE',
    'WORKSHOP_NAME',
]

# Production line entity columns
LINE_COLS: list[str] = [
    'LINE_CODE',
    'LINE_NAME',
    'WORKSHOP_CODE',
]

# ========== JUNCTION TABLES COLUMNS (UPPERCASE for Excel extraction) ==========
# Part-to-Box junction columns (composite key includes box dimensions)
PART_TO_BOX_COMPOSITE_COLS: list[str] = [
    'PART_NUMBER',
    'BOX_TYPE',
    'BOX_LENGTH_MM',
    'BOX_WIDTH_MM',
    'BOX_HEIGHT_MM',
    'PART_PER_BOX',
]

# Part-to-Color junction columns (M:N)
PART_TO_COLOR_COLS: list[str] = [
    'PART_NUMBER',
    'COLOR_CODE',
]

# Box-to-Pallet junction columns (composite key includes both box and pallet dimensions)
BOX_TO_PALLET_COMPOSITE_COLS: list[str] = [
    'PART_NUMBER',
    'BOX_TYPE',
    'BOX_LENGTH_MM',
    'BOX_WIDTH_MM',
    'BOX_HEIGHT_MM',
    'PALLET_TYPE',
    'PALLET_LENGTH_MM',
    'PALLET_WIDTH_MM',
    'PALLET_HEIGHT_MM',
    'BOX_PER_PALLET',
]

# Part-to-Model junction columns
PART_TO_MODEL_COLS: list[str] = [
    'PART_NUMBER',
    'MODEL_CODE',
    'CONFIGURATION',
    'PART_PER_VEHICLE',
]

# Part-to-Line junction columns
PART_TO_LINE_COLS: list[str] = [
    'PART_NUMBER',
    'LINE_CODE',
]

# Configuration-to-Transmission junction columns (allow-list M:N)
CONFIGURATION_TO_TRANSMISSION_COLS: list[str] = [
    'CONFIGURATION',
    'TRANSMISSION',
]

# Special composite key columns that need custom handling
MFT_COMPOSITE_COLUMNS: set[str] = {'box_composite', 'pallet_composite'}

# Required columns for each junction table type (in lowercase for mapper)
MFT_JUNCTION_REQUIRED: dict[str, list[str]] = {
    'part_to_box_composite': [
        'part_number',
        'box_type',
        'box_length_mm',
        'box_width_mm',
        'box_height_mm'
    ],
    'box_to_pallet_composite': [
        'part_number',
        'box_type',
        'box_length_mm',
        'box_width_mm',
        'box_height_mm',
        'pallet_type',
        'pallet_length_mm',
        'pallet_width_mm',
        'pallet_height_mm'
    ],
    'part_to_model': [
        'part_number',
        'model_code',
        'configuration'
    ],
    'part_to_line': [
        'part_number',
        'line_code'
    ],
    'part_to_color': [
        'part_number',
        'color_code'
    ],
    'configuration_to_transmission': [
        'configuration',
        'transmission'
    ],
}

# Optional columns for each junction table type (in lowercase for mapper)
MFT_JUNCTION_OPTIONAL: dict[str, list[str]] = {
    'part_to_box_composite': ['part_per_box'],
    'box_to_pallet_composite': ['box_per_pallet'],
    'part_to_model': ['part_per_vehicle'],
    'part_to_line': [],
    'part_to_color': [],
    'configuration_to_transmission': [],
}

# Expected columns for each core entity table type (in lowercase for loader)
MFT_TABLE_REQUIREMENTS: dict[str, list[str]] = {
    'supplier_data': [
        'supplier_name',
        'location',
        'city',
        'street',
        'building',
        'latitude',
        'longitude',
        'localization'
    ],
    'part_data': [
        'part_number',
        'part_name',
        'part_weight_kg',
        'supplier_id'
    ],
    'box_data': [
        'box_type',
        'box_weight_kg',
        'box_length_mm',
        'box_width_mm',
        'box_height_mm',
        'box_stacking'
    ],
    'pallet_data': [
        'pallet_type',
        'pallet_weight_kg',
        'pallet_length_mm',
        'pallet_width_mm',
        'pallet_height_mm',
        'pallet_stacking'
    ],
    'model_data': [
        'bom_product_code',
        'model_code',
        'model_name'
    ],
    'workshop_data': [
        'workshop_code',
        'workshop_name'
    ],
    'line_data': [
        'line_code',
        'line_name',
        'workshop_id'
    ],
    'configuration_data': [
        'configuration'
    ],
    'transmission_data': [
        'transmission'
    ],
    'color_data': [
        'color_code',
        'color_name'
    ],
}

# ========== BP PIPELINE CONFIGURATION ==============
# For use in bp_dag.py, bp_mapper.py and bp_loader.py
# ===================================================

# ========== CORE ENTITY TABLES COLUMNS (UPPERCASE for Excel extraction) ==========
# Breakpoint entity columns (used by pipeline)
BREAKPOINT_COLS: list[str] = [
    'BP_NO',
    'STATUS',
    'BATCH_PLAN',
    'BATCH_FACT',
    'BATCH_FEEDBACK',
    'CHANGE_DATE',
    'BOM_PRODUCT_CODE',
    'DESCRIPTION',
    'SOLUTION',
    'COMMENTS',
]

# Breakpoint columns present in Excel but NOT extracted by the pipeline
# (calculated in DB, resolved via relationships, or not stored in schema)
BREAKPOINT_IGNORED_COLS: list[str] = [
    'NEW_PART_AVAILABLE_DATE',
    'BOM_PRODUCT_NAME',
    'CONFIGURATION_FOR_OLD_PARTS_USING_OUT',
    'BATCHES_FOR_OLD_PARTS_USING_OUT',
    'TRANSMISSION',
]

# Parts before (old parts) entity columns (used by pipeline)
PART_BEFORE_COLS: list[str] = [
    'PART_NO_BEFORE',
    'CONFIGURATION',
    'QUANTITY_PARTS_IN_SS',
    'QUANTITY_BATCHES_IN_SS',
    'INTERCHANGEABLE',
    'BOX_LENGTH_BEFORE_MM',
    'BOX_WIDTH_BEFORE_MM',
    'BOX_HEIGHT_BEFORE_MM',
    'PALLET_LENGTH_BEFORE_MM',
    'PALLET_WIDTH_BEFORE_MM',
    'PALLET_HEIGHT_BEFORE_MM',
    'PRODUCTION_PART_DISPOSAL',
    'SUPPLIER_NAME_BEFORE',
    'SUPPLIER_LATITUDE_BEFORE',
    'SUPPLIER_LONGITUDE_BEFORE',
]

# Parts-before columns present in Excel but NOT extracted by the pipeline
# (calculated in DB, resolved via relationships, or duplicated)
PART_BEFORE_IGNORED_COLS: list[str] = [
    'PART_NAME_BEFORE',
    'PART_NET_WEIGHT_BEFORE_KG',
    'QUANTITY_PER_VEHICLE_BEFORE',
    'WORKCENTER_CODE_BEFORE',
    'WORKCENTER_NAME_BEFORE',
    'WORKSHOP_CODE_BEFORE',
    'WORKSHOP_NAME_BEFORE',
    'QUANTITY_PER_BOX_BEFORE',
    'BOX_TYPE_BEFORE',
    'BOX_AREA_BEFORE_M2',
    'BOX_VOLUME_BEFORE_M3',
    'BOX_NET_WEIGHT_BEFORE_KG',
    'BOX_STACKING_BEFORE_UNITS',
    'BOXES_PER_PALLET_BEFORE_UNITS',
    'PALLET_TYPE_BEFORE',
    'PALLET_AREA_BEFORE_M2',
    'PALLET_VOLUME_BEFORE_M3',
    'PALLET_GROSS_WEIGHT_BEFORE_KG',
    'PALLET_STACKING_BEFORE_UNITS',
    'SUPPLIER_LOCATION_BEFORE',
    'SUPPLIER_CITY_BEFORE',
    'SUPPLIER_STREET_BEFORE',
    'SUPPLIER_BUILDING_BEFORE',
    'LOCALIZATION_BEFORE',
    'COLOR_CODE',
    'COLOR_NAME',
]

# Parts after (new parts) entity columns (used by pipeline)
PART_AFTER_COLS: list[str] = [
    'PART_NO_AFTER',
    'PART_NAME_AFTER',
    'PART_NET_WEIGHT_AFTER_KG',
    'QUANTITY_PER_VEHICLE_AFTER',
    'WORKCENTER_CODE_AFTER',
    'WORKCENTER_NAME_AFTER',
    'WORKSHOP_CODE_AFTER',
    'WORKSHOP_NAME_AFTER',
    'QUANTITY_PER_BOX_AFTER',
    'BOX_TYPE_AFTER',
    'BOX_LENGTH_AFTER_MM',
    'BOX_WIDTH_AFTER_MM',
    'BOX_HEIGHT_AFTER_MM',
    'BOX_NET_WEIGHT_AFTER_KG',
    'BOX_STACKING_AFTER_UNITS',
    'BOXES_PER_PALLET_AFTER_UNITS',
    'PALLET_TYPE_AFTER',
    'PALLET_LENGTH_AFTER_MM',
    'PALLET_WIDTH_AFTER_MM',
    'PALLET_HEIGHT_AFTER_MM',
    'PALLET_GROSS_WEIGHT_AFTER_KG',
    'PALLET_STACKING_AFTER_UNITS',
    'SUPPLIER_NAME_AFTER',
    'SUPPLIER_LOCATION_AFTER',
    'SUPPLIER_CITY_AFTER',
    'SUPPLIER_STREET_AFTER',
    'SUPPLIER_BUILDING_AFTER',
    'SUPPLIER_LATITUDE_AFTER',
    'SUPPLIER_LONGITUDE_AFTER',
    'LOCALIZATION_AFTER',
    'COLOR_CODE',
    'COLOR_NAME',
]

# Parts-after columns present in Excel but NOT extracted by the pipeline
# (calculated in DB from dimensions/weights)
PART_AFTER_IGNORED_COLS: list[str] = [
    'BOX_AREA_AFTER_M2',
    'BOX_VOLUME_AFTER_M3',
    'PALLET_AREA_AFTER_M2',
    'PALLET_VOLUME_AFTER_M3',
]

# ========== JUNCTION TABLES COLUMNS (UPPERCASE for Excel extraction) ==========
# Part-to-Breakpoints junction columns
PART_TO_BREAKPOINT_COLS: list[str] = [
    'PART_NO_BEFORE',               # old_part_id lookup
    'PART_NO_AFTER',                # new_part_id lookup
    'BP_NO',                        # breakpoint_id lookup
    'BOM_PRODUCT_CODE',             # model_id lookup
    'CONFIGURATION',                # configuration_id lookup
]

# ========== BP JUNCTION CONFIGURATION ==========
# Required columns for breakpoint junction table (in lowercase for mapper)
BP_JUNCTION_REQUIRED: dict[str, list[str]] = {
    'part_to_breakpoint': [
        'part_no_before',
        'part_no_after',
        'bp_no',
        'bom_product_code',
        'configuration',
    ]
}

# Optional columns for breakpoint junction table (in lowercase for mapper)
BP_JUNCTION_OPTIONAL: dict[str, list[str]] = {
    'part_to_breakpoint': [
        'interchangeable',
        'production_part_disposal',
        'quantity_parts_in_ss',
        'quantity_batches_in_ss',
    ]
}

# ========== BP TABLE REQUIREMENTS ==========
# Expected columns for each core entity table type (in lowercase for loader)
BP_TABLE_REQUIREMENTS: dict[str, list[str]] = {
    'breakpoint_data': [
        'breakpoint_number',
        'breakpoint_status',
        'batch_plan',
        'batch_fact',
        'batch_feedback',
        'breakpoint_date',
        'description',
        'solution',
        'comments',
    ],
    'part_data_before': [
        'part_number',
        'configuration',
        'quantity_parts_in_ss',
        'quantity_batches_in_ss',
        'interchangeable',
        'box_length_mm',
        'box_width_mm',
        'box_height_mm',
        'pallet_length_mm',
        'pallet_width_mm',
        'pallet_height_mm',
        'production_part_disposal',
        'supplier_name',
        'latitude',
        'longitude',
    ],
    'part_data_after': [
        'part_number',
        'part_name',
        'part_weight_kg',
        'part_per_vehicle',
        'line_code',
        'line_name',
        'workshop_code',
        'workshop_name',
        'part_per_box',
        'box_type',
        'box_length_mm',
        'box_width_mm',
        'box_height_mm',
        'box_weight_kg',
        'box_stacking',
        'box_per_pallet',
        'pallet_type',
        'pallet_length_mm',
        'pallet_width_mm',
        'pallet_height_mm',
        'pallet_weight_kg',
        'pallet_stacking',
        'supplier_name',
        'location',
        'city',
        'street',
        'building',
        'latitude',
        'longitude',
        'localization',
        'color_code',
        'color_name',
    ]
}

# ========== BP ACTION TYPES ==========
# Action types for breakpoint changes
BP_ACTION_TYPES: dict[str, str] = {
    'ADD': 'add',           # new_part_id NOT NULL, old_part_id NULL
    'DELETE': 'delete',     # new_part_id NULL, old_part_id NOT NULL
    'UPDATE': 'update',     # new_part_id = old_part_id (same part)
    'REPLACE': 'replace'    # Two records (DELETE old + ADD new) in same breakpoint
}

# ========== BP REQUIRED FIELDS BY ACTION ==========
# Required fields for each action type
BP_REQUIRED_FIELDS_BY_ACTION: dict[str, list[str]] = {
    'ADD': [
        'part_no_after',
        'part_name_after',
        'bom_product_code',
        'configuration',
        'workshop_after',
        'workcenter_no_after',
        'workcenter_name_after',
        'supplier_name_after',
        'localization_after',
        'box_after',
        'pallet_after',
        'box_per_pallet_after',
    ],
    'DELETE': [
        'part_no_before',
        'part_name_before',
        'bom_product_code',
        'configuration',
        'workshop_before',
        'workcenter_no_before',
        'workcenter_name_before',
        'supplier_name_before',
        'localization_before',
        'box_before',
        'pallet_before',
        'box_per_pallet_before',
    ],
    'UPDATE': [
        'part_no_before',
        'part_no_after',
        'part_name_before',
        'part_name_after',
        'bom_product_code',
        'configuration',
        'workshop_before',
        'workshop_after',
        'workcenter_no_before',
        'workcenter_no_after',
        'workcenter_name_before',
        'workcenter_name_after',
        'supplier_name_before',
        'supplier_name_after',
        'localization_before',
        'localization_after',
        'box_before',
        'box_after',
        'pallet_before',
        'pallet_after',
        'box_per_pallet_before',
        'box_per_pallet_after',
    ],
    'REPLACE': [
        'part_no_before',
        'part_no_after',
        'part_name_before',
        'part_name_after',
        'bom_product_code',
        'configuration',
        'workshop_before',
        'workshop_after',
        'workcenter_no_before',
        'workcenter_no_after',
        'workcenter_name_before',
        'workcenter_name_after',
        'supplier_name_before',
        'supplier_name_after',
        'localization_before',
        'localization_after',
        'box_before',
        'box_after',
        'pallet_before',
        'pallet_after',
        'box_per_pallet_before',
        'box_per_pallet_after',
    ],
}

# ============================================================================
# CHANGE CLASSIFICATION CONSTANTS
# ============================================================================

# Change Domains
CHANGE_DOMAINS: dict[str, str] = {
    'SUPPLIER': 'supplier',
    'PACKAGING': 'packaging',
    'PRODUCTION': 'production',
    'SPEC': 'spec',
    'CONFIG': 'config',
    'COLOR': 'color',
    'MULTI': 'multi',
}

# Change Natures
CHANGE_NATURES: dict[str, str] = {
    'BUSINESS': 'business',
    'TECHNICAL': 'technical',
    'CORRECTION': 'correction',
}

# Field to Domain mapping (used by classifier)
FIELD_TO_DOMAIN: dict[str, str] = {
    # Supplier
    'supplier_name': CHANGE_DOMAINS['SUPPLIER'],
    'localization': CHANGE_DOMAINS['SUPPLIER'],
    'latitude': CHANGE_DOMAINS['SUPPLIER'],
    'longitude': CHANGE_DOMAINS['SUPPLIER'],
    'location': CHANGE_DOMAINS['SUPPLIER'],
    'city': CHANGE_DOMAINS['SUPPLIER'],
    'street': CHANGE_DOMAINS['SUPPLIER'],
    'building': CHANGE_DOMAINS['SUPPLIER'],

    # Packaging
    'box_type': CHANGE_DOMAINS['PACKAGING'],
    'box_length_mm': CHANGE_DOMAINS['PACKAGING'],
    'box_width_mm': CHANGE_DOMAINS['PACKAGING'],
    'box_height_mm': CHANGE_DOMAINS['PACKAGING'],
    'box_weight_kg': CHANGE_DOMAINS['PACKAGING'],
    'box_stacking': CHANGE_DOMAINS['PACKAGING'],
    'pallet_type': CHANGE_DOMAINS['PACKAGING'],
    'pallet_length_mm': CHANGE_DOMAINS['PACKAGING'],
    'pallet_width_mm': CHANGE_DOMAINS['PACKAGING'],
    'pallet_height_mm': CHANGE_DOMAINS['PACKAGING'],
    'pallet_weight_kg': CHANGE_DOMAINS['PACKAGING'],
    'pallet_stacking': CHANGE_DOMAINS['PACKAGING'],
    'box_per_pallet': CHANGE_DOMAINS['PACKAGING'],
    'part_per_box': CHANGE_DOMAINS['PACKAGING'],

    # Production
    'line_code': CHANGE_DOMAINS['PRODUCTION'],
    'line_name': CHANGE_DOMAINS['PRODUCTION'],
    'workshop_code': CHANGE_DOMAINS['PRODUCTION'],
    'workshop_name': CHANGE_DOMAINS['PRODUCTION'],
    'production_part_disposal': CHANGE_DOMAINS['PRODUCTION'],

    # Specification
    'part_name': CHANGE_DOMAINS['SPEC'],
    'part_weight_kg': CHANGE_DOMAINS['SPEC'],
    'interchangeable': CHANGE_DOMAINS['SPEC'],

    # Configuration
    'configuration': CHANGE_DOMAINS['CONFIG'],
    'transmission': CHANGE_DOMAINS['CONFIG'],
    'part_per_vehicle': CHANGE_DOMAINS['CONFIG'],

    # Color
    'color_code': CHANGE_DOMAINS['COLOR'],
    'color_name': CHANGE_DOMAINS['COLOR'],
}
