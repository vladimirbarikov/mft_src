# pylint: disable=too-many-lines
# pylint: disable=line-too-long
"""
SQL DDL for database-level audit triggers.

This module contains ONLY SQL text. Execution happens in:
    - dags/tasks/initializer.py   (once at startup, idempotent)
    - database/user_roles.py      (post-step when a new PG role is created)

CONTENTS:
    AUDIT_FUNCTION_DDL          - CREATE OR REPLACE FUNCTION audit_trigger_fn()
    AUDIT_HARDENING_STATEMENTS  - list of single-statement hardening DDL.
                                  Must be executed one by one (SQLAlchemy 1.4 +
                                  psycopg2 reject multi-statement text()).
    AUDITED_TABLES              - (table_name, pk_column, extra_skip_csv) tuples,
                                  used in step 4 to CREATE TRIGGER per table.

SECURITY MODEL:
    - audit_trigger_fn() is SECURITY DEFINER, owned by DB_USER (postgres).
      This allows the trigger to write to audit_log_data even when the caller
      role (viewer/editor) has no INSERT on it.
    - EXECUTE on the function is revoked from PUBLIC.
    - Roles are classified as "admin" or "non-admin" by the presence of the
      DELETE privilege on audit_log_data:
          DatabaseAdmin   - ALL privileges on audit_log_data  (admin)
          DatabaseEditor  - SELECT, INSERT, UPDATE            (non-admin)
          DatabaseViewer  - SELECT                            (non-admin)
      Non-admin roles lose:
          - all access to audit_log_data
          - SELECT on audit/security columns of business tables
          - SELECT on sensitive columns of user_data

IDENTITY PROPAGATION:
    Python forwards identity into PostgreSQL via two transaction-scoped GUCs:
        set_config('app.current_user_id',  '<USR_...>', true)  -- preferred
        set_config('app.current_username', '<sub>',     true)  -- fallback
    The trigger prefers the first, falls back to the second. Unresolved
    identity is logged as NULL (anonymous).

KNOWN LIMITATION (PG 13):
    Views created with `CREATE VIEW` execute with the OWNER's privileges.
    `WITH (security_invoker = true)` is available only in PG 15+.
    Column-level REVOKE/GRANT on tables does NOT protect columns reachable
    through a view. See TODO_VIEWS note at the bottom of this module.
"""


# ============================================================
# 1. Trigger function
# ============================================================

