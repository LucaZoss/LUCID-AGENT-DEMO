"""
LLM-assisted merchant categorization rules flow.

Entry point: run_rules_review(llm, conn, user_id, console)

Groups uncategorized transactions by merchant, pre-loads LLM proposals for all
merchants at once (with a progress bar), displays them in a table, and lets the
user accept all, edit individual rows, or skip merchants before saving.

Design:
- One LLM call per merchant group (text completion, no tools), batched upfront.
- Writes directly to transactions + merchant_category_overrides; bypasses
  category_proposals (no staging needed — the user confirms inline).
- Income/refund rules set line_category but leave category=NULL, consistent
  with how compute_split already handles positive-amount rows.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from agents.labeller.tools import RULE_LINE_CATEGORIES
from tools.labeller.name_cleaner import clean_merchant_name

_VALID_TYPES = {"income", "refund", "expense"}
_VALID_BUCKETS = {"need", "want", "savings"}
_BUCKET_COLOR = {"need": "cyan", "want": "yellow", "savings": "green"}


class _UserQuit(Exception):
    """Raised when the user types /quit inside the row editor."""


def _print_help(console) -> None:
    console.print(
        "\n  [bold]Rules flow commands[/bold]\n"
        "\n  [bold]Table view[/bold]\n"
        "    [cyan]<n>[/cyan]       edit row n (e.g. [cyan]5[/cyan])\n"
        "    [cyan]s<n>[/cyan]      skip row n without creating a rule (e.g. [cyan]s5[/cyan])\n"
        "    [cyan]a[/cyan]         accept all suggestions and save\n"
        "    [cyan]p[/cyan]         reprint the proposals table\n"
        "    [cyan]/help[/cyan]     show this message\n"
        "    [cyan]/quit[/cyan]     save confirmed rules and exit the flow\n"
        "\n  [bold]Row editor[/bold]\n"
        "    [cyan]b=need[/cyan]    set bucket directly (need / want / savings)\n"
        "    [cyan]l=groceries[/cyan]  set label directly (see list below)\n"
        "    [cyan]t=expense[/cyan] set type directly (expense / income / refund)\n"
        "    combine: [cyan]b=need l=groceries[/cyan] — all in one line\n"
        "    [cyan]b[/cyan] / [cyan]l[/cyan] / [cyan]t[/cyan]   open interactive picker for that field\n"
        "    [cyan]Enter[/cyan]     accept current values\n"
        "    [cyan]s[/cyan]         skip this merchant\n"
        "    [cyan]/quit[/cyan]     save confirmed rules and exit the flow\n"
        "\n  [bold]Valid labels[/bold]\n"
        f"    {', '.join(sorted(RULE_LINE_CATEGORIES))}\n"
    )

_SYSTEM_PROMPT = """\
You are a Swiss personal finance assistant that classifies bank merchants.
Given a merchant name and sample transactions, return ONLY a JSON object — no
markdown, no extra text.

Classify the merchant as one of:
  income   — regular salary, wage, or large periodic deposit
  refund   — money returned from a previous purchase
  expense  — any outgoing payment

For expense, also set "bucket" to one of: need | want | savings
  need     — essential: rent, groceries, health insurance, telecom, transport
  want     — discretionary: restaurants, clothing, digital goods, travel, sports
  savings  — investment, pillar 3a, savings transfer

For "line_category" pick the EXACT key from this canonical taxonomy:

  Expenses / Needs:
    rent, health_insurance, groceries_food, telecom

  Expenses / Wants:
    car, clothing, digital_goods, health_other, housing,
    restaurants, sports, travel_holidays, transport, wellbeing, wants_other

  Income:
    salary

  Extras:
    twint_credit, twint_debit, extras_other

Examples:
  Coop, Migros, Denner → groceries_food
  Netflix, Spotify, Adobe, Claude.AI, GitHub → digital_goods
  Starbucks, McDonald's, Sushi restaurant → restaurants
  SBB, BLS, Uber → transport
  Helsana, Swica, CSS, Assura → health_insurance
  Gym, Fitnesspark, Decathlon → sports

