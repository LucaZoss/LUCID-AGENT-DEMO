"""Staged REPL startup flow.

State machine:
  MODEL → DATA_SOURCE → [PERSISTENCE → IMPORT → CATEGORIZE → SUMMARY] → REPL

CSV path traverses all stages; DEMO path jumps MODEL → DATA_SOURCE → REPL
(existing onboarding runs inside the REPL loop as before).
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path

# Single-user demo identifiers — shared with repl.py via import
USER_ID = "demo-user-1"
CONV_ID = "demo-conv-1"
ACCOUNT_ID = "demo-account-1"


class StartupStage(Enum):
    MODEL = "model"
    DATA_SOURCE = "data_source"
    PERSISTENCE = "persistence"
    ETL_LOADER = "etl_loader"          # Agent 1: CSV discovery, column mapping, import
    LABELLER = "labeller"              # Agent 2: clean names, classify buckets
    RULES_REVIEW = "rules_review"      # Agent 3: LLM-assisted rule creation for unlabeled merchants
    BUDGET_ONBOARDING = "budget_onboarding"  # Step 4: assign need/want/savings
    REPL = "repl"

    # Backward-compat alias so any external code referencing DB_MANAGER still works
    DB_MANAGER = "etl_loader"


@dataclass
class StartupState:
    stage: StartupStage = StartupStage.MODEL
    llm: object = None                # LiteLLMAdapter after stage 1
    data_source: str | None = None    # "demo" | "csv"
    persistence: str | None = None    # "permanent" | "session"
    db_path: str = ":memory:"
    conn: sqlite3.Connection | None = None
    bank: object = None               # DBBankingProvider after DB init
    is_first_run: bool = True


# ── Stage 1: Model selection ───────────────────────────────────────────────────

def stage_model(console, model_override: str | None = None):
    """Detect available LLM providers; return chosen adapter."""
    from llm.config import build_adapter
    return build_adapter(model_override, console=console)


# ── Stage 2: Data source ───────────────────────────────────────────────────────

def stage_data_source(console) -> str:
    """Ask whether to run demo or import real CSV data. Returns 'demo' or 'csv'."""
    console.print("\n[bold]How do you want to run the agent?[/bold]\n")
    console.print(
        "  [bold cyan]1[/bold cyan]  Demo   — synthetic Swiss bank account "
        "(instant, no files needed)"
    )
    console.print(
        "  [bold cyan]2[/bold cyan]  Import — load your own bank CSV exports\n"
    )
    try:
        from rich.prompt import IntPrompt
        choice = IntPrompt.ask("Choice", choices=["1", "2"], default=1)
    except (ImportError, EOFError, KeyboardInterrupt):
        choice = 1
    return "demo" if choice == 1 else "csv"


# ── Stage 3: Persistence ──────────────────────────────────────────────────────

def stage_persistence(console) -> tuple[str, str]:
    """Ask how imported data should be stored. Returns ('permanent'|'session', db_path)."""
    default_path = os.environ.get("LUCID_DB_PATH", "lucid_data.db")
    console.print("\n[bold]How should imported data be stored?[/bold]\n")
    console.print(
        f"  [bold cyan]1[/bold cyan]  Permanent   — SQLite file "
        f"[dim]({default_path})[/dim]"
    )
    console.print(
        "  [bold cyan]2[/bold cyan]  Session only — in-memory "
        "[dim](lost on exit)[/dim]\n"
    )
    try:
        from rich.prompt import IntPrompt
        choice = IntPrompt.ask("Choice", choices=["1", "2"], default=1)
    except (ImportError, EOFError, KeyboardInterrupt):
        choice = 1
    if choice == 1:
        return "permanent", default_path
    return "session", ":memory:"


# ── HITL mapping helpers ──────────────────────────────────────────────────────

def _show_mapping_preview(console, path, preview: dict, detected) -> None:
    """Render a Rich table showing what the parser detected for a CSV file."""
    from rich.table import Table
    from ingest.csv_detect import MappingAmbiguity, ResolvedColumnMapping

    sample_rows: list[dict] = preview.get("sample_rows", [])

    def _samples(col: str) -> str:
        vals = [str(r.get(col, "")).strip() for r in sample_rows[:3] if str(r.get(col, "")).strip()]
        return "  /  ".join(vals[:3]) or "—"

    console.print(f"\n[bold]Detected mapping for[/bold] [cyan]{path.name}[/cyan]")

    if isinstance(detected, MappingAmbiguity):
        console.print(f"  [red]Auto-detect failed:[/red] {detected.message}")
        if detected.best_effort:
            console.print(f"  [dim]Partial guess: {detected.best_effort}[/dim]")
        return

    # ResolvedColumnMapping — show field → column → samples table
    tbl = Table(box=None, show_header=True, padding=(0, 1))
    tbl.add_column("Lucid field", style="dim")
    tbl.add_column("CSV column", style="bold")
    tbl.add_column("Sample values", style="dim")

    field_labels = {
        "date": "date", "merchant": "merchant",
        "amount": "amount", "debit": "debit (CHF)", "credit": "credit (CHF)",
        "currency": "currency", "reference": "reference",
    }
    for lucid_key, col_name in detected.column_map.items():
        label = field_labels.get(lucid_key, lucid_key)
        tbl.add_row(label, col_name, _samples(col_name))

    console.print(tbl)

    sign_desc = {
        "single_amount": "amount column (negative = outflow)",
        "single_amount_flipped": "amount column × −1 (all-positive = outflow)",
        "debit_credit": "Debit column = outflow, Credit column = inflow",
    }.get(detected.sign_rule, detected.sign_rule)
    console.print(f"  Sign rule: [bold]{sign_desc}[/bold]")


def _infer_sign_rule(col_name: str, sample_rows: list[dict]) -> str:
    """Return sign_rule from column name and sample values — no user input needed.

    Column named "Debit" or similar → positive values are outflows → flip.
    Column with all-positive non-zero samples → assume outflow convention → flip.
    Otherwise → assume values already follow Lucid sign (negative = outflow).
    """
    from ingest.csv_normalize import parse_decimal

    _DEBIT_KEYWORDS = {"debit", "belastung", "ausgabe", "charge", "payment", "outflow", "debet"}
    if any(kw in col_name.lower() for kw in _DEBIT_KEYWORDS):
        return "single_amount_flipped"
    values = [parse_decimal(str(r.get(col_name, ""))) for r in sample_rows]
    non_zero = [v for v in values if v is not None and v != 0.0]
    if non_zero and all(v > 0 for v in non_zero):
        return "single_amount_flipped"
    return "single_amount"


def _resolve_mapping_hitl(
    console,
    llm,
    preview: dict,
    conn: "sqlite3.Connection | None" = None,
    user_id: str | None = None,
) -> "ResolvedColumnMapping | None":
    """Three-step escalation: LLM fallback → manual column selection → skip.

    When *conn* and *user_id* are provided, offers to save a successful
    resolution as a reusable profile (so the header-hash auto-reload path
    gets populated).
    """
    from ingest.csv_detect import LucidField, ResolvedColumnMapping
    from agents.csv_mapper import resolve_mapping_with_llm

    headers: list[str] = preview["headers"]
    encoding: str = preview.get("encoding", "utf-8")
    delimiter: str = preview.get("delimiter", ",")

    def _maybe_save_profile(mapping: "ResolvedColumnMapping", default_name: str) -> None:
        if conn is None or user_id is None:
            return
        try:
            from rich.prompt import Confirm
            save = Confirm.ask("  Save this mapping as a profile for future imports?", default=False)
        except (EOFError, KeyboardInterrupt):
            return
        if not save:
            return
        try:
            name_in = console.input(f"  Profile name [[bold]{default_name}[/bold]]: ").strip()
            display_name = name_in or default_name
        except (EOFError, KeyboardInterrupt):
            return
        from ingest.profiles import save_profile
        pid = save_profile(
            conn, user_id, display_name, mapping.column_map,
            sign_rule=mapping.sign_rule, encoding=mapping.encoding,
            delimiter=mapping.delimiter, headers=headers,
        )
        console.print(f"  [green]Profile saved (id: {pid})[/green]")

    # Step 1 — LLM fallback
    console.print("\n  [dim]Trying LLM to resolve mapping…[/dim]")
    try:
        mapping = resolve_mapping_with_llm(llm, preview)
        _show_mapping_preview(console, type("P", (), {"name": "(LLM resolved)"})(), preview, mapping)
        try:
            from rich.prompt import Confirm
            ok = Confirm.ask("  Use this LLM-resolved mapping?", default=True)
        except (EOFError, KeyboardInterrupt):
            ok = True
        if ok:
            _maybe_save_profile(mapping, "LLM resolved")
            return mapping
    except Exception as exc:
        console.print(f"  [yellow]LLM mapping failed: {exc}[/yellow]")

    # Step 2 — Manual column selection
    console.print("\n  [bold]Manual column assignment[/bold] (type 'skip' to abandon this file)\n")
    for i, h in enumerate(headers, 1):
        console.print(f"    [bold cyan]{i:>2}[/bold cyan]  {h}")
    console.print()

    _SKIP_WORDS = {"skip", "null", "none", "no", "-", "n/a"}

    def _pick(prompt: str, required: bool = True) -> str | None:
        while True:
            try:
                raw = console.input(f"  {prompt} › ").strip()
            except (EOFError, KeyboardInterrupt):
                return None
            if raw.lower() in _SKIP_WORDS:
                return "SKIP" if required else None
            if raw == "":
                if not required:
                    return None
                console.print("  [red]Required — enter a column number or name.[/red]")
                continue
            # Accept number or exact name
            if raw.isdigit():
                idx = int(raw) - 1
                if 0 <= idx < len(headers):
                    return headers[idx]
                console.print(f"  [red]Number out of range (1–{len(headers)}).[/red]")
            elif raw in headers:
                return raw
            else:
                console.print(f"  [red]Column not found. Enter a number (1–{len(headers)}) or exact header.[/red]")

    date_col = _pick("Date column [required]", required=True)
    if date_col == "SKIP" or date_col is None:
        return None

    merchant_col = _pick("Merchant/description column [required]", required=True)
    if merchant_col == "SKIP" or merchant_col is None:
        return None

    sample_rows: list[dict] = preview.get("sample_rows", [])[:5]

    amt_col = _pick("Amount/Debit column [required]", required=True)
    if amt_col == "SKIP" or amt_col is None:
        return None

    credit_col_simple = _pick("Credit column [optional — for refunds/inflows in a separate column]", required=False)
    if credit_col_simple == "SKIP":
        credit_col_simple = None

    cat_col_simple = _pick("Category column [optional]", required=False)
    if cat_col_simple == "SKIP":
        cat_col_simple = None

    if credit_col_simple:
        column_map: dict[str, str] = {
            LucidField.DATE.value: date_col,
            LucidField.MERCHANT.value: merchant_col,
            LucidField.DEBIT.value: amt_col,
            LucidField.CREDIT.value: credit_col_simple,
        }
        sign_rule = "debit_credit"
    else:
        column_map = {
            LucidField.DATE.value: date_col,
            LucidField.MERCHANT.value: merchant_col,
            LucidField.AMOUNT.value: amt_col,
        }
        sign_rule = _infer_sign_rule(amt_col, sample_rows)

    mapping = ResolvedColumnMapping(
        column_map=column_map,
        sign_rule=sign_rule,
        encoding=encoding,
        delimiter=delimiter,
        category_col=cat_col_simple,
    )
    _maybe_save_profile(mapping, "manual")
    return mapping


# ── Primary column-assignment UI (always shown) ──────────────────────────────

def _show_columns_and_get_mapping(
    console,
    llm,
    path: "Path",
    preview: dict,
    conn: "sqlite3.Connection | None" = None,
    user_id: str | None = None,
) -> "ResolvedColumnMapping | None":
    """Show all CSV columns with samples, ask user to assign each field.

    Auto-detection runs silently and its results are shown as bracketed
    defaults.  The user can accept by pressing Enter or type a different
    column number (1-based) or exact header name.

    Returns a ResolvedColumnMapping (with category_col if the user picked one)
    or None if the user chose to skip this file.
    """
    from rich.table import Table
    from ingest.csv_detect import LucidField, MappingAmbiguity, ResolvedColumnMapping

    headers: list[str] = preview["headers"]
    sample_rows: list[dict] = preview.get("sample_rows", [])[:3]
    encoding: str = preview.get("encoding", "utf-8")
    delimiter: str = preview.get("delimiter", ",")
    detected = preview.get("detection")

    # ── Step A: display columns with describe-style stats ────────────────────
    console.print(f"\n[bold]Columns in[/bold] [cyan]{path.name}[/cyan]\n")
    tbl = Table(box=None, show_header=True, padding=(0, 1))
    tbl.add_column("#", style="bold cyan", width=4)
    tbl.add_column("Column name", style="bold", min_width=22)
    tbl.add_column("fill", style="dim", width=6, justify="right")
    tbl.add_column("unique", style="dim", width=7, justify="right")
    tbl.add_column("values / range", style="dim", overflow="fold", max_width=32)

    n_rows = len(sample_rows)
    for i, h in enumerate(headers, 1):
        vals = [str(r.get(h, "")).strip() for r in sample_rows]
        non_empty = [v for v in vals if v]
        fill = f"{len(non_empty)/n_rows*100:.0f}%" if n_rows else "—"
        unique_vals = list(dict.fromkeys(v for v in non_empty))  # ordered, deduped
        unique_count = len(unique_vals)
        # Try numeric range, fall back to top unique values
        try:
            nums = [float(v.replace(",", ".")) for v in non_empty if v]
            preview_str = f"{min(nums):.2f} → {max(nums):.2f}" if nums else "—"
        except ValueError:
            preview_str = ", ".join(unique_vals[:3])
            if unique_count > 3:
                preview_str += f"  (+{unique_count - 3} more)"
        tbl.add_row(str(i), h, fill, str(unique_count) if non_empty else "—", preview_str)
    console.print(tbl)

    # ── Step B: derive defaults from auto-detection ───────────────────────────
    def _default_for(lucid_key: str) -> tuple[int | None, str | None]:
        if isinstance(detected, MappingAmbiguity):
            col_name = detected.best_effort.get(lucid_key)
        elif detected is not None:
            col_name = detected.column_map.get(lucid_key)
        else:
            col_name = None
        if col_name and col_name in headers:
            return headers.index(col_name) + 1, col_name
        return None, None

    detected_sign_rule: str = (
        detected.sign_rule if not isinstance(detected, MappingAmbiguity) and detected else "single_amount"
    )

    # ── Step C: interactive column picker ────────────────────────────────────
    _SKIP_WORDS = {"skip", "null", "none", "no", "-", "n/a"}

    def _pick(prompt_label: str, required: bool = True, default_idx: int | None = None, default_name: str | None = None) -> str | None:
        if required and default_idx:
            default_hint = f" [[bold]{default_idx} '{default_name}'[/bold], Enter to use]"
        elif not required and default_idx:
            default_hint = f" [suggestion: {default_idx} '{default_name}']"
        else:
            default_hint = ""
        while True:
            try:
                raw = console.input(f"  {prompt_label}{default_hint} › ").strip()
            except (EOFError, KeyboardInterrupt):
                return None
            if raw.lower() in _SKIP_WORDS:
                return "SKIP" if required else None
            if raw == "":
                if required and default_idx is not None:
                    return headers[default_idx - 1]
                if not required:
                    return None
                console.print("  [red]Required — enter a column number or name.[/red]")
                continue
            if raw.isdigit():
                idx = int(raw) - 1
                if 0 <= idx < len(headers):
                    return headers[idx]
                console.print(f"  [red]Number out of range (1–{len(headers)}).[/red]")
            elif raw in headers:
                return raw
            else:
                console.print(f"  [red]Not found. Enter a number (1–{len(headers)}) or exact column name.[/red]")

    def _fill_pct(col: str) -> int:
        """Return fill percentage (0-100) for a column across sample_rows."""
        if not sample_rows:
            return 0
        non_empty = sum(1 for r in sample_rows if str(r.get(col, "")).strip())
        return round(non_empty / len(sample_rows) * 100)

    def _warn_if_empty(col: str) -> None:
        if _fill_pct(col) == 0:
            console.print(
                f"  [yellow]⚠  '{col}' appears empty in the sample — "
                "confirm this is the right column.[/yellow]"
            )

    # Date
    d_idx, d_name = _default_for(LucidField.DATE.value)
    date_col = _pick("Date column [required]", required=True, default_idx=d_idx, default_name=d_name)
    if date_col == "SKIP" or date_col is None:
        return None
    _warn_if_empty(date_col)

    # Merchant
    m_idx, m_name = _default_for(LucidField.MERCHANT.value)
    merchant_col = _pick("Merchant/description column [required]", required=True, default_idx=m_idx, default_name=m_name)
    if merchant_col == "SKIP" or merchant_col is None:
        return None
    _warn_if_empty(merchant_col)

    # Amount column — user picks any column; sign_rule is inferred from name + samples
    # Default: prefer detected amount column, fall back to detected debit column
    a_idx, a_name = _default_for(LucidField.AMOUNT.value)
    if a_name is None:
        a_idx, a_name = _default_for(LucidField.DEBIT.value)

    amt_col = _pick("Amount/Debit column [required]", required=True, default_idx=a_idx, default_name=a_name)
    if amt_col == "SKIP" or amt_col is None:
        return None
    _warn_if_empty(amt_col)

    # Credit column — optional; present in bank CSVs that split outflows (debit) and
    # inflows/refunds (credit) into two separate columns.
    cr_idx, cr_name = _default_for(LucidField.CREDIT.value)
    credit_col = _pick(
        "Credit column [optional — for refunds/inflows in a separate column]",
        required=False,
        default_idx=cr_idx,
        default_name=cr_name,
    )
    if credit_col == "SKIP":
        credit_col = None

    cat_idx, cat_name = _default_for(LucidField.CATEGORY.value)
    cat_col = _pick("Category column [optional]", required=False, default_idx=cat_idx, default_name=cat_name)
    if cat_col == "SKIP":
        cat_col = None

    # Skip patterns — rows matching any pattern (any column) are excluded from import.
    # Useful to drop credit-card payment rows that are already tracked in a separate file.
    console.print(
        "\n  [dim]Row skip patterns [optional][/dim]\n"
        "  Any row where ANY column contains the entered text will be skipped.\n"
        "  Use [bold]ColumnName:text[/bold] to match only a specific column.\n"
        "  [dim]Example: 'UBS Card Center'  or  'Description 1:Credit Card Payment'[/dim]"
    )
    skip_patterns: list[str] = []
    while True:
        try:
            sp = console.input("  skip pattern (blank to finish) › ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not sp:
            break
        skip_patterns.append(sp)
        console.print(f"  [dim]Added: {sp}[/dim]")

    if credit_col:
        column_map: dict[str, str] = {
            LucidField.DATE.value: date_col,
            LucidField.MERCHANT.value: merchant_col,
            LucidField.DEBIT.value: amt_col,
            LucidField.CREDIT.value: credit_col,
        }
        sign_rule = "debit_credit"
    else:
        column_map = {
            LucidField.DATE.value: date_col,
            LucidField.MERCHANT.value: merchant_col,
            LucidField.AMOUNT.value: amt_col,
        }
        sign_rule = _infer_sign_rule(amt_col, sample_rows)

    mapping = ResolvedColumnMapping(
        column_map=column_map,
        sign_rule=sign_rule,
        encoding=encoding,
        delimiter=delimiter,
        category_col=cat_col,
        skip_patterns=tuple(skip_patterns),
    )

    # ── Step D: show summary and offer profile save ───────────────────────────
    console.print()
    _show_mapping_preview(console, path, preview, mapping)
    if mapping.skip_patterns:
        console.print(
            "  Skip patterns: "
            + ", ".join(f"[dim]{p}[/dim]" for p in mapping.skip_patterns)
        )

    def _maybe_save_profile(default_name: str) -> None:
        if conn is None or user_id is None:
            return
        try:
            from rich.prompt import Confirm
            save = Confirm.ask("  Save this mapping as a profile for future imports?", default=False)
        except (EOFError, KeyboardInterrupt):
            return
        if not save:
            return
        try:
            name_in = console.input(f"  Profile name [[bold]{default_name}[/bold]]: ").strip()
            display_name = name_in or default_name
        except (EOFError, KeyboardInterrupt):
            return
        from ingest.profiles import save_profile
        pid = save_profile(
            conn, user_id, display_name, mapping.column_map,
            sign_rule=mapping.sign_rule,
            encoding=mapping.encoding,
            delimiter=mapping.delimiter,
            headers=headers,
            category_col=mapping.category_col,
            skip_patterns=list(mapping.skip_patterns),
        )
        console.print(f"  [green]Profile saved (id: {pid})[/green]")

    _maybe_save_profile(path.stem)
    return mapping


# ── Stage 4: CSV import ───────────────────────────────────────────────────────

def stage_import(
    console,
    llm,
    conn: sqlite3.Connection,
    user_id: str,
) -> list:
    """Prompt for file paths, parse and import CSVs. Returns list[ImportResult]."""
    from ingest.csv_detect import MappingAmbiguity
    from ingest.importer import import_csv_files, preview_csv_file
    from ingest.account_detect import detect_and_confirm_account

    console.print(
        "\n[bold]Enter CSV file paths to import[/bold] "
        "[dim](one per line, blank line when done):[/dim]\n"
    )
    paths: list[Path] = []
    while True:
        try:
            line = console.input("  file › ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            break
        p = Path(line).expanduser().resolve()
        if not p.is_file():
            console.print(f"  [red]File not found: {p}[/red]")
        else:
            paths.append(p)

    if not paths:
        console.print("[dim]No files provided — skipping import.[/dim]")
        return []

    all_results = []
    for path in paths:
        prev = preview_csv_file(path)

        # Always show columns and ask the user to confirm/assign all fields
        mapping = _show_columns_and_get_mapping(
            console, llm, path, prev, conn=conn, user_id=user_id
        )
        if mapping is None:
            console.print(f"  [yellow]Skipping {path.name}[/yellow]")
            continue

        # Per-file account detection
        console.print(f"\n  [bold]Account for[/bold] [cyan]{path.name}[/cyan]")
        account_id = detect_and_confirm_account(
            console, llm, prev, conn, user_id, path.name
        )
        if account_id is None:
            console.print(f"  [yellow]Skipping {path.name} — no account selected.[/yellow]")
            continue

        results = import_csv_files(
            conn, user_id, account_id, [path], mapping=mapping,
        )
        all_results.extend(results)
        for r in results:
            color = "red" if r.skipped else "green"
            console.print(f"  [{color}]{path.name}: {r.message}[/{color}]")
            if r.rows_inserted:
                console.print(
                    f"    inserted [green]{r.rows_inserted}[/green]  "
                    f"dupes skipped {r.rows_skipped_duplicate}  "
                    f"invalid {r.rows_skipped_invalid}"
                )
            for w in r.warnings:
                console.print(f"  [yellow]⚠  {w}[/yellow]")

    return all_results


# ── Stage 5: Categorization ───────────────────────────────────────────────────

def stage_categorize(console, llm, conn: sqlite3.Connection, user_id: str) -> int:
    """Run ledger categorizer on imported transactions. Returns count of proposals."""
    from agents.ledger_categorizer import run_ledger_categorizer

    console.print()
    with console.status("[dim]Running ledger categorizer…[/dim]", spinner="dots"):
        run_ledger_categorizer(llm, conn, user_id)

    count = conn.execute(
        "SELECT COUNT(*) FROM category_proposals WHERE user_id=? AND status='pending'",
        (user_id,),
    ).fetchone()[0]

    if count:
        console.print(
            f"[green]{count} transaction(s) categorized.[/green] "
            f"Review with [bold]/review-categories[/bold] or accept with [bold]/cat-accept[/bold]."
        )
    else:
        console.print("[dim]No uncategorized outflows found — skipping categorization.[/dim]")
    return count


# ── Stage 6: Summary ──────────────────────────────────────────────────────────

def stage_summary(console, conn: sqlite3.Connection, user_id: str) -> None:
    """Display accurate aggregate stats computed from imported data. No LLM."""
    from rich.table import Table
    from tools.split import compute_split
    # Local import to avoid module-level circular dependency
    from orchestrator.router import _fetch_transactions  # type: ignore[attr-defined]

    total_count = conn.execute(
        "SELECT COUNT(*) FROM transactions t "
        "JOIN accounts a ON t.account_id=a.id WHERE a.user_id=?",
        (user_id,),
    ).fetchone()[0]

    console.print()
    console.rule("[dim]Import Summary[/dim]")
    console.print(f"  Total transactions in ledger: [bold]{total_count}[/bold]")

    txns = _fetch_transactions(conn, user_id, 90)
    if txns:
        income_account_count = conn.execute(
            "SELECT COUNT(*) FROM accounts WHERE user_id=? AND has_income=1",
            (user_id,),
        ).fetchone()[0]
        try:
            s = compute_split(txns)
            if s.mode == "spend_composition":
                console.print(
                    f"\n  [bold]90-day spending breakdown[/bold] [dim](no income in window)[/dim]\n"
                    f"  Total spend: CHF [bold]{s.needs_chf + s.wants_chf + s.savings_chf:,.2f}[/bold]\n"
                    f"  Needs:    {s.needs_pct:.1f}%  (CHF {s.needs_chf:,.2f})\n"
                    f"  Wants:    {s.wants_pct:.1f}%  (CHF {s.wants_chf:,.2f})\n"
                    f"  Savings:  {s.savings_pct:.1f}%  (CHF {s.savings_chf:,.2f})"
                )
                if not income_account_count:
                    console.print(
                        "  [dim]Import a checking or salary account to see "
                        "ratios relative to income.[/dim]"
                    )
            else:
                console.print(
                    f"\n  [bold]90-day window[/bold]\n"
                    f"  Income:   CHF [bold]{s.income_chf:,.2f}[/bold]\n"
                    f"  Needs:    {s.needs_pct:.1f}%  (CHF {s.needs_chf:,.2f})\n"
                    f"  Wants:    {s.wants_pct:.1f}%  (CHF {s.wants_chf:,.2f})\n"
                    f"  Savings:  {s.savings_pct:.1f}%  (CHF {s.savings_chf:,.2f})"
                )
        except ValueError:
            console.print(
                "  [dim]No transactions in the last 90 days.[/dim]"
            )
    else:
        console.print("  [dim]No transactions in the last 90 days.[/dim]")

    # Monthly charges vs credits — last 6 months
    rows = conn.execute(
        "SELECT strftime('%Y-%m', t.ts) AS month, "
        "  -SUM(CASE WHEN t.amount < 0 THEN t.amount ELSE 0 END) AS charges, "
        "   SUM(CASE WHEN t.amount > 0 THEN t.amount ELSE 0 END) AS credits "
        "FROM transactions t JOIN accounts a ON t.account_id=a.id "
        "WHERE a.user_id=? GROUP BY month ORDER BY month DESC LIMIT 6",
        (user_id,),
    ).fetchall()

    if rows:
        tbl = Table(title="Monthly spending (last 6 months)", box=None, show_header=True)
        tbl.add_column("Month", style="dim")
        tbl.add_column("Charges CHF", justify="right")
        tbl.add_column("Credits CHF", justify="right", style="dim")
        for month, charges, credits in rows:
            tbl.add_row(
                month,
                f"[red]{(charges or 0):,.2f}[/red]",
                f"[green]{(credits or 0):,.2f}[/green]" if (credits or 0) > 0 else "—",
            )
        console.print()
        console.print(tbl)

    console.rule()


# ── Stage 4: CSV folder prompt + Agent 1 ─────────────────────────────────────

def _ask_csv_folder(console) -> str:
    """Prompt the user for the folder that contains their CSV exports."""
    console.print(
        "\n[bold]Enter the folder path containing your CSV files:[/bold]\n"
        "[dim]All .csv files inside will be discovered and imported by the agent.[/dim]\n"
    )
    while True:
        try:
            raw = console.input("  folder › ").strip()
        except (EOFError, KeyboardInterrupt):
            return ""
        if not raw:
            console.print("  [red]Folder path required.[/red]")
            continue
        from pathlib import Path
        p = Path(raw).expanduser().resolve()
        if not p.is_dir():
            console.print(f"  [red]Not a directory: {p}[/red]  Try again.")
            continue
        return str(p)


def stage_etl_loader(
    console,
    llm,
    conn: sqlite3.Connection,
    user_id: str,
    account_id: str,
) -> str:
    """Run deterministic ETL pipeline (CSV discovery, column mapping, import). No LLM."""
    from agents.etl_loader.agent import run_etl_pipeline
    csv_folder = _ask_csv_folder(console)
    if not csv_folder:
        console.print("[dim]No folder provided — skipping import.[/dim]")
        return ""
    return run_etl_pipeline(conn, user_id, account_id, csv_folder, console)


def stage_labeller(
    console,
    llm,
    conn: sqlite3.Connection,
    user_id: str,
) -> str:
    """Run Labeller Agent only when uncategorized outflows exist."""
    uncategorized = conn.execute(
        "SELECT COUNT(*) FROM transactions t JOIN accounts a ON t.account_id=a.id "
        "WHERE a.user_id=? AND t.amount < 0 AND t.line_category IS NULL",
        (user_id,),
    ).fetchone()[0]

    if uncategorized == 0:
        console.print(
            "[dim]  All imported rows already have a category — skipping Labeller.[/dim]"
        )
        return "All rows already categorised."

    from agents.labeller.agent import run_labeller_agent
    return run_labeller_agent(llm, conn, user_id, console, batch_limit=uncategorized)


def stage_rules_review(
    console,
    llm,
    conn: sqlite3.Connection,
    user_id: str,
) -> None:
    """LLM-assisted rule creation for unlabeled merchants — runs before budget onboarding.

    Any merchant without a line_category is shown to the user with an LLM
    suggestion (income / refund / expense + bucket + label).  Confirmed rules
    are applied immediately so the budget onboarding sees accurate categories
    instead of a bulk '(uncategorised)' bucket.
    """
    unlabeled = conn.execute(
        "SELECT COUNT(*) FROM transactions t JOIN accounts a ON t.account_id=a.id "
        "WHERE a.user_id=? AND COALESCE(t.line_category, '') = ''",
        (user_id,),
    ).fetchone()[0]

    if unlabeled == 0:
        return

    from agents.labeller.rules_flow import run_rules_review

    console.print()
    console.print(
        f"[bold]━━  Categorize {unlabeled} unlabeled transaction(s)  ━━[/bold]\n"
        "  [dim]These merchants couldn't be matched by the Labeller.\n"
        "  The LLM will suggest a rule for each — accept, edit, or skip.\n"
        "  Completing this step makes the budget onboarding more accurate.[/dim]\n"
    )

    try:
        from rich.prompt import Confirm
        run_it = Confirm.ask("  Review now? (recommended)", default=True)
    except (EOFError, KeyboardInterrupt):
        run_it = False

    if run_it:
        run_rules_review(llm, conn, user_id, console)


def stage_budget_onboarding(
    console,
    conn: sqlite3.Connection,
    user_id: str,
    account_id: str,
) -> None:
    """Run Budget Onboarding when no need/want/savings categories exist yet."""
    from agents.budget_onboarding.agent import run_budget_onboarding
    run_budget_onboarding(conn, user_id, account_id, console)


def stage_db_manager(
    console,
    llm,
    conn: sqlite3.Connection,
    user_id: str,
    account_id: str,
) -> str:
    """Backward-compat alias for stage_etl_loader."""
    return stage_etl_loader(console, llm, conn, user_id, account_id)


# ── DB seeding helpers ────────────────────────────────────────────────────────

_DEMO_TRANSACTIONS: list[tuple[str, float, str | None]] = [
    ("Salary ACME AG",       5200.00, None),
    ("Salary ACME AG",       5200.00, None),
    ("Salary ACME AG",       5200.00, None),
    ("Miete Zurich",        -1800.00, "need"),
    ("Helsana",              -420.00, "need"),
    ("Coop",                 -480.00, "need"),
    ("Migros",               -220.00, "need"),
    ("SBB Halbtax",          -180.00, "need"),
    ("Swisscom",              -79.00, "need"),
    ("Coop",                 -155.00, "need"),
    ("EWZ Strom",             -62.00, "need"),
    ("Netflix",               -13.00, "want"),
    ("Spotify",               -10.00, "want"),
    ("Starbucks",             -42.00, "want"),
    ("Restaurant Helvetia",   -68.00, "want"),
    ("Zara",                  -89.00, "want"),
    ("Kino Kosmos",           -30.00, "want"),
    ("Starbucks",             -14.00, "want"),
    ("Tibits",                -25.00, "want"),
    ("Amazon.de",             -55.00, "want"),
    ("VIAC 3a",              -400.00, "savings"),
    ("Swissquote",           -200.00, "savings"),
]


def _seed_demo(
    conn: sqlite3.Connection,
    user_id: str,
    account_id: str,
    conv_id: str,
) -> None:
    now = datetime.now()
    conn.execute(
        "INSERT OR IGNORE INTO users(id, display_name, created_at) VALUES(?,?,?)",
        (user_id, "Demo User", now.isoformat()),
    )
    conn.execute(
        "INSERT OR IGNORE INTO accounts"
        "(id, user_id, name, balance, currency, account_type, has_income) "
        "VALUES(?,?,?,?,?,?,?)",
        (account_id, user_id, "Zürcher Kantonalbank Checking", 3200.00, "CHF", "checking", 1),
    )
    conn.execute(
        "INSERT OR IGNORE INTO conversations(id, user_id, started_at) VALUES(?,?,?)",
        (conv_id, user_id, now.isoformat()),
    )
    conn.execute("INSERT OR IGNORE INTO prefs(user_id) VALUES(?)", (user_id,))
    for i, (merchant, amount, cat) in enumerate(_DEMO_TRANSACTIONS):
        days_ago = (i * 3) % 75 + 3
        ts = (now - timedelta(days=days_ago)).isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO transactions"
            "(id, account_id, amount, currency, merchant, category, ts) "
            "VALUES(?,?,?,?,?,?,?)",
            (f"seed-{i}", account_id, amount, "CHF", merchant, cat, ts),
        )
    conn.commit()


def _seed_minimal(
    conn: sqlite3.Connection,
    user_id: str,
    account_id: str,
    conv_id: str,
) -> None:
    now = datetime.now()
    conn.execute(
        "INSERT OR IGNORE INTO users(id, display_name, created_at) VALUES(?,?,?)",
        (user_id, "Import User", now.isoformat()),
    )
    conn.execute(
        "INSERT OR IGNORE INTO accounts(id, user_id, name, balance, currency) "
        "VALUES(?,?,?,?,?)",
        (account_id, user_id, "Imported ledger", 0.0, "CHF"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO conversations(id, user_id, started_at) VALUES(?,?,?)",
        (conv_id, user_id, now.isoformat()),
    )
    conn.execute("INSERT OR IGNORE INTO prefs(user_id) VALUES(?)", (user_id,))
    conn.commit()


# ── Entrypoint ────────────────────────────────────────────────────────────────

def run_startup(console, model_override: str | None = None) -> StartupState:
    """Execute all startup stages in order; return completed StartupState."""
    from bank import make_db_provider
    from db.db_schema import init_db

    state = StartupState()

    # Stage 1 — Model
    state.stage = StartupStage.MODEL
    state.llm = stage_model(console, model_override)

    # Stage 2 — Data source
    state.stage = StartupStage.DATA_SOURCE
    state.data_source = stage_data_source(console)

    # Stage 3 — Persistence (CSV path only)
    if state.data_source == "csv":
        state.stage = StartupStage.PERSISTENCE
        state.persistence, state.db_path = stage_persistence(console)
    else:
        # DEMO: honour existing env var if set, else default to :memory:
        state.db_path = os.environ.get("LUCID_DB_PATH", ":memory:")
        state.persistence = "permanent" if state.db_path != ":memory:" else "session"

    if state.db_path == ":memory:" and state.data_source == "csv":
        console.print(
            "\n[yellow]Note:[/yellow] [dim]Session-only — imported data will be lost on exit.[/dim]"
        )

    # Init DB and seed
    state.conn = init_db(state.db_path)
    if state.data_source == "demo":
        _seed_demo(state.conn, USER_ID, ACCOUNT_ID, CONV_ID)
    else:
        _seed_minimal(state.conn, USER_ID, ACCOUNT_ID, CONV_ID)

    # Wire BankingProvider
    state.bank = make_db_provider(state.conn, USER_ID)

    if state.data_source == "csv":
        # Stage 4 — ETL Loader: CSV discovery, column mapping, import
        state.stage = StartupStage.ETL_LOADER
        stage_etl_loader(console, state.llm, state.conn, USER_ID, ACCOUNT_ID)

        # Stage 5 — Labeller: clean names, classify buckets
        state.stage = StartupStage.LABELLER
        stage_labeller(console, state.llm, state.conn, USER_ID)

        # Stage 5.5 — Rules Review: LLM-assisted rules for unlabeled merchants
        # Runs BEFORE budget onboarding so users can classify merchants accurately
        # rather than having them bulk-assigned as 'want'.
        state.stage = StartupStage.RULES_REVIEW
        stage_rules_review(console, state.llm, state.conn, USER_ID)

        # Stage 6 — Budget Onboarding: assign need/want/savings if none exist yet
        uncategorized_count = state.conn.execute(
            "SELECT COUNT(*) FROM transactions t "
            "JOIN accounts a ON t.account_id = a.id "
            "WHERE a.user_id = ? AND t.category IS NULL",
            (USER_ID,),
        ).fetchone()[0]
        if uncategorized_count > 0:
            state.stage = StartupStage.BUDGET_ONBOARDING
            stage_budget_onboarding(console, state.conn, USER_ID, ACCOUNT_ID)

        stage_summary(console, state.conn, USER_ID)

    # Determine if first-run (no active goal → onboarding pending)
    row = state.conn.execute(
        "SELECT 1 FROM goals WHERE user_id=? AND active=1 LIMIT 1",
        (USER_ID,),
    ).fetchone()
    state.is_first_run = row is None

    state.stage = StartupStage.REPL
    return state
