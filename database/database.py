# pylint: disable=too-many-lines
# pylint: disable=line-too-long
# pylint: disable=wrong-import-position
"""
Database Models Module for Material Flow Table Database with SQLAlchemy ORM.

DATABASE ENUM TYPES, MODELS AND TABLES:
1. ENUM TYPES:
    - LOCALIZATION_ENUM:
        - yes/no - Local or foreign supplier.
        - no data - if no information about Localization status.
    - PACKAGING_TYPE_ENUM:
        - returnable/non-returnable - Packaging type.
        - no data - if no information about Packaging type.
    - BOM_PRODUCT_ENUM:
        - a01g-r-bom, a08-r-bom, b02-r-bom, b04-r-bom, b06-r-bom, b16-r-bom - BOM product codes.
        - no data - if no information about BOM product.
    - MODEL_NAMES_ENUM:
        - jolion, h3, f7, f7x, dargo, h7 - Model names.
        - no data - if no information about Model name.
    - WORKSHOP_CODES_ENUM:
        - as, comp, paint, weld, stamp, en, nb, tr, ch - Workshop codes.
        - no data - if no information about Workshop code.
    - WORKSHOP_NAMES_ENUM:
        - assembly, component, painting, welding, stamping, engine,
          nobo, transmission, chassis - Workshop names.
        - no data - if no information about Workshop name.
    - CONFIGURATION_ENUM:
        - comfort, elite, tech-plus, premium, s_version - Vehicle assembly levels.
        - no data - if no information about Configuration level.
    - BREAKPOINT_STATUS_ENUM:
        - approved, published, closed - Breakpoint execution statuses.
        - no data - if no information about status.

2. CORE ENTITY TABLES:
    - supplier_data              - Information about component suppliers
    - part_data                  - Data about automotive components (parts)
    - box_data                   - Packaging box specifications
    - pallet_data                - Pallet (platform) specifications
    - model_data                 - Vehicle models (bom_product + model_code)
    - configuration_data         - Vehicle configuration types (comfort, elite, etc.)
    - engine_data                - Engine specifications (GW4B15L, etc.)
    - transmission_data          - Transmission / drivetrain specifications (4x4, 4x2, etc.)
    - workshop_data              - Production workshops
    - line_data                  - Production lines
    - breakpoint_data            - Technical changes (breakpoints)
    - department_data            - Company departments
    - user_role_data             - Application-level roles (mapped to PostgreSQL roles)
    - user_data                  - Application user accounts
    - production_plan_data       - Production plan records (one row per Excel line)
    - production_plan_day_data   - Daily breakdown of a production plan record

3. JUNCTION TABLES:
    - part_to_box                - Parts ↔ Boxes (with quantity per box)
    - box_to_pallet              - Parts ↔ Boxes ↔ Pallets (with boxes per pallet)
    - part_to_model              - Parts ↔ Models ↔ Configurations (with quantity per vehicle)
    - part_to_line               - Parts ↔ Production lines
    - part_to_breakpoint         - Part version history through breakpoints
    - configuration_to_transmission - SOFT allow-list of (configuration, transmission) combinations

STORED INFORMATION:

1. SUPPLIERS (supplier_data):
   - Basic data: identifier, name, location
   - Address: city, street, building
   - Geographic coordinates: latitude, longitude (optional, validated to Earth range)
   - Localization: yes/no (local/foreign supplier)

2. PARTS (part_data):
   - Identifiers: PART_ID, PART_NUMBER
   - Description: name, weight (kg) with CheckConstraint (>= 0)
   - Supplier relationship (ForeignKey with RESTRICT on delete)
   - Versioning: original_part_id, version_number
   - Soft delete support: deactivated_by_breakpoint_id, computed is_active
   - deactivated_by_breakpoint_id: References breakpoint that caused deactivation (SET NULL on delete)

3. PACKAGING (box_data, pallet_data):
   - Packaging type: returnable/non-returnable/no data
   - Dimensions: length, width, height (mm) with CheckConstraint (> 0)
   - Calculated parameters: volume (m³), area (m²)
   - Weight and maximum stacking capability with CheckConstraint (>= 0)
   - Automatic packaging number generation: 'R/N/no_d L-W-H' format
   - Real-time calculation via database triggers (Computed fields)
   - UniqueConstraint on (type, length, width, height) to prevent duplicates

4. ENGINES (engine_data):
   - Engine code (GW4B15L, GW4G15N, ..., no data) — unique
   - Optional attributes: name, displacement (cc), power (hp), fuel type
   - Soft-disable flag (is_active)
   - Independent vehicle dimension: no M:N allow-list with engines/transmissions

5. TRANSMISSIONS (transmission_data):
   - Transmission code (4x4, 4x2, ..., no data) — unique
   - Optional attributes: name, drive_type (full-time, part-time, on-demand)
   - Soft-disable flag (is_active)
   - Independent vehicle dimension: allowed combinations with configurations
     are stored in configuration_to_transmission (SOFT allow-list, not FK-enforced)

6. PRODUCTION (workshop_data, line_data):
   - Workshops: code (as, comp, paint, etc.) and name
   - Lines: code, name, workshop affiliation (ForeignKey with RESTRICT on delete)

7. VEHICLE MODELS (model_data):
   - BOM product codes: a01g-r-bom, a08-r-bom, b02-r-bom, b04-r-bom,
     b06-r-bom, b16-r-bom, no data
   - Model codes (e.g. CC6460AB26B) — unique
   - Model names: jolion, h3, f7, f7x, dargo, h7, no data

8. TECHNICAL CHANGES (breakpoint_data):
   - Breakpoint number (unique, mandatory) and date
   - Entry date into the system (auto-generated)
   - Batch information (plan / fact)
   - Description of change and solution
   - Classification: change_domain (supplier, packaging, production, spec,
     config, multi) and change_nature (business, technical, correction)

9. CHANGE HISTORY (part_to_breakpoint):
   - Links part versions through technical changes (breakpoints)
   - Each change is specific to a model (model_id)
   - Type of change determined by presence of IDs:
        * ADD: new_part_id IS NOT NULL, old_part_id IS NULL
        * DELETE: new_part_id IS NULL, old_part_id IS NOT NULL
        * UPDATE: new_part_id = old_part_id (same part)
        * REPLACE: Two records (DELETE old + ADD new) in same breakpoint
   - All part data accessed through relationships to part_data
   - Composite primary key: (new_part_id, old_part_id, breakpoint_id, model_id)

10. USERS (department_data, user_role_data, user_data):
   - Departments: code and name (unique), soft-disable flag
   - Roles: application role_code (admin | editor | viewer), human-readable
     role_name, and pg_role_name (actual PostgreSQL role provisioned by
     user_roles.py: mft_admin / mft_editor / mft_viewer)
   - Users: username, email (both unique), full_name, hashed_password,
     role_id (FK, RESTRICT), department_id (FK, RESTRICT, optional),
     is_active flag, last_login_at, created_at, updated_at
   - NOTE: user_data stores APPLICATION users; their SQL privileges come
     from the PostgreSQL role referenced via role_id -> pg_role_name.
     The PostgreSQL role itself is managed by user_roles.py.

11. PRODUCTION PLAN (production_plan_data, production_plan_day_data):
   - One record per Excel line: batch, batch_date, workshop, model,
     configuration, engine, transmission, quantity, comments, created_by
   - Daily breakdown (day 1..31 in Excel) stored in production_plan_day_data
     as separate rows: (plan_id, plan_date, planned_quantity, actual_quantity)
   - NO hard allow-list of (model, configuration, engine, transmission):
     ProductionPlanData is the source of truth for which combinations exist.
     Application may warn about "new" combinations based on history.
   - batch is NOT unique: the same batch may appear in several records
     (carry-over to another day, partial production, multiple workshops)

IMPLEMENTATION FEATURES:
    - UUID format: 32 hexadecimal characters + 4 hyphens = 36 characters total
    - Automatic ID generation with prefixes:
        SUP_, PRT_, BOX_, PLT_, MDL_, CFG_, WSP_, LNE_, BPT_,
        ENG_, TRN_, DEP_, ROL_, USR_, PLN_, PLD_
    - All ID fields use format: PREFIX_ + UUID = 40 characters total
    - Business rule validation through CheckConstraint:
        * Positive values for dimensions, weights, quantities
        * Non-negative values for stacking heights
        * Latitude/longitude within Earth ranges
    - Enum type support for categorized data (including 'no data' fallbacks)
    - Unique constraints for dimension combinations (box/pallet)
    - Complete bidirectional relationship mapping with back_populates
    - Real-time calculation of packaging volume/area via SQLAlchemy Computed fields
    - Automatic packaging number generation via SQLAlchemy Computed expressions
    - Composite foreign keys with RESTRICT/CASCADE/SET NULL rules:
        * RESTRICT: Prevents deletion of referenced records with dependencies
        * CASCADE: Automatically deletes child records when parent deleted
        * SET NULL: Sets foreign key to NULL when referenced record deleted
    - Comprehensive indexing strategy including GIN for text search
    - Optimized lazy loading strategies:
        * selectin: Used for collections to avoid N+1 queries
        * joined: Used for single relationships when always needed
        * select: Default lazy loading for less frequently accessed relationships
    - Soft-delete pattern for master data (is_active flags) to preserve history
    - 'no data' seed records in engine_data / transmission_data as fallback
      for unknown values (NOT NULL FKs on production_plan_data)
    - Module-level separation:
        * database.py — ORM models (this module)
        * user_roles.py — PostgreSQL role management
    - Two-level role model:
        * user_role_data (application roles, this module)
        * pg_role_name (PostgreSQL roles, managed by user_roles.py)

RELATIONSHIP STRUCTURE:
    - Supplier (1) ↔ (N) Part (N) ↔ (N) Box (N) ↔ (N) Pallet
    - Part (N) ↔ (N) Model (with Configuration)
    - Part (N) ↔ (N) Line (N) ↔ (1) Workshop
    - Part (N) ↔ (N) Breakpoint (change history) with model-specific versions
    - Each PartToBreakpoint links new_part and old_part versions for a specific model
    - Configuration (1) ↔ (N) PartToModel (N) ↔ (1) Model
    - Configuration (N) ↔ (N) Transmission (via configuration_to_transmission)
    - Model (1) ↔ (N) PartToBreakpoint (N) ↔ (1) Part (model-specific changes)
    - Supplier (1) ↔ (N) PartToBreakpoint (supplier change history)
    - Line (1) ↔ (N) PartToBreakpoint (line change history)
    - Department (1) ↔ (N) User (N) ↔ (1) UserRole
    - User (1) ↔ (N) ProductionPlan (created_by audit)
    - Workshop (1) ↔ (N) ProductionPlan (N) ↔ (1) Model
    - Configuration (1) ↔ (N) ProductionPlan (N) ↔ (1) Engine
    - Engine (1) ↔ (N) ProductionPlan (N) ↔ (1) Transmission
    - ProductionPlan (1) ↔ (N) ProductionPlanDay

CHANGE TRACKING (PartToBreakpoint):
    - Composite PK: (new_part_id, old_part_id, breakpoint_id, model_id)
    - new_part_id/old_part_id: References part_data versions
    - breakpoint_id: References breakpoint_data
    - model_id: References model_data (model-specific change)
    - Type of change determined by presence of IDs:
        * ADD: new_part_id NOT NULL, old_part_id NULL
        * DELETE: new_part_id NULL, old_part_id NOT NULL
        * UPDATE: new_part_id = old_part_id
        * REPLACE: Two records per breakpoint

DATABASE CONSTRAINTS SUMMARY:
    - Check Constraints:
        * part_weight_kg >= 0
        * box_weight_kg >= 0, box_length_mm > 0, box_width_mm > 0,
          box_height_mm > 0, box_stacking >= 0
        * pallet_weight_kg >= 0, pallet_length_mm > 0, pallet_width_mm > 0,
          pallet_height_mm > 0, pallet_stacking >= 0
        * part_per_box > 0, box_per_pallet > 0, part_per_vehicle > 0
        * latitude BETWEEN -90 AND 90 (or NULL)
        * longitude BETWEEN -180 AND 180 (or NULL)
        * engine displacement_cc > 0 (or NULL), power_hp > 0 (or NULL)
        * production_plan_data.quantity >= 0
        * production_plan_day_data.planned_quantity >= 0
        * production_plan_day_data.actual_quantity >= 0 (or NULL)
    - Unique Constraints:
        * supplier_name
        * part_number
        * (box_type, box_length_mm, box_width_mm, box_height_mm) on box_data
        * (pallet_type, pallet_length_mm, pallet_width_mm, pallet_height_mm) on pallet_data
        * bom_product, model_code, model_name on model_data
        * configuration on configuration_data
        * engine_code on engine_data
        * transmission_code on transmission_data
        * workshop_code, workshop_name on workshop_data
        * line_code on line_data
        * breakpoint_number on breakpoint_data
        * department_code, department_name on department_data
        * role_code, role_name, pg_role_name on user_role_data
        * username, email on user_data
        * (plan_id, plan_date) on production_plan_day_data
    - NOT UNIQUE by design:
        * production_plan_data.batch (may repeat across records)
        * production_plan_data.(batch, batch_date) (may repeat within a day)

Version: 1.0.0
Compatibility: Python 3.14.4+, SQLAlchemy 1.4.54+, PostgreSQL 12+
Maintainer: PLD Engineering Center
Created: 2026-01-16
Last Modified: 2026-11-02
License: MIT
Status: Production
"""
# Third-party imports
from sqlalchemy import (
    CheckConstraint, Column, Computed, Date, DateTime, Enum as SqlEnum,
    ForeignKey, func, Index, text, UniqueConstraint
)
from sqlalchemy.types import (
    Boolean, Integer, Numeric, String, SmallInteger, Text
)
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