AUDIT_FUNCTION_DDL = r"""
CREATE OR REPLACE FUNCTION public.audit_trigger_fn()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_uid           TEXT;
    v_username      TEXT;
    v_user_id       TEXT;
    v_record_id     TEXT;
    v_pk_arg        TEXT;
    v_pk_columns    TEXT[];
    v_pk_count      INT;
    v_old_json      JSONB;
    v_new_json      JSONB;
    v_old_value     JSONB;
    v_new_value     JSONB;
    v_field_key     TEXT;
    v_skip_fields   TEXT[];
BEGIN
    v_uid      := NULLIF(current_setting('app.current_user_id',  true), '');
    v_username := NULLIF(current_setting('app.current_username', true), '');

    IF v_uid IS NOT NULL THEN
        SELECT user_id INTO v_user_id
        FROM public.user_data WHERE user_id = v_uid;
    ELSIF v_username IS NOT NULL THEN
        SELECT user_id INTO v_user_id
        FROM public.user_data WHERE username = v_username;
    END IF;

    IF TG_NARGS < 1 THEN
        RAISE EXCEPTION
            'audit_trigger_fn: PK column(s) must be passed as first trigger argument';
    END IF;
    v_pk_arg     := TG_ARGV[0];
    v_pk_columns := string_to_array(v_pk_arg, ',');
    v_pk_count   := array_length(v_pk_columns, 1);

    -- v4: skip list includes PK columns (all of them) + audit cols + extras
    v_skip_fields := ARRAY['created_at', 'updated_at'];
    IF v_pk_count > 0 THEN
        v_skip_fields := v_skip_fields || v_pk_columns;
    END IF;
    IF TG_NARGS >= 2 AND TG_ARGV[1] <> '' THEN
        v_skip_fields := v_skip_fields || string_to_array(TG_ARGV[1], ',');
    END IF;

    IF TG_OP = 'INSERT' THEN
        v_new_json  := to_jsonb(NEW);
        -- v4: single PK -> scalar; composite PK -> JSON object
        IF v_pk_count = 1 THEN
            v_record_id := v_new_json ->> v_pk_columns[1];
        ELSE
            SELECT jsonb_object_agg(k, v_new_json -> k)::text
            INTO v_record_id
            FROM unnest(v_pk_columns) AS k;
        END IF;

        INSERT INTO public.audit_log_data
            (table_name, record_id, field_name, old_value, new_value, action, user_id)
        VALUES
            (TG_TABLE_NAME, v_record_id, '*',
             NULL, v_new_json::text, 'INSERT', v_user_id);
        RETURN NEW;

    ELSIF TG_OP = 'DELETE' THEN
        v_old_json  := to_jsonb(OLD);
        IF v_pk_count = 1 THEN
            v_record_id := v_old_json ->> v_pk_columns[1];
        ELSE
            SELECT jsonb_object_agg(k, v_old_json -> k)::text
            INTO v_record_id
            FROM unnest(v_pk_columns) AS k;
        END IF;

        INSERT INTO public.audit_log_data
            (table_name, record_id, field_name, old_value, new_value, action, user_id)
        VALUES
            (TG_TABLE_NAME, v_record_id, '*',
             v_old_json::text, NULL, 'DELETE', v_user_id);
        RETURN OLD;

    ELSE  -- UPDATE
        v_old_json  := to_jsonb(OLD);
        v_new_json  := to_jsonb(NEW);
        IF v_pk_count = 1 THEN
            v_record_id := v_new_json ->> v_pk_columns[1];
        ELSE
            SELECT jsonb_object_agg(k, v_new_json -> k)::text
            INTO v_record_id
            FROM unnest(v_pk_columns) AS k;
        END IF;

        FOR v_field_key IN SELECT jsonb_object_keys(v_new_json) LOOP
            CONTINUE WHEN v_field_key = ANY(v_skip_fields);

            v_new_value := v_new_json -> v_field_key;
            v_old_value := v_old_json -> v_field_key;

            CONTINUE WHEN v_new_value IS NOT DISTINCT FROM v_old_value;

            INSERT INTO public.audit_log_data
                (table_name, record_id, field_name, old_value, new_value, action, user_id)
            VALUES
                (TG_TABLE_NAME, v_record_id, v_field_key,
                 v_old_value #>> '{}',
                 v_new_value #>> '{}',
                 'UPDATE', v_user_id);
        END LOOP;
        RETURN NEW;
    END IF;
END;
$$;
"""


# ============================================================
# 2. Hardening statements (executed one by one)
# ============================================================
# Order matters:
#   - stmt 3 must run BEFORE stmt 4/5, because the "non-admin role" set
#     is determined by has_table_privilege(..., 'audit_log_data', 'DELETE')
#     evaluated on the CURRENT grant state. Revoking audit_log_data from
#     non-admin roles first makes the follow-up classification consistent
#     across re-runs.

