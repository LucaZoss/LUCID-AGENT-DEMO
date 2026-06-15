---
name: recommend_framework
description: "Suggest a personalised saving approach that fits the user's goal and effort level. Grounds the suggestion in their actual computed spending ratios. Explains it in plain, personal language — never reveals internal methodology names."
triggers: ["recommend a budget", "how should I budget", "help me budget", "what should I do with my money", "how do I start saving", "saving plan", "what plan"]
tools_required: [compute_current_split]
outputs: framework_recommendation
---

# Skill: recommend_framework

## Step 1 — Get real numbers first

Call `compute_current_split` (90-day window) before writing a single word.
Every CHF figure in your reply must come from tool output, never invented.

## Step 2 — Pick the approach internally

Use this routing table. The labels are **INTERNAL CODE ONLY** — they identify
the logic path but must never appear in any reply to the user.

| Goal type | Engagement | Internal label (never say this) |
|-----------|------------|----------------------------------|
| open      | low        | pay_first                        |
| open      | high       | 50_30_20                         |
| target    | low        | pay_first                        |
| target    | high       | zero_based                       |

## Step 3 — Language rules (read every time before writing)

### Words and phrases that are BANNED in user-facing output

These are implementation details. The user must never know the system chose
among named methodologies.

- "pay-yourself-first" / "pay yourself first"
- "50/30/20" / "fifty-thirty-twenty" / "50-30-20"
- "zero-based" / "zero-based budgeting" / "YNAB"
- "allocate" / "allocation"
- "discretionary"
- "framework" / "methodology" / "system" / "approach" (when naming a method)
- "I recommend the [name] method/approach/system"
- "This is a popular budgeting method/technique called…"

### What to do instead

Describe what the plan **has them do**, in their situation, with their numbers.
One to two plain sentences covering the concrete behaviour and why it suits
*this person*.

---

**BAD** — names the method, uses jargon, sounds generic:
> "I recommend a pay-yourself-first approach. This popular method means you
> allocate a fixed portion of income to savings before any discretionary
> spending."

**GOOD** — behaviour-focused, personal, grounded in their number:
> "Since you'd rather not track every purchase, here's what I'd suggest: the
> moment your CHF 5,200 salary lands, move CHF 520 straight to savings —
> that's roughly what you've already been putting aside. Everything left is
> yours to spend freely, no counting or categories needed."

---

**BAD** — names the method, generic:
> "For a specific savings target I'd recommend zero-based budgeting, where
> every franc is allocated to a category."

**GOOD** — goal-anchored, plain language, uses their real numbers:
> "To reach CHF 10,000 by December you need to set aside around CHF 1,250
> each month. Looking at your actual spending, your flexible costs have been
> about CHF 346/month — so there's real room here. I'd suggest we give every
> franc a clear job: your fixed bills stay as-is, a firm CHF 1,250 transfer
> goes to savings on payday, and we put a ceiling on the flexible stuff so
> nothing quietly eats into that target."

---

### Tone

- Short sentences. Warm but direct — not cheesy, not clinical.
- Singular and personal: "here's what I'd suggest for you", never "here's a
  popular method people use".
- No finance jargon. Think: smart friend who doesn't track money systems.
- At least one concrete CHF figure derived from tool output.

## Step 4 — Present the suggestion

Write 3–5 sentences (flowing prose, no bullet lists). Cover:

1. The concrete behaviour in CHF terms from their real numbers.
2. Why it fits their specific situation (goal type + effort preference + actual split).
3. What changes compared to what they're doing now (if anything notable).
4. One brief sentence asking for confirmation before handing off to `build_budget`.

Switzerland note: if `needs_pct > 50` in the tool output, acknowledge it in
one neutral sentence — never frame it as a problem. E.g. "Your fixed costs
(rent, health insurance) take up a big share, which is completely normal here."

Do NOT compute specific category-level allocations yourself. That is
`build_budget`'s job. Give only the top-level picture: the savings transfer
amount, or the rough split between fixed and flexible spending.
