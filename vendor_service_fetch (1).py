"""
vendor_service_fetch.py

Fetches vendor service fields from the `public.vendor_service` table
based on whether the request is a renewal or addition, and for one or
more service IDs.

Rules:
  - Single service ID  → return the relevant fields as a dict.
  - Multiple service IDs:
      Scalar columns (text, char, numeric, date, timestamp, …)
          → included only when ALL services share the same value.
      JSONB columns → union per column shape:
          internal_owners                           {"values": [...]} — union inner list, deduplicated
          service_cost_allocated_to_categories      [...] — flat array union, deduplicated
          service_cost_allocated_to_category_desc_values  {key: [...]} — dict union per key, deduplicated
          type_of_diligence_values                  [...] — flat array union, deduplicated
"""

import asyncio
import json
from typing import Any

import asyncpg


# ---------------------------------------------------------------------------
# Column definitions  (all names are exact DB column names)
# ---------------------------------------------------------------------------

COMMON_COLUMNS: list[str] = [
    "department",
    "internal_owners",                                # jsonb – {"values": [...]}
    "is_business_critical",
    "business_critical_desc",
    "flg_personal_connection",
    "personal_connection_desc",
    "is_research_soft_dollar_service",
    "aml_check_result",
    "aml_check_completed_date",
    "flg_cost_reasonable_in_relation",
    "flg_service_use_other_than_research",
    "service_use_percentage",
    "service_use_percentage_other",
    "vendor_to_be_reviewed_frequency",
    "vendor_to_be_reviewed_frequency_desc",
    "flg_review_by_conflicts_committee",
    "service_cost_allocated_to",
    "service_cost_allocated_to_desc",
    "service_cost_allocated_to_categories",           # jsonb – [...]
    "service_cost_allocated_to_category_desc_values", # jsonb – {key: [...]}
    "product_or_service_is",
    "is_service_safe_harbor",
    "is_service_safe_harbor_desc",
    "research_expense_amount",
    "research_expense_percentage",
    "flg_access_to_customer_information",
    "flg_provides_cpc",
    "cyber_review_cadence_id",
    "last_cyber_diligence_date",
]

ADDITION_ONLY_COLUMNS: list[str] = [
    "type_of_diligence_desc",
    "type_of_diligence_values",                       # jsonb – [...]
    "auto_renews",
    "auto_terminates",
]


def _get_columns(is_renewal: bool, is_addition: bool) -> list[str]:
    cols = list(COMMON_COLUMNS)
    if is_addition:
        cols += ADDITION_ONLY_COLUMNS
    return cols


# ---------------------------------------------------------------------------
# JSONB merge strategies
# ---------------------------------------------------------------------------

def _merge_wrapped_list(values: list[Any]) -> dict:
    """
    internal_owners: {"values": [{name, email}, ...]}
    Unions all inner lists, deduplicating by JSON fingerprint.
    Always returns {"values": [...]}.
    """
    seen: set[str] = set()
    merged: list[Any] = []
    for val in values:
        if not isinstance(val, dict):
            continue
        for item in val.get("values", []):
            fp = json.dumps(item, sort_keys=True, default=str)
            if fp not in seen:
                seen.add(fp)
                merged.append(item)
    return {"values": merged}


def _merge_flat_array(values: list[Any]) -> list:
    """
    service_cost_allocated_to_categories, type_of_diligence_values: [...]
    Union of all array elements, deduplicated, order preserved.
    """
    seen: set[str] = set()
    merged: list[Any] = []
    for val in values:
        if not isinstance(val, list):
            continue
        for item in val:
            fp = json.dumps(item, sort_keys=True, default=str)
            if fp not in seen:
                seen.add(fp)
                merged.append(item)
    return merged


def _merge_dict_of_lists(values: list[Any]) -> dict:
    """
    service_cost_allocated_to_category_desc_values: {"legal fees": [...], ...}
    Unions per key — values within each key are deduplicated.
    """
    merged: dict[str, list] = {}
    for val in values:
        if not isinstance(val, dict):
            continue
        for key, items in val.items():
            items = items if isinstance(items, list) else [items]
            if key not in merged:
                merged[key] = []
            seen_in_key = {
                json.dumps(x, sort_keys=True, default=str) for x in merged[key]
            }
            for item in items:
                fp = json.dumps(item, sort_keys=True, default=str)
                if fp not in seen_in_key:
                    seen_in_key.add(fp)
                    merged[key].append(item)
    return merged