JSON schema (all fields required):
{
  "type": "income" | "refund" | "expense",
  "bucket": "need" | "want" | "savings" | null,
  "line_category": "<exact key from the taxonomy above>",
  "rationale": "<one sentence>"
}
"""


# ── Data fetch ──────────────────────────────────────────────────────────────────


def _fetch_uncategorized_groups(
    conn: sqlite3.Connection,
    user_id: str,
) -> list[dict[str, Any]]:
    """Return merchants with uncategorized transactions, sorted by frequency."""
    rows = conn.execute(
        "SELECT "
        "  lower(trim(t.merchant))                        AS merchant_key, "
        "  COALESCE(t.clean_name, t.merchant)             AS display_name, "
        "  t.merchant                                     AS raw_merchant, "
        "  COUNT(*)                                       AS txn_count, "
        "  ROUND(SUM(t.amount), 2)                        AS total_amount, "
        "  MIN(t.amount)                                  AS min_amount, "
        "  MAX(t.amount)                                  AS max_amount "
        "FROM transactions t "
        "JOIN accounts a ON t.account_id = a.id "
        "WHERE a.user_id = ? "
        "AND (t.category IS NULL OR COALESCE(t.line_category, '') = '') "
        "GROUP BY merchant_key "
        "ORDER BY txn_count DESC",
        (user_id,),
    ).fetchall()

    return [
        {
            "merchant_key": r[0],
            "display_name": r[1],
            "raw_merchant": r[2],
            "txn_count": r[3],
            "total_amount": r[4],
            "min_amount": r[5],
            "max_amount": r[6],
        }
        for r in rows
    ]


# ── LLM proposal ───────────────────────────────────────────────────────────────


def _parse_json_response(text: str) -> dict | None:
    """Extract and parse JSON from LLM output, tolerating markdown fences."""
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip()
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if m:
        cleaned = m.group(0)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def _propose_rule(llm, group: dict[str, Any]) -> dict[str, Any]:
    """Ask the LLM to classify a merchant; return a normalised proposal dict."""
    user_msg = (
        f"Merchant: {group['display_name']}\n"
        f"Occurrences: {group['txn_count']}\n"
        f"Total CHF: {group['total_amount']:+.2f}   "
        f"(range {group['min_amount']:+.2f} to {group['max_amount']:+.2f})\n"
    )

    try:
        response = llm.complete(
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        data = _parse_json_response(response.content or "")
    except Exception:
        data = None

    if not data:
        return _fallback_proposal(group)

    txn_type = str(data.get("type", "expense")).lower()
    bucket = str(data.get("bucket") or "").lower() or None
    line = str(data.get("line_category", "other")).lower().replace(" ", "_")
    rationale = str(data.get("rationale", ""))

    if txn_type not in _VALID_TYPES:
        txn_type = "expense"
    if txn_type == "expense" and bucket not in _VALID_BUCKETS:
        bucket = "want"
    if txn_type in ("income", "refund"):
        bucket = None
    if line not in RULE_LINE_CATEGORIES:
        line = "wants_other"

    return {
        "type": txn_type,
        "bucket": bucket,
        "line_category": line,
        "rationale": rationale,
        "llm_ok": True,
    }


def _fallback_proposal(group: dict[str, Any]) -> dict[str, Any]:
    """Deterministic fallback when the LLM call fails."""
    if group["total_amount"] > 0:
        return {"type": "income", "bucket": None, "line_category": "salary",
                "rationale": "positive balance (auto-fallback)", "llm_ok": False}
    return {"type": "expense", "bucket": "want", "line_category": "wants_other",
            "rationale": "unknown merchant (auto-fallback)", "llm_ok": False}


def _propose_all_rules(llm, groups: list[dict], console) -> list[dict]:
    """Fetch LLM proposals for all groups in sequence with a progress bar."""
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn

    proposals: list[dict] = []
    with Progress(
        TextColumn("  [progress.description]{task.description}"),
        BarColumn(bar_width=28),
        MofNCompleteColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Proposing rules...", total=len(groups))
        for group in groups:
            proposals.append(_propose_rule(llm, group))
            progress.advance(task)
    return proposals


# ── Bulk table display ──────────────────────────────────────────────────────────


def _render_proposals_table(
    console,
    groups: list[dict],
    proposals: list[dict],
    skipped: set[int],
) -> None:
    """Render all pending (non-skipped) proposals as a compact Rich table."""
    from rich.table import Table

    table = Table(
        show_header=True,
        header_style="bold dim",
        box=None,
        pad_edge=False,
        show_edge=False,
        padding=(0, 1),
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Merchant", no_wrap=True, max_width=44)
    table.add_column("×", justify="right", width=4)
    table.add_column("CHF", justify="right", width=10)
    table.add_column("Type", width=8)
    table.add_column("Bucket", width=9)
    table.add_column("Label", width=18)

    for i, (group, prop) in enumerate(zip(groups, proposals)):
        if i in skipped:
            continue
        bucket = prop.get("bucket") or "—"
        color = _BUCKET_COLOR.get(bucket, "dim")
        table.add_row(
            str(i + 1),
            group["display_name"][:44],
            str(group["txn_count"]),
            f"{group['total_amount']:+,.0f}",
            prop["type"],
            f"[{color}]{bucket}[/{color}]",
            prop["line_category"],
        )

    console.print()
    console.print(table)


# ── Single-item HITL dialog ─────────────────────────────────────────────────────

_TYPE_CHOICES = list(_VALID_TYPES)
_BUCKET_CHOICES = list(_VALID_BUCKETS)
_LABEL_CHOICES = sorted(RULE_LINE_CATEGORIES)


def _ask_choice(console, prompt: str, choices: list[str], current: str) -> str:
    """Show a numbered list and let the user pick by number or keep current."""
    for i, c in enumerate(choices, 1):
        marker = " ◀" if c == current else ""
        console.print(f"    [dim]{i}[/dim]  {c}{marker}")
    try:
        raw = console.input(f"  {prompt} (number, Enter=keep [{current}]): ").strip()
        if raw:
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return choices[idx]
    except (EOFError, KeyboardInterrupt, ValueError):
        pass
    return current


def _show_rule_hitl(
    console,
    group: dict[str, Any],
    proposal: dict[str, Any],
    index: int,
    total: int,
) -> dict[str, Any] | None:
    """Interactive dialog for one merchant. Returns updated rule dict or None (skip).

    Loops until the user accepts (Enter/a) or skips (s). Each iteration
    re-renders the current state so multiple fields can be edited before
    confirming.
    """
    txn_type = proposal["type"]
    bucket = proposal.get("bucket")
    line = proposal["line_category"]
    rationale = proposal.get("rationale", "")
    llm_ok = proposal.get("llm_ok", True)

    while True:
        amount = group["total_amount"]
        amount_color = "green" if amount > 0 else "red"
        llm_note = "" if llm_ok else "  [dim yellow](fallback)[/dim yellow]"
        bucket_display = bucket or "—"
        bucket_color = _BUCKET_COLOR.get(bucket or "", "dim")

        console.print(
            f"\n  [bold cyan]─── {index}/{total}: {group['display_name']}[/bold cyan]"
            f"  [dim]({group['txn_count']}×  ·  "
            f"[{amount_color}]CHF {amount:+,.2f}[/{amount_color}])[/dim]"
        )
        console.print(
            f"  Current:   [bold]{txn_type}[/bold]"
            f"  ·  [bold {bucket_color}]{bucket_display}[/bold {bucket_color}]"
            f"  ·  [bold]{line}[/bold]{llm_note}"
        )
        if rationale:
            console.print(f"  Rationale: [dim]{rationale}[/dim]")
        console.print(
            "  [dim](Enter=accept  b=<bucket>  l=<label>  t=<type>  "
            "or bare t/b/l for picker  ·  s=skip)[/dim]"
        )

        try:
            raw = console.input("  › ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None

        if raw in ("", "a"):
            break

        if raw in ("s", "q"):
            return None

        if raw in ("/quit", "/exit", "/q"):
            raise _UserQuit()

        if raw in ("/help", "/h", "/?"):
            _print_help(console)
            continue

        # Parse space-separated commands, supporting both:
        #   bare letters:   t  b  l  (interactive picker)
        #   inline values:  t=expense  b=need  l=groceries  (direct assignment)
        # Multiple tokens allowed on one line, e.g. "b=need l=groceries"
        direct: dict[str, str] = {}
        interactive_cmds: list[str] = []
        skip_flag = False

        for token in raw.split():
            if token in ("s", "q"):
                skip_flag = True
                break
            if "=" in token:
                key, _, val = token.partition("=")
                direct[key.strip()] = val.strip()
            elif token in ("t", "b", "l"):
                interactive_cmds.append(token)

        if skip_flag:
            return None

        # Apply direct assignments
        if "t" in direct:
            v = direct["t"]
            if v in _VALID_TYPES:
                txn_type = v
                if txn_type in ("income", "refund"):
                    bucket = None
        if "b" in direct:
            v = direct["b"]
            if txn_type == "expense" and v in _VALID_BUCKETS:
                bucket = v
            elif v not in _VALID_BUCKETS:
                console.print(f"  [dim yellow]Unknown bucket '{v}' — use need/want/savings.[/dim yellow]")
        if "l" in direct:
            v = direct["l"].replace(" ", "_").replace("-", "_")
            if v in RULE_LINE_CATEGORIES:
                line = v
            else:
                console.print(f"  [dim yellow]Unknown label '{v}' — type l for the full list.[/dim yellow]")

        # Interactive prompts for bare letters (loop back after to show updated state)
        for cmd in interactive_cmds:
            if cmd == "t":
                txn_type = _ask_choice(console, "Type", _TYPE_CHOICES, txn_type)
                if txn_type in ("income", "refund"):
                    bucket = None
            elif cmd == "b":
                if txn_type != "expense":
                    console.print("  [dim]Bucket only applies to expense transactions.[/dim]")
                else:
                    bucket = _ask_choice(console, "Bucket", _BUCKET_CHOICES, bucket or "want")
            elif cmd == "l":
                line = _ask_choice(console, "Label", _LABEL_CHOICES, line)

        # Direct assignments are unambiguous — accept immediately without re-prompting.
        # Only loop back when interactive pickers were used (user may want to adjust more).
        if direct and not interactive_cmds:
            break

    if txn_type == "expense" and not bucket:
        bucket = "want"
    if txn_type in ("income", "refund"):
        bucket = None

    return {"type": txn_type, "bucket": bucket, "line_category": line}


# ── Rule persistence + retroactive application ─────────────────────────────────


def _apply_and_save_rule(
    conn: sqlite3.Connection,
    user_id: str,
    merchant_key: str,
    raw_merchant: str,
    display_name: str,
    bucket: str | None,
    line_category: str,
) -> int:
    """Update matching transactions + upsert merchant_category_overrides."""
    from categories import is_valid_key
    from categories_mapping import map_from_line_category

    norm_cat = line_category if is_valid_key(line_category) else map_from_line_category(line_category)
    now = datetime.now(timezone.utc).isoformat()

    # No category IS NULL guard — user-confirmed rules override bulk onboarding assignments.
    cur = conn.execute(
        "UPDATE transactions "
        "SET category = ?, line_category = ?, normalized_category = ? "
        "WHERE lower(trim(merchant)) = ? "
        "AND account_id IN (SELECT id FROM accounts WHERE user_id = ?)",
        (bucket, line_category, norm_cat, merchant_key, user_id),
    )
    n_updated = cur.rowcount

    canonical = clean_merchant_name(raw_merchant) or display_name

    existing = conn.execute(
        "SELECT id FROM merchant_category_overrides "
        "WHERE user_id = ? AND merchant_normalized = ?",
        (user_id, merchant_key),
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE merchant_category_overrides "
            "SET canonical_name=?, bucket=?, line_category=?, normalized_category=?, "
            "source='user_confirmed', confidence=1.0, updated_at=? "
            "WHERE id=?",
            (canonical, bucket, line_category, norm_cat, now, existing[0]),
        )
    else:
        conn.execute(
            "INSERT INTO merchant_category_overrides "
            "(id, user_id, merchant_normalized, canonical_name, bucket, "
            "line_category, normalized_category, source, confidence, override_count, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'user_confirmed', 1.0, 0, ?)",
            (str(uuid.uuid4()), user_id, merchant_key, canonical,
             bucket, line_category, norm_cat, now),
        )

    conn.commit()
    return n_updated


# ── Main entry point ───────────────────────────────────────────────────────────


def run_rules_review(llm, conn: sqlite3.Connection, user_id: str, console) -> None:
    """LLM-assisted HITL flow for creating merchant categorization rules.

    Pre-loads all LLM suggestions, displays them in a compact table, and lets
    the user accept all, edit individual rows, or skip merchants before saving.
    """
    groups = _fetch_uncategorized_groups(conn, user_id)
    if not groups:
        console.print("  [dim]No unlabeled transactions — nothing to do.[/dim]")
        return

    total_txns = sum(g["txn_count"] for g in groups)
    console.print(
        f"\n  [bold]━━  Rules: {total_txns} transactions · {len(groups)} merchants  ━━[/bold]"
    )

    proposals = _propose_all_rules(llm, groups, console)
    skipped: set[int] = set()

    # Render the table once upfront; only reprint on 'p' so edits don't flood the screen.
    _render_proposals_table(console, groups, proposals, skipped)

    while True:
        n_pending = len(groups) - len(skipped)
        console.print(
            f"\n  [dim]{n_pending} rule(s) ready ·  "
            "Enter/a=save all   <n>=edit   s<n>=skip   p=reprint table   q=quit[/dim]"
        )

        try:
            raw = console.input("  › ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if raw in ("a", "", "q"):
            break

        if raw in ("/quit", "/exit", "/q"):
            break

        if raw in ("/help", "/h", "/?"):
            _print_help(console)
            continue

        if raw == "p":
            _render_proposals_table(console, groups, proposals, skipped)
            continue

        # s<n> — skip row n
        skip_m = re.match(r"^s\s*(\d+)$", raw)
        if skip_m:
            idx = int(skip_m.group(1)) - 1
            if 0 <= idx < len(groups):
                skipped.add(idx)
                console.print(f"  [dim]Row {idx + 1} skipped.[/dim]")
            continue

        # <n> — inline edit (also un-skips if the row was previously skipped)
        try:
            idx = int(raw) - 1
        except ValueError:
            continue

        if 0 <= idx < len(groups):
            skipped.discard(idx)
            try:
                updated = _show_rule_hitl(console, groups[idx], proposals[idx], idx + 1, len(groups))
            except _UserQuit:
                break
            if updated is None:
                skipped.add(idx)
                console.print(f"  [dim]Row {idx + 1} skipped.[/dim]")
            else:
                proposals[idx] = updated
                prop = proposals[idx]
                bucket_display = prop.get("bucket") or "—"
                console.print(
                    f"  [green]✓[/green] Row {idx + 1} updated: "
                    f"[bold]{prop['type']}[/bold] · "
                    f"[bold]{bucket_display}[/bold] · "
                    f"[bold]{prop['line_category']}[/bold]"
                )

    # Persist all non-skipped rules
    rules_saved = 0
    txns_updated = 0
    for i, (group, prop) in enumerate(zip(groups, proposals)):
        if i in skipped:
            continue
        n = _apply_and_save_rule(
            conn,
            user_id,
            merchant_key=group["merchant_key"],
            raw_merchant=group["raw_merchant"],
            display_name=group["display_name"],
            bucket=prop["bucket"],
            line_category=prop["line_category"],
        )
        txns_updated += n
        rules_saved += 1

    console.print(
        f"\n  [bold]━━  Rules session complete  ━━[/bold]\n"
        f"  Rules saved:          [bold]{rules_saved}[/bold]\n"
        f"  Merchants skipped:    [bold]{len(skipped)}[/bold]\n"
        f"  Transactions updated: [bold]{txns_updated}[/bold]\n"
    )