AUDIT_HARDENING_STATEMENTS = [

    # ---------------------------------------------------------
    # 2.1. Function: revoke EXECUTE from PUBLIC
    # ---------------------------------------------------------
    "REVOKE EXECUTE ON FUNCTION public.audit_trigger_fn() FROM PUBLIC",

    # ---------------------------------------------------------
    # 2.2. Function: documentation
    # ---------------------------------------------------------
    """COMMENT ON FUNCTION public.audit_trigger_fn() IS
'Generic row-level audit trigger function (SECURITY DEFINER). '
'Identity: app.current_user_id (uid) preferred, app.current_username (sub) fallback; '
'both forwarded from Python via set_config(..., is_local=true) on each transaction. '
'Unresolved identity is logged as NULL (anonymous). '
'Trigger args: 1) PK column name (mandatory), '
'2) comma-separated extra skip columns (optional). '
'INSERT/DELETE emit one row with field_name = ''*'' and a full JSON snapshot; '
'UPDATE emits one row per changed field.'""",

    # ---------------------------------------------------------
    # 2.3. audit_log_data: revoke from all non-admin roles
    #      Admin detection: has DELETE privilege on audit_log_data.
    # ---------------------------------------------------------
    """
    DO $$
    DECLARE
        r RECORD;
    BEGIN
        FOR r IN
            SELECT rolname
            FROM pg_roles
            WHERE rolcanlogin
              AND NOT rolsuper
              AND NOT has_table_privilege(
                    rolname, 'public.audit_log_data', 'DELETE')
              AND (
                    has_table_privilege(
                        rolname, 'public.audit_log_data', 'SELECT')
                 OR has_table_privilege(
                        rolname, 'public.audit_log_data', 'INSERT')
              )
        LOOP
            EXECUTE format(
                'REVOKE ALL ON TABLE public.audit_log_data FROM %I',
                r.rolname);
            RAISE NOTICE
                'audit_log_data: revoked all from role %', r.rolname;
        END LOOP;
    END $$;
    """,

    # ---------------------------------------------------------
    # 2.4. Business tables: hide audit/security columns
    #      from non-admin roles via column-level GRANTs.
    #      Excludes user_data (handled separately in 2.5) and
    #      audit_log_data (handled in 2.3).
    # ---------------------------------------------------------
    """
    DO $$
    DECLARE
        r RECORD;
        t RECORD;
        col_list TEXT;
        hidden_cols TEXT[] := ARRAY[
            'created_at',
            'updated_at',
            'created_by_user_id',
            'updated_by_user_id',
            'hashed_password'
        ];
    BEGIN
        FOR r IN
            SELECT rolname
            FROM pg_roles
            WHERE rolcanlogin
              AND NOT rolsuper
              AND NOT has_table_privilege(
                    rolname, 'public.audit_log_data', 'DELETE')
        LOOP
            FOR t IN
                SELECT DISTINCT table_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name NOT IN ('audit_log_data', 'user_data')
                  AND column_name = ANY(hidden_cols)
            LOOP
                EXECUTE format(
                    'REVOKE SELECT ON TABLE public.%I FROM %I',
                    t.table_name, r.rolname);

                SELECT string_agg(quote_ident(column_name), ', ')
                INTO col_list
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = t.table_name
                  AND column_name <> ALL(hidden_cols);

                IF col_list IS NOT NULL THEN
                    EXECUTE format(
                        'GRANT SELECT (%s) ON TABLE public.%I TO %I',
                        col_list, t.table_name, r.rolname);
                END IF;
            END LOOP;
        END LOOP;
    END $$;
    """,

    # ---------------------------------------------------------
    # 2.5. user_data: expose only (user_id, username, full_name)
    #      to non-admin roles. Everything else hidden:
    #      email, hashed_password, role_id, department_id,
    #      is_active, last_login_at, created_at, updated_at,
    #      created_by_user_id, updated_by_user_id.
    # ---------------------------------------------------------
    """
    DO $$
    DECLARE
        r RECORD;
    BEGIN
        FOR r IN
            SELECT rolname
            FROM pg_roles
            WHERE rolcanlogin
              AND NOT rolsuper
              AND NOT has_table_privilege(
                    rolname, 'public.audit_log_data', 'DELETE')
        LOOP
            EXECUTE format(
                'REVOKE ALL ON TABLE public.user_data FROM %I',
                r.rolname);
            EXECUTE format(
                'GRANT SELECT (user_id, username, full_name) '
                'ON TABLE public.user_data TO %I',
                r.rolname);
        END LOOP;
    END $$;
    """,

    # ---------------------------------------------------------
    # TODO_VIEWS (PG 13 limitation):
    # Views created with CREATE VIEW execute with the OWNER's
    # privileges. `WITH (security_invoker = true)` is PG 15+.
    # Column-level REVOKE/GRANT on base tables does NOT protect
    # columns reachable through a view.
    #
    # If database/views.py exposes any of the hidden columns
    # (created_at, updated_at, created_by_user_id,
    #  updated_by_user_id, hashed_password), non-admin roles
    # will still see them via the view.
    #
    # Options when views.py is reviewed:
    #   (a) REVOKE ALL ON <view> FROM non-admin roles
    #   (b) Recreate views without hidden columns in views.py
    #   (c) Column-level REVOKE/GRANT on each view (same pattern as 2.4)
    # ---------------------------------------------------------
]


# ============================================================
# 2b. Schema migrations (idempotent DDL for audit_log_data)
# ============================================================
# Widens record_id from VARCHAR(40) to TEXT to hold composite PKs
# as JSON. Widening is lossless and safe on re-run.