# Base class
Base = declarative_base()

# ========== ENUM TYPES ==========
LOCALIZATION_ENUM = SqlEnum(
    'yes', 'no', 'no data',
    name='localization'
)

PACKAGING_TYPE_ENUM = SqlEnum(
    'returnable', 'non-returnable', 'no data',
    name='packaging_type'
)

BOM_PRODUCT_ENUM = SqlEnum(
    'a01g-r-bom', 'a08-r-bom', 'b02-r-bom', 'b04-r-bom', 'b06-r-bom', 'b16-r-bom', 'no data',
    name='model_codes'
)

MODEL_NAMES_ENUM = SqlEnum(
    'jolion', 'h3', 'f7', 'f7x', 'dargo', 'h7', 'no data',
    name='model_names'
)

WORKSHOP_CODES_ENUM = SqlEnum(
    'as', 'comp', 'paint', 'weld', 'stamp', 'en', 'nb', 'tr', 'ch', 'no data',
    name='workshop_codes'
)

WORKSHOP_NAMES_ENUM = SqlEnum(
    'assembly', 'component', 'painting', 'welding', 'stamping', 'engine', 'nobo', 'transmission', 'chassis', '', 'no data',
    name='workshop_names'
)

CONFIGURATION_ENUM = SqlEnum(
    'comfort', 'elite', 'tech-plus', 'premium', 's_version', 'no data',
    name='configuration_types'
)

BREAKPOINT_STATUS_ENUM = SqlEnum(
    'approved', 'published', 'closed', 'no data',
    name='breakpoint_status'
)

# ========== CORE ENTITY TABLES ==========
class SupplierData(Base):
    '''
    Model defines a table for storing supplier's information.
    '''
    __tablename__ = 'supplier_data'
    __table_args__ = (
        CheckConstraint(
            'latitude IS NULL OR (latitude BETWEEN -90 AND 90)',
            name='chk_supplier_latitude_range'
        ),
        CheckConstraint(
            'longitude IS NULL OR (longitude BETWEEN -180 AND 180)',
            name='chk_supplier_longitude_range'
        ),
        Index('idx_supplier_name', 'supplier_name'),
        Index('idx_supplier_city', 'city'),
        Index('idx_supplier_localization', 'localization'),
        {
            'comment': """
            PURPOSE: Automotive component suppliers master data
            ---
            COLUMN DESCRIPTION:
            - supplier_id: Unique system identifier (SUP_ + 36-character UUID)
            - supplier_name: Legal entity name for contracts
            - location/city/street/building: Complete address
            - latitude: Geographic latitude in decimal degrees (-90..+90)
            - longitude: Geographic longitude in decimal degrees (-180..+180)
            - localization: 'yes'=local, 'no'=foreign (affects customs)
            ---
            RELATIONSHIPS:
            - One supplier produces many parts (1:N with PartData)
            ---
            BUSINESS RULES:
            - City is mandatory for logistics planning
            - Localization affects duty calculations
            - Supplier ID is immutable
            - Coordinates optional; when present, validated to valid Earth ranges
            - Coordinates used for logistics route optimization and map display
            - Numeric(9,6) gives ~11 cm precision — sufficient for logistics
            """
        },
    )
    supplier_id = Column(
        String(40),
        primary_key=True,
        server_default=text("'SUP_' || gen_random_uuid()::text"),
        unique=True,
        nullable=False
    )
    supplier_name = Column(
        String(200),
        unique=True,
        nullable=False
    )
    location = Column(
        String(50),
        nullable=True
    )
    city = Column(
        String(50),
        nullable=True
    )
    street = Column(
        String(100),
        nullable=True
    )
    building = Column(
        String(10),
        nullable=True
    )
    latitude = Column(
        Numeric(9, 6),
        nullable=True
    )
    longitude = Column(
        Numeric(9, 6),
        nullable=True
    )
    localization = Column(
        LOCALIZATION_ENUM,
        nullable=False
    )
    # Relationships
    parts = relationship('PartData', back_populates='supplier', lazy='selectin')
    breakpoint_changes = relationship(
        'PartToBreakpoint',
        foreign_keys='PartToBreakpoint.supplier_id',
        back_populates='supplier',
        lazy='select'
    )

