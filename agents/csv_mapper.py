"""LLM fallback for CSV column mapping when heuristic detection fails."""

from __future__ import annotations

import json

from ingest.csv_detect import LucidField, MappingAmbiguity, ResolvedColumnMapping
from llm.provider import LLMProvider

_SYSTEM = """\
You are a CSV column mapping assistant for a personal finance app.
Given a sample of rows from a bank CSV export, identify which CSV column corresponds to each field.

Respond with ONLY a JSON object — no explanation, no markdown fences. Schema:
{
  "date_col": "<exact column header string>",
  "amount_col": "<column header or null if using debit/credit>",
  "debit_col": "<column header or null>",
  "credit_col": "<column header or null>",
  "merchant_col": "<exact column header string>",
  "currency_col": "<column header or null>",
  "sign_rule": "single_amount" or "debit_credit"
}

Rules:
- sign_rule is "single_amount" when one column holds both positive and negative amounts.
- sign_rule is "debit_credit" when outflows and inflows are in separate columns.
- All non-null header values must exactly match one of the provided headers (case-sensitive).
- date_col and merchant_col are required — always provide them.
- Set null for optional fields you cannot identify with confidence.
"""


def resolve_mapping_with_llm(
    llm: LLMProvider,
    preview: dict,
) -> ResolvedColumnMapping:
    """Use the LLM to resolve an ambiguous CSV column mapping.

    *preview* is the dict returned by ``ingest.importer.preview_csv_file``.
    Raises ValueError if the LLM returns an unusable mapping.
    """
    headers: list[str] = preview["headers"]
    sample_rows: list[dict] = preview.get("sample_rows", [])
    encoding: str = preview.get("encoding", "utf-8")
    delimiter: str = preview.get("delimiter", ",")
    ambiguity: MappingAmbiguity = preview["detection"]

    sample_text = f"Available headers: {headers}\n\nSample rows (up to 10):\n"
    for i, row in enumerate(sample_rows[:10]):
        sample_text += f"  Row {i + 1}: {json.dumps(row, ensure_ascii=False)}\n"

    hints = ""
    if ambiguity.missing_required:
        hints += f"\nThe heuristic could not identify: {', '.join(ambiguity.missing_required)}."
    if ambiguity.best_effort:
        hints += f"\nPartial best-effort mapping so far: {ambiguity.best_effort}."

    user_msg = f"Map the columns in this bank CSV export.\n\n{sample_text}{hints}"

    resp = llm.complete(system=_SYSTEM, messages=[{"role": "user", "content": user_msg}])

    raw = (resp.content or "").strip()
    # Strip markdown code fences if the model wraps its response
    if raw.startswith("```"):
        raw = "\n".join(
            line for line in raw.splitlines() if not line.startswith("```")
        ).strip()

    try:
        data: dict = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned non-JSON: {raw[:300]!r}") from exc

    # Validate: every non-null column name must exist in the actual headers
    header_set = set(headers)
    for field_key in ("date_col", "amount_col", "debit_col", "credit_col",
                      "merchant_col", "currency_col"):
        val = data.get(field_key)
        if val is not None and val not in header_set:
            raise ValueError(
                f"LLM returned unknown column {val!r} for {field_key}. "
                f"Known headers: {headers}"
            )

    sign_rule: str = data.get("sign_rule", "single_amount")
    if sign_rule not in ("single_amount", "debit_credit"):
        sign_rule = "single_amount"

    column_map: dict[str, str] = {}
    if data.get("date_col"):
        column_map[LucidField.DATE.value] = data["date_col"]
    if data.get("merchant_col"):
        column_map[LucidField.MERCHANT.value] = data["merchant_col"]
    if sign_rule == "single_amount" and data.get("amount_col"):
        column_map[LucidField.AMOUNT.value] = data["amount_col"]
    if sign_rule == "debit_credit":
        if data.get("debit_col"):
            column_map[LucidField.DEBIT.value] = data["debit_col"]
        if data.get("credit_col"):
            column_map[LucidField.CREDIT.value] = data["credit_col"]
    if data.get("currency_col"):
        column_map[LucidField.CURRENCY.value] = data["currency_col"]

    # Verify required fields are present
    missing: list[str] = []
    if LucidField.DATE.value not in column_map:
        missing.append("date")
    if LucidField.MERCHANT.value not in column_map:
        missing.append("merchant")
    if sign_rule == "single_amount" and LucidField.AMOUNT.value not in column_map:
        missing.append("amount")
    if sign_rule == "debit_credit" and not (
        LucidField.DEBIT.value in column_map or LucidField.CREDIT.value in column_map
    ):
        missing.append("debit or credit")
    if missing:
        raise ValueError(f"LLM mapping is missing required fields: {missing}")

    return ResolvedColumnMapping(
        column_map=column_map,
        sign_rule=sign_rule,
        encoding=encoding,
        delimiter=delimiter,
    )
