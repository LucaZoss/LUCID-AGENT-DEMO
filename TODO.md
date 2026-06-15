# TODO

## REPL improvements (Stage 3 polish)
- [ ] Add more REPL helper commands (e.g. `/budget`, `/goal`, `/history`, `/reset`, `/help`)
- [ ] Add onboarding stage with plugin LLM Key — prompt user for `ANTHROPIC_API_KEY` (or other provider key) on first launch and persist it securely; skip if already set in env

## Stage 3 iteration
- [ ] Iterate and stabilise Stage 3 (LLM-wired agent loop, skill routing, context assembly)

---

## Roadmap

### Phase 4 — Event + Notification layer
Wire the transaction stream to `check_budget` and the tiered notifications (silent / informational / actionable), with the `Notifier` interface.
- [ ] `Notifier` interface + `ConsoleNotifier`
- [ ] Hook `check_budget` into the simulated transaction stream
- [ ] Tiered dispatch: silent → dashboard only, informational → digest queue, actionable → immediate push
- [ ] `diagnose_overspend` skill escalation for actionable tier (one human sentence + offered action)
- [ ] `TelegramNotifier` with inline buttons and deep-link back into chat
- [ ] Frequency cap + quiet hours (deterministic config, not agent logic)

### Phase 5 — Interface
FastAPI backend + real frontend with dashboard charts and live notifications.
- [ ] `POST /chat` → router → agent loop
- [ ] `GET /dashboard` → `build_dashboard_payload`
- [ ] Frontend: dashboard charts (needs/wants/savings over time, goal progress)
- [ ] Frontend: live notification feed (WebSocket or SSE)

### Phase 6 — Demo polish
Scripted demo mode for live walkthroughs.
- [ ] Scripted demo mode (deterministic seed data, reproducible run)
- [ ] Button to fire a budget-breaching transaction on cue
- [ ] Two rehearsed happy paths:
  - Open-ended saver ("I want to save more") → pay-yourself-first
  - Specific goal ("CHF 10k by December") → zero-based, goal as funded category
