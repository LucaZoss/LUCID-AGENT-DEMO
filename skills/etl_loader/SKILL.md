---
name: etl_loader
description: "Import bank CSV files into the ledger: discover files, auto-apply known format profiles (header fingerprint memory), run HITL column-mapping dialog for new formats, normalize rows, and store transactions."
triggers: ["import csv", "load transactions", "upload bank export", "import bank file", "import data"]
tools_required: ["scan_folder", "check_complexity", "lookup_format_profile", "show_columns_ask_user", "import_file", "save_format_profile"]
outputs: import_summary
---

# Skill: etl_loader

Scout Pattern — two-pass file processing.

## Steps

### Pass 1 — Scout each file
1. `scan_folder(folder_path)` → list of .csv paths
2. For each path: `check_complexity(file_path)` → determines parse strategy
3. `lookup_format_profile(file_path)` → checks header-fingerprint memory
   - If `auto_apply = true` (confirmed + use_count ≥ 2): proceed to import directly, print one-line confirmation
   - Otherwise: proceed to Pass 2 HITL

### Pass 2 — HITL for unknown or unconfirmed formats
4. `show_columns_ask_user(file_path)` → displays all columns with sample values; user assigns each Lucid field
5. Returns `{column_map, sign_rule, encoding, delimiter, category_col}`

### Import
6. `import_file(file_path, column_map, sign_rule, ...)` → inserts normalized rows
7. `save_format_profile(...)` → persists the mapping (increments use_count)

## Format memory logic

- Header fingerprint = sha256(sorted normalized headers)
- Confirmed + use_count ≥ 2 → auto-apply silently
- Confirmed + use_count < 2 → show summary to user, ask for quick "looks right?" confirmation before import
- Not found → full HITL column dialog

## CHF resolution for debit_credit sign rule

When a file has both Amount and Debit/Credit columns and Debit is populated:
- Use Debit column for the CHF outflow amount (not Amount which may be local-currency)
- Pending rows (Debit/Credit empty, no Booked date) are skipped with a warning

## Output

After all files are processed, output a summary:
```
✓ <filename>: <N> rows imported  [auto-applied | user-confirmed]
✗ <filename>: skipped (<reason>)
```
