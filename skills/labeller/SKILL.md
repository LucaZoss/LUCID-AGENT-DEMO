---
name: labeller
description: "Clean merchant names and classify imported transactions into need/want/savings buckets. Uses merchant memory for auto-apply, confidence-tiered batch confirmation for new merchants."
triggers: ["label transactions", "categorize transactions", "classify spending", "clean merchant names", "run labeller"]
tools_required: ["fetch_unlabelled", "lookup_merchant_memory", "propose_clean_name", "propose_bucket", "batch_confirm_with_user", "apply_labels"]
outputs: labelled_transactions
---

# Skill: labeller

Two-pass labelling with merchant memory.

## Steps

### Pass 1 — Memory lookup
1. `fetch_unlabelled(limit)` → batch of uncategorized outflow transactions
2. For each merchant: `lookup_merchant_memory(merchant)`
   - If `auto_apply = true` (user_confirmed, confidence ≥ 1.0, override_count < 3): mark for auto-apply
   - Otherwise: mark for HITL review

### Pass 2 — Propose for new merchants
3. `propose_clean_name(merchant)` → strips location suffix, title-cases
4. `propose_bucket(merchant, amount, sector_hint?)` → need/want/savings + confidence

### Confirmation
5. `batch_confirm_with_user(transactions)` → tiered UI:

   **AUTO-APPLIED** (confidence ≥ 1.0 AND source = user_confirmed):
   - Single keypress to accept all — no per-row display.

   **NEEDS REVIEW** (new merchants OR confidence < 1.0):
   - Table: raw name | clean name | CHF | proposed bucket | sector hint
   - Per-row: Enter=accept, n=need, w=want, s=savings, e=edit name

### Persist
6. `apply_labels(confirmed)` →
   - UPDATE `transactions.clean_name` and `transactions.category`
   - INSERT/UPDATE `merchant_category_overrides` with `source='user_confirmed'`, `confidence=1.0`

## Merchant memory logic

- Key: `merchant.strip().lower()` (raw string from CSV, not the clean name)
- After user confirms: upsert with source=user_confirmed, confidence=1.0
- override_count tracks how many times the user manually changed a suggestion
- Safety: override_count ≥ 3 → show in review tier even for known merchants

## Output

```
✓ N transaction(s) labelled (M auto-applied, K reviewed)
```