class PartData(Base):
    '''
    Model defines a table for storing component's information.
    '''
    __tablename__ = 'part_data'
    __table_args__ = (
        Index('idx_part_number', 'part_number'),
        Index('idx_part_name', 'part_name'),
        Index('idx_part_weight', 'part_weight_kg'),
        Index('idx_part_supplier_id', 'supplier_id'),
        Index('idx_part_deactivated', 'deactivated_by_breakpoint_id'),
        {
            'comment': """
            PURPOSE: Automotive component master data with versioning support
            ---
            COLUMN DESCRIPTION:
            - part_id: Unique system identifier (PRT_ + 36-character UUID)
            - part_number: Business number (99999AAA999 format)
            - part_name: Technical description
            - part_weight_kg: Weight in kilograms (precision 0.01)
            - supplier_id: References supplier_data
            - is_active: Computed property - True if part has at least one active model association
            - deactivated_by_breakpoint_id: Which breakpoint caused deactivation
              (deactivated_at is computed from breakpoint_date)
            - original_part_id: First version of this part (for grouping versions)
            - version_number: Version number (1, 2, 3, ...)
            - created_at: When this version was created
            ---
            RELATIONSHIPS:
            - Many-to-Many with: ModelData, LineData, BoxData, BreakpointData
            - Many-to-One with: SupplierData
            ---
            BUSINESS RULES:
            - Part number follows corporate standard
            - Weight critical for logistics costing
            - Each part has exactly one supplier
            - Parts are never physically deleted, only deactivated (soft delete)
            - Historical data in part_to_breakpoint remains valid
            - deactivated_at is ALWAYS derived from breakpoint_date
            - Single source of truth: breakpoint_data.breakpoint_date
            """
        },
    )
    part_id = Column(
        String(40),
        primary_key=True,
        server_default=text("'PRT_' || gen_random_uuid()::text"),
        unique=True,
        nullable=False
    )
    part_number = Column(
        String(50),
        unique=True,
        nullable=False
    )
    part_name = Column(
        String(100),
        nullable=True
    )
    part_weight_kg = Column(
        Numeric(5, 2),
        CheckConstraint('part_weight_kg >= 0'),
        nullable=True
    )
    supplier_id = Column(
        String(40),
        ForeignKey('supplier_data.supplier_id', ondelete='RESTRICT'),
        nullable=False
    )
    # Versioning fields
    deactivated_by_breakpoint_id = Column(
        String(40),
        ForeignKey('breakpoint_data.breakpoint_id', ondelete='SET NULL'),
        nullable=True,
        comment="References the breakpoint that caused deactivation. Deactivation date is derived from breakpoint_date."
    )
    original_part_id = Column(
        String(40),
        ForeignKey('part_data.part_id', ondelete='SET NULL'),
        nullable=True,
        comment="First version ID for grouping all versions of the same part"
    )
    version_number = Column(
        Integer,
        nullable=False,
        default=1,
        comment="Version number (starts at 1 for original)"
    )
    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )
    # Relationships
    supplier = relationship(
        'SupplierData',
        back_populates='parts',
        lazy='joined'
    )
    boxes = relationship(
        'PartToBox',
        back_populates='part',
        lazy='selectin',
        cascade='all, delete-orphan'
    )
    models = relationship(
        'PartToModel',
        back_populates='part',
        lazy='selectin',
        cascade='all, delete-orphan'
    )
    lines = relationship(
        'PartToLine',
        back_populates='part',
        lazy='select',
        cascade='all, delete-orphan'
    )
    box_pallet_combinations = relationship(
        'BoxToPallet',
        back_populates='part',
        lazy='selectin',
        cascade='all, delete-orphan'
    )
    new_versions = relationship(
        'PartToBreakpoint',
        foreign_keys='PartToBreakpoint.new_part_id',
        back_populates='new_part',
        lazy='select'
    )
    old_versions = relationship(
        'PartToBreakpoint',
        foreign_keys='PartToBreakpoint.old_part_id',
        back_populates='old_part',
        lazy='select'
    )
    deactivation_breakpoint = relationship(
        'BreakpointData',
        foreign_keys=[deactivated_by_breakpoint_id],
        lazy='joined',
        back_populates='deactivated_parts'
    )
    original_part = relationship(
        'PartData',
        remote_side=[part_id],
        foreign_keys=[original_part_id],
        lazy='joined'
    )
    # Properties
    @property
    def deactivated_at(self):
        """
        Part deactivation date.
        
        ALWAYS taken from breakpoint_data.breakpoint_date,
        which guarantees a single source of truth.
        
        Returns:
            datetime or None: The effective date of the breakpoint
                             that deactivated the part
        """
        if self.deactivated_by_breakpoint_id and self.deactivation_breakpoint:
            return self.deactivation_breakpoint.breakpoint_date
        return None

    @property
    def is_active(self):
        """
        Part is active if there is at least one active connection to a model.
        
        Note: A part can be active for some models and inactive for others.
        """
        return any(model.is_active for model in self.models)

    @property
    def deactivated_by(self):
        """
        Returns the BreakpointData object that caused the deactivation.
        
        Returns:
            BreakpointData or None: The breakpoint that caused deactivation
        """
        return self.deactivation_breakpoint

    @property
    def is_fully_deactivated(self):
        """
        Checks if the part is fully deactivated (for all models).
        
        Returns:
            bool: True if there are no active connections to models
        """
        return not self.is_active

    @property
    def active_models(self):
        """List of models for which the part is active"""
        return [model for model in self.models if model.is_active]

    @property
    def inactive_models(self):
        """List of models for which the part is inactive"""
        return [model for model in self.models if not model.is_active]

    @property
    def deactivation_info(self):
        """
        Complete deactivation information.
        
        Returns:
            dict: Contains breakpoint, date and reason for deactivation
        """
        if not self.deactivated_by_breakpoint_id:
            return None

        return {
            'breakpoint_id': self.deactivated_by_breakpoint_id,
            'breakpoint_number': self.deactivation_breakpoint.breakpoint_number if self.deactivation_breakpoint else None,
            'deactivated_at': self.deactivated_at,
            'breakpoint_status': self.deactivation_breakpoint.breakpoint_status if self.deactivation_breakpoint else None,
            'description': self.deactivation_breakpoint.description if self.deactivation_breakpoint else None,
            'solution': self.deactivation_breakpoint.solution if self.deactivation_breakpoint else None,
        }


class BoxData(Base):
    '''
    Model defines a table for storing box's information.
    '''
    __tablename__ = 'box_data'
    __table_args__ = (
        Index('idx_box_number', 'box_number'),
        Index('idx_box_type', 'box_type'),
        Index('idx_box_dimensions',
              'box_length_mm', 'box_width_mm', 'box_height_mm'),
        UniqueConstraint('box_type', 'box_length_mm', 'box_width_mm', 'box_height_mm',
                         name='unique_box_dimensions'),
        {
            'comment': """
            PURPOSE: Packaging specifications for logistics
            ---
            COLUMN DESCRIPTION:
            - box_id: Unique system identifier (BOX_ + 36-character UUID)
            - box_number: Auto-generated from type and dimensions (R/N L-W-H)
            - box_type: 'returnable' or 'non-returnable'
            - Dimensions: Length/Width/Height in mm
            - box_vol_m3/box_area_m2: Calculated from dimensions
            - box_stacking: Max safe box stacking height
            ---
            RELATIONSHIPS:
            - Many-to-Many with: PartData (via part_to_box)
            - Many-to-Many with: PalletData (via box_to_pallet)
            ---
            BUSINESS RULES:
            - Standard sizes:
                - 400x300x200mm - Small electronic components
                - 600x400x300mm - Middle nodes (sensors, control units)
                - 800x600x400mm - Large parts (headlights, seats)
                - 1200x800x600mm - Very large components (doors, hoods)
            - Dimensions in 5mm increments
            - Volume/area auto-calculated on insert/update
            - Box number auto-generated from type and dimensions
            """
        },
    )
    box_id = Column(
        String(40),
        primary_key=True,
        server_default=text("'BOX_' || gen_random_uuid()::text"),
        unique=True,
        nullable=False
    )
    box_type = Column(
        PACKAGING_TYPE_ENUM,
        nullable=False
    )
    box_weight_kg = Column(
        Numeric(5, 2),
        CheckConstraint('box_weight_kg >= 0'),
        nullable=True
    )
    box_length_mm = Column(
        SmallInteger,
        CheckConstraint('box_length_mm > 0'),
        nullable=True
    )
    box_width_mm = Column(
        SmallInteger,
        CheckConstraint('box_width_mm > 0'),
        nullable=True
    )
    box_height_mm = Column(
        SmallInteger,
        CheckConstraint('box_height_mm > 0'),
        nullable=True
    )
    box_number = Column(String(50), Computed(
        """
        CASE
            WHEN box_type IS NOT NULL
                AND box_length_mm IS NOT NULL
                AND box_width_mm IS NOT NULL
                AND box_height_mm IS NOT NULL
            THEN 
                CASE 
                    WHEN box_type = 'returnable' THEN 'R ' || 
                        box_length_mm::text || '-' ||
                        box_width_mm::text || '-' ||
                        box_height_mm::text
                    WHEN box_type = 'non-returnable' THEN 'N ' ||
                        box_length_mm::text || '-' ||
                        box_width_mm::text || '-' ||
                        box_height_mm::text
                    WHEN box_type = 'no data' THEN 'no_d ' ||
                        box_length_mm::text || '-' ||
                        box_width_mm::text || '-' ||
                        box_height_mm::text
                    ELSE NULL
                END
            ELSE NULL
        END
        """
        ), nullable=True
    )
    box_vol_m3 = Column(Numeric(8, 4), Computed(
        """
        CASE
            WHEN box_length_mm IS NOT NULL
                 AND box_width_mm IS NOT NULL
                 AND box_height_mm IS NOT NULL
            THEN ROUND(
                (box_length_mm::numeric / 1000.0) *
                (box_width_mm::numeric / 1000.0) *
                (box_height_mm::numeric / 1000.0), 4
            )
            ELSE NULL
        END
        """
        ), nullable=True
    )
    box_area_m2 = Column(Numeric(8, 4), Computed(
        """
        CASE
            WHEN box_length_mm IS NOT NULL
                 AND box_width_mm IS NOT NULL
            THEN ROUND(
                (box_length_mm::numeric / 1000.0) *
                (box_width_mm::numeric / 1000.0), 4
            )
            ELSE NULL
        END
        """
        ), nullable=True
    )
    box_stacking = Column(
        SmallInteger,
        CheckConstraint('box_stacking >= 0'),
        nullable=True
    )
    # Relationships
    parts = relationship(
        'PartToBox',
        back_populates='box',
        lazy='select'
    )
    pallets = relationship(
        'BoxToPallet',
        back_populates='box',
        lazy='select'
    )