AUDIT_SCHEMA_MIGRATIONS = [
    # (existing) widen record_id
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'audit_log_data'
              AND column_name = 'record_id'
              AND data_type <> 'text'
        ) THEN
            ALTER TABLE public.audit_log_data
                ALTER COLUMN record_id TYPE TEXT;
            RAISE NOTICE 'audit_log_data.record_id widened to TEXT';
        END IF;
    END $$;
    """,
]


# ============================================================
# 2c. Views hardening (runs AFTER create_views in initializer.py)
# ============================================================
# PG 13 note: views have no security_invoker option (PG 15+). Column-level
# REVOKE/GRANT on the view itself still works, so we apply the same pattern
# as for base tables. CREATE OR REPLACE VIEW preserves grants, but views
# created for the first time inherit SELECT via ALTER DEFAULT PRIVILEGES,
# hence this must run AFTER create_views.
#
# `version_created_at` is v_part_change_summary's alias for p.created_at -
# hidden_cols includes it explicitly.

AUDIT_VIEW_HARDENING_STATEMENTS = [
    """
    DO $$
    DECLARE
        r RECORD;
        v RECORD;
        col_list TEXT;
        view_hidden_cols TEXT[] := ARRAY[
            'created_at',
            'updated_at',
            'created_by_user_id',
            'updated_by_user_id',
            'hashed_password',
            'version_created_at'
        ];
    BEGIN
        FOR r IN
            SELECT rolname FROM pg_roles
            WHERE rolcanlogin AND NOT rolsuper
              AND NOT has_table_privilege(
                    rolname, 'public.audit_log_data', 'DELETE')
        LOOP
            FOR v IN
                SELECT DISTINCT table_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name LIKE 'v_%'
                  AND column_name = ANY(view_hidden_cols)
            LOOP
                EXECUTE format('REVOKE ALL ON TABLE public.%I FROM %I',
                    v.table_name, r.rolname);

                SELECT string_agg(quote_ident(column_name), ', ')
                INTO col_list
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = v.table_name
                  AND column_name <> ALL (view_hidden_cols);

                IF col_list IS NOT NULL THEN
                    EXECUTE format(
                        'GRANT SELECT (%s) ON TABLE public.%I TO %I',
                        col_list, v.table_name, r.rolname);
                END IF;
            END LOOP;
        END LOOP;
    END $$;
    """,
]


# ============================================================
# 3. Audited tables (populated in step 4)
# ============================================================
# Tuple format: (table_name, pk_column, extra_skip_columns_csv)
# Example:
#     ('box_data', 'box_id', 'box_number,box_vol_m3,box_area_m2')
#
# pk_column is mandatory (passed as TG_ARGV[0]).
# extra_skip_columns_csv is optional (passed as TG_ARGV[1]);
# created_at, updated_at and pk_column are always skipped implicitly.

AUDITED_TABLES = [
    # ---- Core master data (single-column PK) ----
    ('supplier_data',                'supplier_id',     ''),
    ('part_data',                    'part_id',         ''),
    ('box_data',                     'box_id',          'box_number,box_vol_m3,box_area_m2'),
    ('pallet_data',                  'pallet_id',       'pallet_number,pallet_vol_m3,pallet_area_m2'),
    ('model_data',                   'model_id',        ''),
    ('configuration_data',           'configuration_id', ''),
    ('engine_data',                  'engine_id',       ''),
    ('transmission_data',            'transmission_id', ''),
    ('batch_data',                   'batch_id',        ''),
    ('color_data',                   'color_id',        ''),
    ('workshop_data',                'workshop_id',     ''),
    ('line_data',                    'line_id',         ''),
    ('breakpoint_data',              'breakpoint_id',   ''),
    ('breakpoint_checklist_data',    'checklist_id',    ''),
    ('department_data',              'department_id',   ''),
    ('user_role_data',               'role_id',         ''),
    # hashed_password: never log password hashes to audit
    # last_login_at: noise on every successful login
    ('user_data',                    'user_id',         'hashed_password,last_login_at'),
    # ---- Production plan ----
    ('production_plan_data',         'plan_id',         ''),
    ('production_plan_day_data',     'plan_day_id',     ''),
    # ---- Composite PK tables (v4 trigger supports JSON record_id) ----
    ('part_to_box',   'part_id,box_id',                       ''),
    ('part_to_model', 'part_id,model_id,configuration_id',    ''),
    # ---- Deliberately NOT audited ----
    # part_to_breakpoint  -- it IS the change history
    # part_to_color, part_to_line, box_to_pallet,
    # configuration_to_transmission, batch_to_vehicle  -- pure links, low signal
]
