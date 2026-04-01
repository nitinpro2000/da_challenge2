"""
vendor_service_fetch.py

Fetches vendor service fields from the `public.vendor_service` table
based on whether the request is a renewal or addition, and for one or
more service IDs.

Rules:
  - Single service ID  → return the relevant fields as a dict.
  - Multiple service IDs → for scalar columns (text, char, bool, int,
    float, numeric, date, timestamp, uuid …) return the value only when
    ALL services share the same value, otherwise omit the key.
    For JSONB columns → return the *union* of values across all services.
"""

import asyncio
import json
from typing import Any

import asyncpg


# ---------------------------------------------------------------------------
# Column definitions  (all names are exact DB column names)
# ---------------------------------------------------------------------------

# Columns that apply to BOTH renewal and addition
COMMON_COLUMNS: list[str] = [
    "department",
    "internal_owners",                            # jsonb
    "is_business_critical",
    "business_critical_desc",
    "flg_personal_connection",
    "personal_connection_desc",
    "is_research_soft_dollar_service",
    "aml_check_result",
    "flg_cost_reasonable_in_relation",
    "flg_service_use_other_than_research",
    "service_use_percentage",
    "service_use_percentage_other",
    "vendor_to_be_reviewed_frequency",
    "vendor_to_be_reviewed_frequency_desc",
    "flg_review_by_conflicts_committee",
    "service_cost_allocated_to",
    "service_cost_allocated_to_desc",
    "service_cost_allocated_to_categories",       # jsonb
    "service_cost_allocated_to_category_desc_values",  # jsonb
    "product_or_service_is",
    "is_service_safe_harbor",
    "is_service_safe_harbor_desc",
    "research_expense_amount",
    "research_expense_percentage",
    "flg_access_to_customer_information",
    "flg_provides_cpc",
    "cyber_review_cadence_id",
    "last_cyber_diligence_date",
    "aml_check_completed_date",
]

# Columns that apply ONLY to additions
ADDITION_ONLY_COLUMNS: list[str] = [
    "type_of_diligence_desc",
    "type_of_diligence_values",                   # jsonb
    "auto_renews",
    "auto_terminates",
]

# Which of the above are JSONB in Postgres
JSONB_COLUMNS: set[str] = {
    "internal_owners",
    "service_cost_allocated_to_categories",
    "service_cost_allocated_to_category_desc_values",
    "type_of_diligence_values",
}


def _get_columns(is_renewal: bool, is_addition: bool) -> list[str]:
    """Return the ordered list of DB column names for this request type."""
    cols = list(COMMON_COLUMNS)
    if is_addition:
        cols += ADDITION_ONLY_COLUMNS
    return cols


# ---------------------------------------------------------------------------
# JSONB union helpers
# ---------------------------------------------------------------------------

def _union_jsonb(values: list[Any]) -> Any:
    """
    Merge a list of JSONB values (already parsed by asyncpg) into a union.

    Strategy:
      - list of scalars / objects  → deduplicated list preserving order
      - dict / object              → merged dict (later values overwrite)
      - None                       → skipped
    """
    non_null = [v for v in values if v is not None]
    if not non_null:
        return None

    # Collect everything into a flat list, then deduplicate
    merged: list[Any] = []
    seen_strings: set[str] = set()

    for val in non_null:
        items = val if isinstance(val, list) else [val]
        for item in items:
            key = json.dumps(item, sort_keys=True, default=str)
            if key not in seen_strings:
                seen_strings.add(key)
                merged.append(item)

    # If every original value was a plain dict (not a list), return merged dict
    if all(isinstance(v, dict) for v in non_null):
        result: dict = {}
        for v in non_null:
            result.update(v)
        return result

    return merged


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
    dict mapping DB column name → merged value
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

    # -----------------------------------------------------------------------
    # Single service ID → straight dict
    # -----------------------------------------------------------------------
    if len(service_ids) == 1:
        return dict(rows[0])

    # -----------------------------------------------------------------------
    # Multiple service IDs → merge by column type rules
    # -----------------------------------------------------------------------
    result: dict[str, Any] = {}
    for col in columns:
        col_values = [row[col] for row in rows]

        if col in JSONB_COLUMNS:
            # Union of JSONB values
            result[col] = _union_jsonb(col_values)
        else:
            # Scalar: include only when ALL rows agree on the same value
            unique_vals = set(
                json.dumps(v, sort_keys=True, default=str) for v in col_values
            )
            if len(unique_vals) == 1:
                result[col] = col_values[0]
            # else: values differ → omit this key entirely

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
    merged dict of field → value
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