class PalletData(Base):
    '''
    Model defines a table for storing pallet's information.
    '''
    __tablename__ = 'pallet_data'
    __table_args__ = (
        Index('idx_pallet_number', 'pallet_number'),
        Index('idx_pallet_type', 'pallet_type'),
        Index('idx_pallet_dimensions',
              'pallet_length_mm', 'pallet_width_mm', 'pallet_height_mm'),
        UniqueConstraint('pallet_type', 'pallet_length_mm', 'pallet_width_mm', 'pallet_height_mm',
                         name='unique_pallet_dimensions'),
        {
            'comment': """
            PURPOSE: Pallet specifications for logistics
            ---
            COLUMN DESCRIPTION:
            - pallet_id: Unique system identifier (PLT_ + 36-character UUID)
            - pallet_number: Auto-generated from type and dimensions (R/N L-W-H)
            - pallet_type: 'returnable' or 'non-returnable'
            - Dimensions: Length/Width/Height in mm
            - pallet_vol_m3/pallet_area_m2: Calculated from dimensions
            - pallet_stacking: Max safe pallet stacking height
            ---
            RELATIONSHIPS:
            - Many-to-Many with: BoxData (via box_to_pallet)
            ---
            BUSINESS RULES:
            - Standard sizes:
                - 1200x800mm - Euro
                - 1200x1000mm - Industrial
            - Dimensions in 10mm increments
            - Volume/area auto-calculated on insert/update
            - Pallet number auto-generated from type and dimensions
            """
        },
    )
    pallet_id = Column(
        String(40),
        primary_key=True,
        server_default=text("'PLT_' || gen_random_uuid()::text"),
        unique=True,
        nullable=False
    )
    pallet_type = Column(
        PACKAGING_TYPE_ENUM,
        nullable=False
    )
    pallet_weight_kg = Column(
        Numeric(5, 2),
        CheckConstraint('pallet_weight_kg >= 0'),
        nullable=True
    )
    pallet_length_mm = Column(
        SmallInteger,
        CheckConstraint('pallet_length_mm > 0'),
        nullable=True
    )
    pallet_width_mm = Column(
        SmallInteger,
        CheckConstraint('pallet_width_mm > 0'),
        nullable=True
    )
    pallet_height_mm = Column(
        SmallInteger,
        CheckConstraint('pallet_height_mm > 0'),
        nullable=True
    )
    pallet_number = Column(String(50), Computed(
        """
        CASE
            WHEN pallet_type IS NOT NULL
                AND pallet_length_mm IS NOT NULL
                AND pallet_width_mm IS NOT NULL
                AND pallet_height_mm IS NOT NULL
            THEN 
                CASE 
                    WHEN pallet_type = 'returnable' THEN 'R ' || 
                        pallet_length_mm::text || '-' ||
                        pallet_width_mm::text || '-' ||
                        pallet_height_mm::text
                    WHEN pallet_type = 'non-returnable' THEN 'N ' ||
                        pallet_length_mm::text || '-' ||
                        pallet_width_mm::text || '-' ||
                        pallet_height_mm::text
                    WHEN pallet_type = 'no data' THEN 'no_d ' ||
                        pallet_length_mm::text || '-' ||
                        pallet_width_mm::text || '-' ||
                        pallet_height_mm::text
                    ELSE NULL
                END
            ELSE NULL
        END
        """
        ), nullable=True
    )
    pallet_vol_m3 = Column(Numeric(8, 4), Computed(
        """
        CASE
            WHEN pallet_length_mm IS NOT NULL
                 AND pallet_width_mm IS NOT NULL
                 AND pallet_height_mm IS NOT NULL
            THEN ROUND(
                (pallet_length_mm::numeric / 1000.0) *
                (pallet_width_mm::numeric / 1000.0) *
                (pallet_height_mm::numeric / 1000.0), 4
            )
            ELSE NULL
        END
        """
        ), nullable=True
    )
    pallet_area_m2 = Column(Numeric(8, 4), Computed(
        """
        CASE
            WHEN pallet_length_mm IS NOT NULL
                 AND pallet_width_mm IS NOT NULL
            THEN ROUND(
                (pallet_length_mm::numeric / 1000.0) *
                (pallet_width_mm::numeric / 1000.0), 4
            )
            ELSE NULL
        END
        """
        ), nullable=True
    )
    pallet_stacking = Column(
        SmallInteger,
        CheckConstraint('pallet_stacking >= 0'),
        nullable=True
    )
    # Relationships
    boxes = relationship(
        'BoxToPallet',
        back_populates='pallet',
        lazy='select'
    )


class ModelData(Base):
    '''
    Model defines a table for storing model's information.
    '''
    __tablename__ = 'model_data'
    __table_args__ = (
        Index('idx_model_code', 'model_code'),
        Index('idx_model_name', 'model_name'),
        {
            'comment': """
            PURPOSE: Vehicle model master data
            ---
            COLUMN DESCRIPTION:
            - model_id: Unique system identifier (MDL_ + 36-character UUID)
            - model_code: Platform codes (A01, B02, etc.)
            - model_name: Marketing names (Jolion, H3, etc.)
            ---
            RELATIONSHIPS:
            - Many-to-Many with: PartData (via part_to_model)
            ---
            BUSINESS RULES:
            - Model codes follow platform-generation-variant pattern
            - Used for BOM (Bill of Materials) configuration
            """
        },
    )
    model_id = Column(
        String(40),
        primary_key=True,
        server_default=text("'MDL_' || gen_random_uuid()::text"),
        unique=True,
        nullable=False
    )
    bom_product = Column(
        BOM_PRODUCT_ENUM,
        unique=True,
        nullable=False
        )
    model_code = Column(
        String(15),
        unique=True,
        nullable=False
    )
    model_name = Column(
        MODEL_NAMES_ENUM,
        unique=True,
        nullable=False
    )
    # Relationships
    parts = relationship(
        'PartToModel',
        back_populates='model',
        lazy='select'
    )
    breakpoint_changes = relationship(
        'PartToBreakpoint',
        foreign_keys='PartToBreakpoint.model_id',
        back_populates='model',
        lazy='select'
    )
    production_plans = relationship(
        'ProductionPlanData',
        back_populates='model',
        lazy='select'
    )


class ConfigurationData(Base):
    '''
    Model defines a table for storing configuration types.
    '''
    __tablename__ = 'configuration_data'
    __table_args__ = (
        Index('idx_configuration', 'configuration'),
        {
            'comment': """
            PURPOSE: Configuration types master data
            ---
            COLUMN DESCRIPTION:
            - configuration_id: Unique system identifier (CFG_ + 36-character UUID)
            - configuration: Configuration name (comfort, elite, tech_plus, premium)
            RELATIONSHIPS:
            - Many-to-Many with: TransmissionData (via configuration_to_transmission)
              Defines which transmissions are allowed for this configuration.
            - Many-to-Many with: PartData (via part_to_model)
            - One-to-Many with: ProductionPlanData (each batch picks one configuration)
            ---
            ---
            BUSINESS RULES:
            - Configuration names are unique
            - Used across all vehicle models
            - Affects part consumption per vehicle
            - Transmission is an INDEPENDENT dimension of a vehicle, NOT an
              attribute of ConfigurationData. The allowed combinations are
              defined in configuration_to_transmission (M:N).
            - The actual combination used by a specific batch is stored in
              ProductionPlanData (configuration_id + transmission_id)
            """
        },
    )
    configuration_id = Column(
        String(40),
        primary_key=True,
        server_default=text("'CFG_' || gen_random_uuid()::text"),
        unique=True,
        nullable=False
    )
    configuration = Column(
        CONFIGURATION_ENUM,
        unique=True,
        nullable=False
    )
    # Relationships
    part_models = relationship(
        'PartToModel',
        back_populates='configuration'
    )
    allowed_transmissions = relationship(
        'ConfigurationToTransmission',
        back_populates='configuration',
        lazy='selectin',
        cascade='all, delete-orphan'
    )
    production_plans = relationship(
        'ProductionPlanData',
        back_populates='configuration',
        lazy='select'
    )