# Date columns where we want only the date portion (no time component)
_DATE_ONLY_COLS = {"last_cyber_diligence_date", "aml_check_completed_date"}


def _format_value(col: str, value: Any) -> Any:
    """Strip the time component for date-only columns; pass everything else through."""
    if value is not None and col in _DATE_ONLY_COLS:
        # asyncpg may return a datetime.date or datetime.datetime
        return value.date() if hasattr(value, "time") else value
    return value


# Dispatch: column name → merge function
_JSONB_MERGE_FN: dict[str, Any] = {
    "internal_owners":                                _merge_wrapped_list,
    "service_cost_allocated_to_categories":           _merge_flat_array,
    "service_cost_allocated_to_category_desc_values": _merge_dict_of_lists,
    "type_of_diligence_values":                       _merge_flat_array,
}


def _merge_jsonb(col: str, values: list[Any]) -> Any:
    non_null = [v for v in values if v is not None]
    if not non_null:
        return None
    return _JSONB_MERGE_FN[col](non_null)


# ---------------------------------------------------------------------------
# Core fetch function
# ---------------------------------------------------------------------------

async def fetch_vendor_service_data(
    conn: asyncpg.Connection,
    *,
    is_renewal: bool,
    is_addition: bool,
    service_ids: list[int],
) -> dict[str, Any]:
    """
    Fetch and merge vendor_service data for one or more service IDs.

    Parameters
    ----------
    conn        : active asyncpg connection
    is_renewal  : True if the request is a renewal
    is_addition : True if the request is an addition
    service_ids : non-empty list of service_id values

    Returns
    -------
    dict mapping DB column name -> merged value
    """
    if not service_ids:
        raise ValueError("service_ids must not be empty")

    columns      = _get_columns(is_renewal, is_addition)
    select_str   = ", ".join(columns)
    placeholders = ", ".join(f"${i+1}" for i in range(len(service_ids)))

    query = f"""
        SELECT {select_str}
        FROM   public.vendor_service
        WHERE  service_id IN ({placeholders})
    """

    rows = await conn.fetch(query, *service_ids)

    if not rows:
        return {}

    # Single service ID -> straight dict (apply date formatting)
    if len(service_ids) == 1:
        return {col: _format_value(col, rows[0][col]) for col in columns}

    # Multiple service IDs -> merge by column type rules
    result: dict[str, Any] = {}
    for col in columns:
        col_values = [row[col] for row in rows]

        if col in _JSONB_MERGE_FN:
            result[col] = _merge_jsonb(col, col_values)
        else:
            # Scalar: include only when ALL rows share the same value
            unique_vals = {
                json.dumps(v, sort_keys=True, default=str) for v in col_values
            }
            if len(unique_vals) == 1:
                result[col] = _format_value(col, col_values[0])
            # else: values differ -> omit key entirely

    return result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def get_service_data(
    dsn: str,
    *,
    is_renewal: bool,
    is_addition: bool,
    service_ids: list[int],
) -> dict[str, Any]:
    """
    Open a connection, fetch data, and return the merged result dict.

    Parameters
    ----------
    dsn         : asyncpg DSN, e.g. "postgresql://user:pass@host/db"
    is_renewal  : flag for renewal
    is_addition : flag for addition
    service_ids : list of service_id integers

    Returns
    -------
    merged dict of DB column name -> value
    """
    conn = await asyncpg.connect(dsn)
    try:
        return await fetch_vendor_service_data(
            conn,
            is_renewal=is_renewal,
            is_addition=is_addition,
            service_ids=service_ids,
        )
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Example usage
# ---------------------------------------------------------------------------

async def _demo() -> None:
    DSN = "postgresql://user:password@localhost/mydb"

    # --- Single service, renewal ---
    result = await get_service_data(
        DSN,
        is_renewal=True,
        is_addition=False,
        service_ids=[10000343],
    )
    print("=== Single service (renewal) ===")
    print(json.dumps(result, indent=2, default=str))

    # --- Multiple services, addition ---
    result = await get_service_data(
        DSN,
        is_renewal=False,
        is_addition=True,
        service_ids=[10000343, 10000344],
    )
    print("\n=== Multiple services (addition) ===")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(_demo())