class EngineData(Base):
    '''
    Model defines a table for storing engine specifications.
    '''
    __tablename__ = 'engine_data'
    __table_args__ = (
        Index('idx_engine_code', 'engine_code'),
        {
            'comment': """
            PURPOSE: Engine master data
            ---
            COLUMN DESCRIPTION:
            - engine_id: Unique system identifier (ENG_ + 36-character UUID)
            - engine_code: Engine code (GW4B15L, GW4G15N, ..., no data)
            - engine_name: Human-readable name (optional)
            - displacement_cc: Engine displacement in cubic centimeters
            - power_hp: Maximum power in horsepower
            - fuel_type: Fuel type (petrol, diesel, hybrid, electric)
            - is_active: Soft-disable flag
            ---
            RELATIONSHIPS:
            - One engine is used in many production plans
              (1:N with ProductionPlanData)
            ---
            BUSINESS RULES:
            - Engine codes are unique
            - 'no data' engine exists as fallback for unknown engines
            - Engines are never physically deleted (is_active=False)
            - Engine is an INDEPENDENT dimension of a vehicle:
              the same engine can be installed on different models,
              configurations and drivetrains
            """
        },
    )
    engine_id = Column(
        String(40),
        primary_key=True,
        server_default=text("'ENG_' || gen_random_uuid()::text"),
        unique=True,
        nullable=False
    )
    engine_code = Column(
        String(50),
        unique=True,
        nullable=False,
        comment="Engine code (e.g. GW4B15L, GW4G15N, no data)"
    )
    engine_name = Column(
        String(200),
        nullable=True
    )
    displacement_cc = Column(
        Integer,
        CheckConstraint(
            'displacement_cc IS NULL OR displacement_cc > 0',
            name='chk_engine_displacement'
        ),
        nullable=True
    )
    power_hp = Column(
        SmallInteger,
        CheckConstraint(
            'power_hp IS NULL OR power_hp > 0',
            name='chk_engine_power'
        ),
        nullable=True
    )
    fuel_type = Column(
        String(20),
        nullable=True,
        comment="Fuel type: petrol, diesel, hybrid, electric"
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text('true')
    )
    # Relationships
    production_plans = relationship(
        'ProductionPlanData',
        back_populates='engine',
        lazy='select'
    )


class TransmissionData(Base):
    '''
    Model defines a table for storing transmission / drivetrain specifications.
    '''
    __tablename__ = 'transmission_data'
    __table_args__ = (
        Index('idx_transmission_code', 'transmission_code'),
        {
            'comment': """
            PURPOSE: Transmission / drivetrain master data
            ---
            COLUMN DESCRIPTION:
            - transmission_id: Unique system identifier (TRN_ + 36-character UUID)
            - transmission_code: Transmission code (4x4, 4x2, no data)
            - transmission_name: Human-readable name
            - drive_type: Drivetrain type (full-time, part-time, on-demand)
            - is_active: Soft-disable flag
            ---
            RELATIONSHIPS:
            - Many-to-Many with: ConfigurationData (via configuration_to_transmission)
              Defines which configurations are allowed for this transmission.
            - One-to-Many with: ProductionPlanData (each batch picks one transmission)
            ---
            BUSINESS RULES:
            - Transmission codes are unique
            - 'no data' transmission exists as fallback for unknown values
            - Transmissions are never physically deleted (is_active=False)
            - Transmission is an INDEPENDENT dimension of a vehicle, NOT an
              attribute of ConfigurationData. Combinations premium+4x4 and
              premium+4x2 are distinct vehicles with potentially different BOMs.
            - Allowed combinations are managed in configuration_to_transmission
            """
        },
    )
    transmission_id = Column(
        String(40),
        primary_key=True,
        server_default=text("'TRN_' || gen_random_uuid()::text"),
        unique=True,
        nullable=False
    )
    transmission_code = Column(
        String(20),
        unique=True,
        nullable=False,
        comment="Transmission code (e.g. 4x4, 4x2, no data)"
    )
    transmission_name = Column(
        String(100),
        nullable=True
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text('true')
    )
    # Relationships
    allowed_configurations = relationship(
        'ConfigurationToTransmission',
        back_populates='transmission',
        lazy='selectin'
    )
    production_plans = relationship(
        'ProductionPlanData',
        back_populates='transmission',
        lazy='select'
    )


class WorkshopData(Base):
    '''
    Model defines a table for storing workshop's information.
    '''
    __tablename__ = 'workshop_data'
    __table_args__ = (
        Index('idx_workshop_code', 'workshop_code'),
        Index('idx_workshop_name', 'workshop_name'),
        {
            'comment': """
            PURPOSE: Production workshop organization
            ---
            COLUMN DESCRIPTION:
            - workshop_id: Unique system identifier (WSP_ + 36-character UUID)
            - workshop_code: Process codes (AS, COMP, etc.)
            - workshop_name: Full names (Assembly, Component, etc.)
            ---
            RELATIONSHIPS:
            - One workshop contains many lines (1:N with LineData)
            ---
            BUSINESS RULES:
            - Workshops represent manufacturing process steps
            - Codes follow production flow sequence
            """
        },
    )
    workshop_id = Column(
        String(40),
        primary_key=True,
        server_default=text("'WSP_' || gen_random_uuid()::text"),
        unique=True,
        nullable=False
    )
    workshop_code = Column(
        WORKSHOP_CODES_ENUM,
        unique=True,
        nullable=False
    )
    workshop_name = Column(
        WORKSHOP_NAMES_ENUM,
        unique=True,
        nullable=False
    )
    # Relationships
    lines = relationship(
        'LineData',
        back_populates='workshop',
        lazy='joined'
    )
    production_plans = relationship(
        'ProductionPlanData',
        back_populates='workshop',
        lazy='select'
    )


class LineData(Base):
    '''
    Model defines a table for storing line's information.
    '''
    __tablename__ = 'line_data'
    __table_args__ = (
        Index('idx_line_code', 'line_code'),
        Index('idx_line_name', 'line_name'),
        Index('idx_line_workshop_id', 'workshop_id'),
        {
            'comment': """
            PURPOSE: Production line specifications
            ---
            COLUMN DESCRIPTION:
            - line_id: Unique system identifier (LNE_ + 36-character UUID)
            - line_code: Line identifier within workshop
            - line_name: Descriptive name
            - workshop_id: References workshop_data
            ---
            RELATIONSHIPS:
            - Many-to-One with: WorkshopData
            - Many-to-Many with: PartData (via part_to_line)
            ---
            BUSINESS RULES:
            - Each line belongs to exactly one workshop
            - Parts are assigned to specific installation lines
            """
        },
    )
    line_id = Column(
        String(40),
        primary_key=True,
        server_default=text("'LNE_' || gen_random_uuid()::text"),
        unique=True,
        nullable=False
    )
    line_code = Column(
        String(10),
        unique=True,
        nullable=False
    )
    line_name = Column(
        String(50),
        nullable=True
    )
    workshop_id = Column(
        String(40),
        ForeignKey('workshop_data.workshop_id', ondelete='RESTRICT'),
        nullable=False,
        comment="The production workshop cannot be deleted if there are lines!"
    )
    # Relationships
    workshop = relationship(
        'WorkshopData',
        back_populates='lines',
        lazy='joined'
    )
    parts = relationship(
        'PartToLine',
        back_populates='line',
        lazy='select'
    )
    breakpoint_changes = relationship(
        'PartToBreakpoint',
        foreign_keys='PartToBreakpoint.line_id',
        back_populates='line',
        lazy='select'
    )


class BreakpointData(Base):
    '''
    Model defines a table for storing technical change's information.
    '''
    __tablename__ = 'breakpoint_data'
    __table_args__ = (
        Index('idx_breakpoint_number', 'breakpoint_number'),
        Index('idx_breakpoint_date', 'breakpoint_date'),
        Index('idx_input_date', 'input_date'),
        Index('idx_breakpoint_batch_plan', 'batch_plan'),
        Index('idx_breakpoint_batch_fact', 'batch_fact'),
        Index('idx_breakpoint_domain', 'change_domain'),
        Index('idx_breakpoint_nature', 'change_nature'),
        Index('idx_breakpoint_domain_nature', 'change_domain', 'change_nature'),
        {
            'comment': """
            PURPOSE: Technical change management (breakpoints) with classification
            ---
            COLUMN DESCRIPTION:
            - breakpoint_id: Unique system identifier (BPT_ + 36-character UUID)
            - input_date: When record was created
            - breakpoint_number: Engineering change identifier (BP-* or MAN-*)
            - breakpoint_status: Execution status of breakpoint
            - breakpoint_date: When change takes effect
            - batch_plan: Planned batch number
            - batch_fact: Real batch number
            - description: Cause description (from Excel)
            - solution: Solution description (from Excel)
            - change_domain: WHAT changed (supplier, packaging, production, spec, config, multi)
            - change_nature: WHY it changed (business, technical, correction)
            ---
            CLASSIFICATION:
            - Domain: supplier | packaging | production | spec | config | multi
            - Nature: business | technical | correction
            ---
            SOURCES:
            - Automatic: BP pipeline from Excel (BP-*)
            - Manual: MFT Modify API (MAN-*)
            ---
            INDEXES:
            - idx_breakpoint_number: For breakpoint lookups
            - idx_breakpoint_date: For date range queries
            - idx_breakpoint_domain: For domain filtering
            - idx_breakpoint_nature: For nature filtering
            - idx_breakpoint_domain_nature: For combined filtering
            """
        },
    )
    breakpoint_id = Column(
        String(40),
        primary_key=True,
        server_default=text("'BPT_' || gen_random_uuid()::text"),
        unique=True,
        nullable=False
    )
    input_date = Column(
        DateTime(),
        server_default=func.now(),
        nullable=False
    )
    breakpoint_number = Column(
        String(10),
        unique=True,
        nullable=False
    )
    breakpoint_status = Column(
        BREAKPOINT_STATUS_ENUM,
        nullable=False
    )
    batch_plan = Column(
        String(10),
        nullable=True
    )
    batch_fact = Column(
        String(10),
        nullable=True
    )
    breakpoint_date = Column(
        DateTime(),
        nullable=False
    )
    description = Column(
        Text,
        nullable=True
    )
    solution = Column(
        Text,
        nullable=True
    )
    change_domain = Column(
        String(20),
        nullable=True,
        comment="Domain: supplier, packaging, production, spec, config, multi"
    )
    change_nature = Column(
        String(20),
        nullable=True,
        comment="Nature: business, technical, correction"
    )
    # Relationships
    part_transitions = relationship(
        'PartToBreakpoint',
        back_populates='breakpoint',
        lazy='select'
    )
    deactivated_parts = relationship(
        'PartData',
        foreign_keys='PartData.deactivated_by_breakpoint_id',
        back_populates='deactivation_breakpoint',
        lazy='selectin'
    )
    deactivated_part_models = relationship(
        'PartToModel',
        foreign_keys='PartToModel.deactivated_by_breakpoint_id',
        back_populates='deactivation_breakpoint',
        lazy='select'
    )


# ========== USER MANAGEMENT TABLES ==========
class DepartmentData(Base):
    '''
    Model defines a table for storing company departments.
    '''
    __tablename__ = 'department_data'
    __table_args__ = (
        Index('idx_department_code', 'department_code'),
        Index('idx_department_name', 'department_name'),
        {
            'comment': """
            PURPOSE: Company departments master data
            ---
            COLUMN DESCRIPTION:
            - department_id: Unique system identifier (DEP_ + 36-character UUID)
            - department_code: Short code (LOG, QA, PROD, etc.)
            - department_name: Full department name
            - description: Optional notes
            - is_active: Soft-disable flag
            - created_at: Record creation timestamp
            ---
            RELATIONSHIPS:
            - One department has many users (1:N with UserData)
            ---
            BUSINESS RULES:
            - Department codes are unique
            - Departments are never physically deleted (is_active=False)
            - Users may exist without a department (nullable FK)
            """
        },
    )
    department_id = Column(
        String(40),
        primary_key=True,
        server_default=text("'DEP_' || gen_random_uuid()::text"),
        unique=True,
        nullable=False
    )
    department_code = Column(
        String(20),
        unique=True,
        nullable=False
    )
    department_name = Column(
        String(200),
        unique=True,
        nullable=False
    )
    description = Column(
        Text,
        nullable=True
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text('true')
    )
    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )
    # Relationships
    users = relationship(
        'UserData',
        back_populates='department',
        lazy='selectin'
    )


class UserRoleData(Base):
    '''
    Model defines a table for storing application-level business roles.

    NOTE: This table is distinct from PostgreSQL roles managed by
    user_roles.py. Each application role maps to exactly one PostgreSQL
    role via pg_role_name (admin -> mft_admin, editor -> mft_editor,
    viewer -> mft_viewer).
    '''
    __tablename__ = 'user_role_data'
    __table_args__ = (
        Index('idx_user_role_code', 'role_code'),
        Index('idx_user_role_pg_name', 'pg_role_name'),
        {
            'comment': """
            PURPOSE: Application-level business roles mapped to PostgreSQL roles
            ---
            COLUMN DESCRIPTION:
            - role_id: Unique system identifier (ROL_ + 36-character UUID)
            - role_code: Application code (admin | editor | viewer)
            - role_name: Human-readable name
            - pg_role_name: Actual PostgreSQL role name (mft_admin, etc.)
            - description: Detailed purpose of the role
            - is_active: Soft-disable flag
            ---
            RELATIONSHIPS:
            - One role has many users (1:N with UserData)
            ---
            BUSINESS RULES:
            - role_code values MUST match the classes in user_roles.py
            - pg_role_name is the actual PostgreSQL role granted via user_roles.py
            - Role table is extensible (unlike fixed ENUMs for stable categories)
            - Roles are never physically deleted (is_active=False)
            """
        },
    )
    role_id = Column(
        String(40),
        primary_key=True,
        server_default=text("'ROL_' || gen_random_uuid()::text"),
        unique=True,
        nullable=False
    )
    role_code = Column(
        String(20),
        unique=True,
        nullable=False,
        comment="Application role code: admin | editor | viewer"
    )
    role_name = Column(
        String(100),
        unique=True,
        nullable=False
    )
    pg_role_name = Column(
        String(63),
        unique=True,
        nullable=False,
        comment="PostgreSQL role name (max 63 chars per PostgreSQL identifier limit)"
    )
    description = Column(
        Text,
        nullable=True
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text('true')
    )
    # Relationships
    users = relationship(
        'UserData',
        back_populates='role',
        lazy='selectin'
    )


class UserData(Base):
    '''
    Model defines a table for storing database users of the application.

    NOTE: This table stores APPLICATION users. Their SQL privileges are
    determined by the PostgreSQL role referenced via role_id -> pg_role_name.
    The actual PostgreSQL role is provisioned by user_roles.py.
    '''
    __tablename__ = 'user_data'
    __table_args__ = (
        Index('idx_user_username', 'username'),
        Index('idx_user_email', 'email'),
        Index('idx_user_role_id', 'role_id'),
        Index('idx_user_department_id', 'department_id'),
        Index('idx_user_active', 'is_active'),
        {
            'comment': """
            PURPOSE: Application user accounts
            ---
            COLUMN DESCRIPTION:
            - user_id: Unique system identifier (USR_ + 36-character UUID)
            - username: Login name (unique, case-sensitive as entered)
            - email: Contact and recovery address (unique)
            - full_name: Display name
            - hashed_password: Password hash (bcrypt/argon2), NEVER plaintext
            - role_id: Business role (references user_role_data)
            - department_id: Optional department affiliation
            - is_active: Soft-disable flag (failed login, offboarding)
            - last_login_at: Last successful authentication timestamp
            - created_at: Account creation timestamp
            - updated_at: Last profile update timestamp
            ---
            RELATIONSHIPS:
            - Many-to-One with: UserRoleData, DepartmentData
            - One user creates many production plans (1:N with ProductionPlanData)
            ---
            BUSINESS RULES:
            - Passwords stored as hashes only (application hashes before INSERT)
            - Inactive users cannot authenticate
            - username and email are globally unique
            - User deletion is soft (is_active=False); never physical
              to preserve audit trail (created_by references)
            - One user has exactly one role
            - Users without a department are allowed
            """
        },
    )
    user_id = Column(
        String(40),
        primary_key=True,
        server_default=text("'USR_' || gen_random_uuid()::text"),
        unique=True,
        nullable=False
    )
    username = Column(
        String(50),
        unique=True,
        nullable=False
    )
    email = Column(
        String(255),
        unique=True,
        nullable=False
    )
    full_name = Column(
        String(200),
        nullable=True
    )
    hashed_password = Column(
        String(255),
        nullable=False,
        comment="Password hash (bcrypt/argon2). NEVER plaintext."
    )
    role_id = Column(
        String(40),
        ForeignKey('user_role_data.role_id', ondelete='RESTRICT'),
        nullable=False,
        comment="Business role; cannot delete role while users reference it"
    )
    department_id = Column(
        String(40),
        ForeignKey('department_data.department_id', ondelete='RESTRICT'),
        nullable=True,
        comment="Optional department affiliation"
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text('true')
    )
    last_login_at = Column(
        DateTime,
        nullable=True
    )
    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )
    updated_at = Column(
        DateTime,
        nullable=True,
        onupdate=func.now()
    )
    # Relationships
    role = relationship(
        'UserRoleData',
        back_populates='users',
        lazy='joined'
    )
    department = relationship(
        'DepartmentData',
        back_populates='users',
        lazy='joined'
    )
    created_plans = relationship(
        'ProductionPlanData',
        back_populates='created_by',
        lazy='select'
    )


# ========== PRODUCTION PLAN TABLES ==========
class ProductionPlanData(Base):
    '''
    Model defines a table for storing production plan records.

    Each record represents ONE LINE of the planning Excel: a concrete
    (workshop, model, configuration, engine, transmission, quantity, date)
    tuple. The same batch may appear in MULTIPLE records - e.g. when part
    of the batch is carried over to another day, or when the same batch is
    produced in several workshops.
    '''
    __tablename__ = 'production_plan_data'
    __table_args__ = (
        Index('idx_plan_batch', 'batch'),
        Index('idx_plan_batch_date', 'batch_date'),
        Index('idx_plan_batch_batch_date', 'batch', 'batch_date'),
        Index('idx_plan_workshop_id', 'workshop_id'),
        Index('idx_plan_model_id', 'model_id'),
        Index('idx_plan_configuration_id', 'configuration_id'),
        Index('idx_plan_engine_id', 'engine_id'),
        Index('idx_plan_transmission_id', 'transmission_id'),
        Index('idx_plan_created_by', 'created_by_user_id'),
        Index('idx_plan_model_date', 'model_id', 'batch_date'),
        CheckConstraint('quantity >= 0', name='chk_plan_quantity'),
        {
            'comment': """
            PURPOSE: Production plan records (one row per Excel line)
            ---
            COLUMN DESCRIPTION:
            - plan_id: Unique system identifier (PLN_ + 36-character UUID)
            - batch: Batch identifier from Excel (e.g. RAR2628). NOT unique:
              the same batch may be split across days/workshops.
            - batch_date: Date of this plan record (from Excel)
            - workshop_id: Workshop where the batch is produced
            - model_id: Vehicle model (includes bom_product + model_code)
            - configuration_id: Vehicle configuration (comfort, elite, ...)
            - engine_id: Engine used in the batch (references engine_data)
            - transmission_id: Transmission used in the batch (references transmission_data)
            - quantity: Planned quantity for this record
            - comments: Free-text comment from the Excel row
            - created_by_user_id: Who created the plan (audit)
            - created_at / updated_at: Audit timestamps
            ---
            RELATIONSHIPS:
            - Many-to-One with: WorkshopData, ModelData, ConfigurationData,
              EngineData, TransmissionData, UserData
            - One-to-Many with: ProductionPlanDayData (daily breakdown)
            ---
            BUSINESS RULES:
            - One Excel line = one ProductionPlanData record
            - batch is NOT unique: the same batch may appear in several
              records (carry-over to another day, partial production,
              production in several workshops)
            - (batch, batch_date) is also NOT unique: multiple records for
              the same batch on the same date are allowed
            - Duplicates from re-imported Excel are handled by the
              application layer, not by a UNIQUE constraint
            - Total planned quantity per record must equal
              SUM(ProductionPlanDayData.planned_quantity) - enforced in app layer
            - engine and transmission are independent dimensions: any
              combination of (model, configuration, engine, transmission)
              is allowed at the DB level. The application may warn about
              "new" combinations based on historical ProductionPlanData.
            - configuration_to_transmission is a SOFT reference table:
              it is NOT enforced by FK from ProductionPlanData
            - Plans are never physically deleted without their day rows
              (CASCADE on ProductionPlanDayData)
            """
        },
    )
    plan_id = Column(
        String(40),
        primary_key=True,
        server_default=text("'PLN_' || gen_random_uuid()::text"),
        unique=True,
        nullable=False
    )
    batch = Column(
        String(20),
        nullable=False,
        comment="Batch identifier from Excel. NOT unique: may repeat across records."
    )
    batch_date = Column(
        Date,
        nullable=False,
        comment="Date of this plan record (from Excel)"
    )
    workshop_id = Column(
        String(40),
        ForeignKey('workshop_data.workshop_id', ondelete='RESTRICT'),
        nullable=False,
        comment="Workshop where the batch is produced"
    )
    model_id = Column(
        String(40),
        ForeignKey('model_data.model_id', ondelete='RESTRICT'),
        nullable=False,
        comment="Vehicle model (bom_product + model_code are in ModelData)"
    )
    configuration_id = Column(
        String(40),
        ForeignKey('configuration_data.configuration_id', ondelete='RESTRICT'),
        nullable=False,
        comment="Vehicle configuration (use 'no data' if unknown)"
    )
    engine_id = Column(
        String(40),
        ForeignKey('engine_data.engine_id', ondelete='RESTRICT'),
        nullable=False,
        comment="Engine used in the batch (use 'no data' if unknown)"
    )
    transmission_id = Column(
        String(40),
        ForeignKey('transmission_data.transmission_id', ondelete='RESTRICT'),
        nullable=False,
        comment="Transmission used in the batch (use 'no data' if unknown)"
    )
    quantity = Column(
        Integer,
        nullable=False,
        comment="Planned quantity for this record"
    )
    comments = Column(
        Text,
        nullable=True
    )
    created_by_user_id = Column(
        String(40),
        ForeignKey('user_data.user_id', ondelete='SET NULL'),
        nullable=True,
        comment="User who created the plan (audit)"
    )
    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )
    updated_at = Column(
        DateTime,
        nullable=True,
        onupdate=func.now()
    )
    # Relationships
    workshop = relationship(
        'WorkshopData',
        back_populates='production_plans',
        lazy='joined'
    )
    model = relationship(
        'ModelData',
        back_populates='production_plans',
        lazy='joined'
    )
    configuration = relationship(
        'ConfigurationData',
        back_populates='production_plans',
        lazy='joined'
    )
    engine = relationship(
        'EngineData',
        back_populates='production_plans',
        lazy='joined'
    )
    transmission = relationship(
        'TransmissionData',
        back_populates='production_plans',
        lazy='joined'
    )
    created_by = relationship(
        'UserData',
        back_populates='created_plans',
        lazy='joined'
    )
    days = relationship(
        'ProductionPlanDayData',
        back_populates='plan',
        lazy='selectin',
        cascade='all, delete-orphan'
    )
    # Properties
    @property
    def total_planned_quantity(self):
        """Sum of daily planned quantities for this record."""
        return sum(day.planned_quantity for day in self.days) if self.days else 0

    @property
    def total_actual_quantity(self):
        """Sum of daily actual quantities (where reported)."""
        return sum(
            (day.actual_quantity or 0) for day in self.days
        ) if self.days else 0

    @property
    def is_consistent(self):
        """Record quantity matches sum of daily planned quantities."""
        return self.total_planned_quantity == self.quantity


class ProductionPlanDayData(Base):
    '''
    Model defines a table for storing daily quantities of a plan record.

    One record = one day of one plan record. The monthly Excel view
    (columns 1..31) is rebuilt by aggregating these rows.
    '''
    __tablename__ = 'production_plan_day_data'
    __table_args__ = (
        UniqueConstraint('plan_id', 'plan_date', name='uq_plan_day'),
        Index('idx_plan_day_plan_id', 'plan_id'),
        Index('idx_plan_day_plan_date', 'plan_date'),
        Index('idx_plan_day_date_plan', 'plan_date', 'plan_id'),
        CheckConstraint('planned_quantity >= 0', name='chk_plan_day_planned'),
        CheckConstraint(
            'actual_quantity IS NULL OR actual_quantity >= 0',
            name='chk_plan_day_actual'
        ),
        {
            'comment': """
            PURPOSE: Daily breakdown of a production plan record
            ---
            COLUMN DESCRIPTION:
            - plan_day_id: Unique system identifier (PLD_ + 36-character UUID)
            - plan_id: Parent plan record (references production_plan_data)
            - plan_date: Calendar date of production
            - planned_quantity: Planned quantity for this date
            - actual_quantity: Actual quantity reported for this date
            ---
            RELATIONSHIPS:
            - Many-to-One with: ProductionPlanData
            ---
            BUSINESS RULES:
            - One plan record has at most one row per date (uq_plan_day)
            - The sum of planned_quantity across days should equal
              ProductionPlanData.quantity (checked in application layer)
            - actual_quantity is optional and filled after production
            - Rows are deleted automatically when the parent record is deleted
            """
        },
    )
    plan_day_id = Column(
        String(40),
        primary_key=True,
        server_default=text("'PLD_' || gen_random_uuid()::text"),
        unique=True,
        nullable=False
    )
    plan_id = Column(
        String(40),
        ForeignKey('production_plan_data.plan_id', ondelete='CASCADE'),
        nullable=False
    )
    plan_date = Column(
        Date,
        nullable=False
    )
    planned_quantity = Column(
        Integer,
        nullable=False,
        comment="Planned quantity for this date"
    )
    actual_quantity = Column(
        Integer,
        nullable=True,
        comment="Actual quantity for this date (filled after production)"
    )
    # Relationships
    plan = relationship(
        'ProductionPlanData',
        back_populates='days'
    )


# ========== JUNCTION TABLES ==========
class PartToBox(Base):
    '''
    Junction table used to organize many-to-many relationships
    between two main entities: PartData and BoxData.
    '''
    __tablename__ = 'part_to_box'
    __table_args__ = (
        Index('idx_ptb_part_id', 'part_id'),
        Index('idx_ptb_box_id', 'box_id'),
        Index('idx_ptb_composite', 'part_id', 'box_id'),
        {
            'comment': """
            PURPOSE: Many-to-many relationship: Parts ↔ Boxes
            ---
            COLUMN DESCRIPTION:
            - part_id: References part_data
            - box_id: References box_data
            - part_per_box: Quantity of parts per box
            ---
            BUSINESS RULES:
            - Defines packaging configuration for parts
            - Used for warehouse capacity planning
            """
        },
    )
    part_id = Column(
        String(40),
        ForeignKey('part_data.part_id', ondelete='CASCADE'),
        primary_key=True
    )
    box_id = Column(
        String(40),
        ForeignKey('box_data.box_id', ondelete='RESTRICT'),
        primary_key=True,
        comment="The box cannot be removed if it is used by parts!"
    )
    part_per_box = Column(
        Integer,
        CheckConstraint('part_per_box > 0'),
        nullable=True
    )
    # Relationships
    part = relationship(
        'PartData',
        back_populates='boxes'
    )
    box = relationship(
        'BoxData',
        back_populates='parts'
    )


class PartToModel(Base):
    '''
    Junction table used to organize many-to-many relationships
    between two main entities: PartData and ModelData.
    '''
    __tablename__ = 'part_to_model'
    __table_args__ = (
        Index('idx_ptm_part_id', 'part_id'),
        Index('idx_ptm_model_id', 'model_id'),
        Index('idx_ptm_configuration_id', 'configuration_id'),
        Index('idx_ptm_composite', 'part_id', 'model_id'),
        Index('idx_ptm_active', 'is_active'),
        {
            'comment': """
            PURPOSE: Many-to-many relationship: Parts ↔ Vehicle Models with configuration
            ---
            COLUMN DESCRIPTION:
            - part_id: References part_data
            - model_id: References model_data
            - configuration_id: References configuration_data
            - part_per_vehicle: Quantity used per vehicle for this configuration
            - is_active: Whether this part is active for this specific model
            - deactivated_at: When this association was deactivated
            - deactivated_by_breakpoint_id: Which breakpoint caused deactivation
            ---
            BUSINESS RULES:
            - Defines which parts go into which vehicle models with specific configuration
            - Different configurations may use different quantities of the same part
            - Used for BOM configuration and costing
            - A part can be active for some models and inactive for others
            - Universal parts have multiple active PartToModel records
            - A part is considered "fully active" if it has at least one active PartToModel
            """
        },
    )
    part_id = Column(
        String(40),
        ForeignKey('part_data.part_id', ondelete='CASCADE'),
        primary_key=True
    )
    model_id = Column(
        String(40),
        ForeignKey('model_data.model_id', ondelete='RESTRICT'),
        primary_key=True
    )
    configuration_id = Column(
        String(40),
        ForeignKey('configuration_data.configuration_id', ondelete='RESTRICT'),
        primary_key=True
    )
    part_per_vehicle = Column(
        SmallInteger,
        CheckConstraint('part_per_vehicle > 0'),
        nullable=True
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text('true'),
        comment="Whether this part is active for this specific model"
    )
    deactivated_by_breakpoint_id = Column(
        String(40),
        ForeignKey('breakpoint_data.breakpoint_id', ondelete='SET NULL'),
        nullable=True,
        comment="Which breakpoint caused deactivation for this model"
    )
    # Relationships
    part = relationship(
        'PartData',
        back_populates='models'
    )
    model = relationship(
        'ModelData',
        back_populates='parts'
    )
    configuration = relationship(
        'ConfigurationData',
        back_populates='part_models'
    )
    deactivation_breakpoint = relationship(
        'BreakpointData',
        foreign_keys=[deactivated_by_breakpoint_id],
        lazy='joined',
        back_populates='deactivated_part_models'
    )
    # Properties
    @property
    def deactivated_at(self):
        """Deactivation date derived from breakpoint_date"""
        if self.deactivated_by_breakpoint_id and self.deactivation_breakpoint:
            return self.deactivation_breakpoint.breakpoint_date
        return None


class PartToLine(Base):
    '''
    Junction table used to organize many-to-many relationships
    between two main entities: PartData and LineData.
    '''
    __tablename__ = 'part_to_line'
    __table_args__ = (
        Index('idx_ptl_part_id', 'part_id'),
        Index('idx_ptl_line_id', 'line_id'),
        Index('idx_ptl_composite', 'part_id', 'line_id'),
        {
            'comment': """
            PURPOSE: Many-to-many relationship: Parts ↔ Production Lines
            ---
            COLUMN DESCRIPTION:
            - part_id: References part_data
            - line_id: References line_data
            ---
            BUSINESS RULES:
            - Defines which parts are installed on which lines
            - Used for production scheduling and line balancing
            """
        },
    )
    part_id = Column(
        String(40),
        ForeignKey('part_data.part_id', ondelete='CASCADE'),
        primary_key=True
    )
    line_id = Column(
        String(40),
        ForeignKey('line_data.line_id', ondelete='RESTRICT'),
        primary_key=True,
        comment="The line cannot be deleted if parts are installed on it!"
    )
    # Relationships
    part = relationship(
        'PartData',
        back_populates='lines'
    )
    line = relationship(
        'LineData',
        back_populates='parts'
    )


class PartToBreakpoint(Base):
    '''
    Junction table used to organize many-to-many relationships
    between two main entities: PartData and BreakpointData.
    '''
    __tablename__ = 'part_to_breakpoint'
    __table_args__ = (
        Index('idx_ptbkp_new_part', 'new_part_id'),
        Index('idx_ptbkp_old_part', 'old_part_id'),
        Index('idx_ptbkp_breakpoint', 'breakpoint_id'),
        Index('idx_ptbkp_model', 'model_id'),
        Index('idx_ptbkp_model_breakpoint', 'model_id', 'breakpoint_id'),
        UniqueConstraint('new_part_id', 'breakpoint_id', 'model_id',
                         name='uq_ptbkp_unique'),
        {
            'comment': """
            PURPOSE: Links part versions through technical changes (breakpoints)
            ---
            COLUMN DESCRIPTION:
            - new_part_id: New/current version of the part (references part_data)
            - old_part_id: Previous version of the part (references part_data)  
            - breakpoint_id: Technical change that caused this version transition
            - model_id: Model this change applies to (CRITICAL for universal parts)
            ---
            BUSINESS RULES:
            - A breakpoint ALWAYS applies to a specific model
            - Universal parts have multiple PartToBreakpoint records (one per model)
            - Part is fully deactivated only when ALL model associations are inactive
            - All part data (including all relationships) is stored in part_data
            - All information accessed through part_data relationships
            """
        },
    )
    new_part_id = Column(
        String(40),
        ForeignKey('part_data.part_id', ondelete='RESTRICT'),
        primary_key=True,
        nullable=True,
        comment="New/current version of the part (NULL for DELETE)"
    )
    old_part_id = Column(
        String(40),
        ForeignKey('part_data.part_id', ondelete='RESTRICT'),
        primary_key=True,
        nullable=True,
        comment="Previous version of the part (NULL for ADD)"
    )
    breakpoint_id = Column(
        String(40),
        ForeignKey('breakpoint_data.breakpoint_id', ondelete='RESTRICT'),
        primary_key=True,
        comment="Technical change that triggered this version transition"
    )
    model_id = Column(
        String(40),
        ForeignKey('model_data.model_id', ondelete='RESTRICT'),
        primary_key=True,
        comment="Model this change applies to (must match PartToModel.model_id)"
    )
    # Relationships
    new_part = relationship(
        'PartData',
        foreign_keys=[new_part_id],
        back_populates='new_versions',
        lazy='joined'
    )
    old_part = relationship(
        'PartData',
        foreign_keys=[old_part_id],
        back_populates='old_versions',
        lazy='joined'
    )
    breakpoint = relationship(
        'BreakpointData',
        back_populates='part_transitions',
        lazy='joined'
    )
    model = relationship(
        'ModelData',
        foreign_keys=[model_id],
        lazy='joined'
    )


class BoxToPallet(Base):
    '''
    Junction table used to organize many-to-many relationships
    between main entities: PartData, BoxData and PalletData.
    '''
    __tablename__ = 'box_to_pallet'
    __table_args__ = (
        Index('idx_btp_box_id', 'box_id'),
        Index('idx_btp_pallet_id', 'pallet_id'),
        Index('idx_btp_part_id', 'part_id'),
        Index('idx_btp_composite', 'box_id', 'pallet_id', 'part_id'),
        {
            'comment': """
            PURPOSE: Many-to-many relationship: Boxes ↔ Pallets with Part association
            ---
            COLUMN DESCRIPTION:
            - part_id: References part_data (which part uses this box-pallet combination)
            - box_id: References box_data
            - pallet_id: References pallet_data
            - box_per_pallet: Quantity of boxes per pallet
            ---
            BUSINESS RULES:
            - Defines pallet loading configuration
            - Optimizes transportation and warehouse space utilization
            """
        },
    )
    part_id = Column(
        String(40),
        ForeignKey('part_data.part_id', ondelete='CASCADE'),
        primary_key=True
    )
    box_id = Column(
        String(40),
        ForeignKey('box_data.box_id', ondelete='CASCADE'),
        primary_key=True
    )
    pallet_id = Column(
        String(40),
        ForeignKey('pallet_data.pallet_id', ondelete='RESTRICT'),
        primary_key=True,
        comment="The pallet cannot be removed if it is used by boxes!"
    )
    box_per_pallet = Column(
        SmallInteger,
        CheckConstraint('box_per_pallet > 0'),
        nullable=True
    )
    # Relationships
    part = relationship(
        'PartData',
        back_populates='box_pallet_combinations'
    )
    box = relationship(
        'BoxData',
        back_populates='pallets'
    )
    pallet = relationship(
        'PalletData',
        back_populates='boxes'
    )


class ConfigurationToTransmission(Base):
    '''
    Junction table defining which transmissions are allowed for
    which vehicle configurations.
    '''
    __tablename__ = 'configuration_to_transmission'
    __table_args__ = (
        Index('idx_cfg_trn_configuration', 'configuration_id'),
        Index('idx_cfg_trn_transmission', 'transmission_id'),
        Index('idx_cfg_trn_composite', 'configuration_id', 'transmission_id'),
        {
            'comment': """
            PURPOSE: Allow-list of valid (configuration, transmission) combinations
            ---
            COLUMN DESCRIPTION:
            - configuration_id: References configuration_data
            - transmission_id: References transmission_data
            - is_active: Whether this combination is currently allowed
            - notes: Why/when this combination was added or disabled
            ---
            RELATIONSHIPS:
            - Many-to-One with: ConfigurationData, TransmissionData
            ---
            BUSINESS RULES:
            - A configuration may be produced with multiple transmissions
              (e.g. comfort can be 4x4 or 4x2)
            - A transmission may be used by multiple configurations
              (e.g. 4x4 can be comfort, elite, premium)
            - Therefore the relationship is Many-to-Many
            - This table is master data: it exists even if no production
              plans have been created yet
            - Application MUST validate ProductionPlanData inserts against
              this table (is_active=True)
            - Rows are never physically deleted; use is_active=False to
              disable a combination without losing history
            """
        },
    )
    configuration_id = Column(
        String(40),
        ForeignKey('configuration_data.configuration_id', ondelete='CASCADE'),
        primary_key=True,
        comment="Configuration side of the allowed combination"
    )
    transmission_id = Column(
        String(40),
        ForeignKey('transmission_data.transmission_id', ondelete='RESTRICT'),
        primary_key=True,
        comment="Transmission side; cannot delete transmission while allowed for any configuration"
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text('true'),
        comment="Whether this combination is currently allowed for new plans"
    )
    notes = Column(
        Text,
        nullable=True
    )
    # Relationships
    configuration = relationship(
        'ConfigurationData',
        back_populates='allowed_transmissions'
    )
    transmission = relationship(
        'TransmissionData',
        back_populates='allowed_configurations'
    )
