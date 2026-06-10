# Design: surfacing Overkiz command failures

Status: **implemented** (branch `overkiz-execution-result-await`)
Last updated: 2026-06-10

## Problem

The Overkiz API command path is fire-and-forget. `OverkizExecutor.async_execute_command`
calls `client.execute_action_group(...)`, which returns an `exec_id` the moment the
gateway *queues* the command — not when the device acts on it. Success or failure
arrives later, asynchronously, on the event-listener poll loop as
`ExecutionStateChangedEvent`s.

Before this change, `on_execution_state_changed` treated `COMPLETED` and `FAILED`
identically: it just `del`-ed the `exec_id` from `coordinator.executions`. A failed
command (motor unreachable, RF interference, priority lock, blocked by hazard) was
**silently discarded** — no log, no error to the caller, no way for automations to
react.

A first community PR (#173155) fired a custom `overkiz_execution_failed` event on the
HA event bus. This was rejected by maintainers: HA's convention is to raise
`HomeAssistantError` from the service call when a command fails, not to broadcast on
the bus. See the PR thread for the discussion.

## What the real event stream looks like

Captured from real gateways (IO protocol). Lifecycle of one command:

```
ExecutionRegistered
INITIALIZED -> NOT_TRANSMITTED -> TRANSMITTED   (instant)
TRANSMITTED -> IN_PROGRESS                       (device accepted, motor starts)
... DeviceStateChanged events while moving ...
IN_PROGRESS -> COMPLETED                          (physical movement finished)
```

Key measured facts that drive the design:

1. **`COMPLETED` latency is the physical travel time.** Observed 3 s for a short move,
   ~70 s for a full-travel shutter. Waiting for `COMPLETED` would block the service
   call for the entire movement.
2. **Failures come in two flavours, at two different times:**
   - *Pre-movement rejection* — e.g. `PRIORITY_LOCK__USER`. Arrives ~1 s, from
     `old_state=TRANSMITTED`, **before** `IN_PROGRESS`.
   - *Mid-movement failure* — e.g. `WHILEEXEC_BLOCKED_BY_HAZARD` (cover hit an
     obstacle). Arrives several seconds in, from `old_state=IN_PROGRESS`, **after**
     the device already accepted and started moving.
3. **On `FAILED`, top-level `event.device_url` is `None`.** The device context lives
   in `failed_commands[].device_url` and in our own `coordinator.executions[exec_id]`
   mapping. `failure_type` (str) and `failure_type_code` (`FailureType` IntEnum) are
   populated. We correlate via the stored `executions[exec_id]`, never the top-level
   `device_url`.
4. **RTS / stateless (`INTERNAL`) protocols are one-way** and never emit meaningful
   terminal execution events. Awaiting them would always hit the timeout.

## Decision

`async_execute_command` waits for the gateway to **acknowledge** the command — reaching
`IN_PROGRESS` (accepted) or a terminal state — then returns. It does **not** wait for
`COMPLETED`.

- Reached `IN_PROGRESS` or `COMPLETED` -> return normally.
- Reached `FAILED` *before* we returned (pre-movement rejection) -> raise
  `HomeAssistantError` carrying `failure_type`.
- No acknowledgement within `EXECUTION_RESULT_TIMEOUT` (10 s) -> return optimistically
  (assume success), so a dropped event or slow gateway never fails a command that
  likely worked.

Gating:
- Only when `refresh_afterwards=True`. Batched chains (`refresh_afterwards=False`,
  e.g. the water-heater flows) opt out — they have no per-command refresh to deliver
  the event, and awaiting mid-chain would deadlock.
- Only for bidirectional protocols. `Protocol.RTS` and `Protocol.INTERNAL` stay
  fire-and-forget.

Mechanism: `coordinator.execution_results: dict[exec_id, asyncio.Future]`. The executor
registers a future and awaits it under `asyncio.timeout`. `on_execution_state_changed`
resolves it (`set_result` on accept/terminal, `set_exception(HomeAssistantError)` on
pre-movement `FAILED`). `executions[exec_id]` is kept until the terminal state so cover
entities can keep deriving `is_opening`/`is_closing` from it.

## Behaviour matrix (against real captured timings)

| Case                         | Terminal arrives | Behaviour                          |
| ---------------------------- | ---------------- | ---------------------------------- |
| Priority lock (pre-move)     | ~1 s (pre-IP)    | **raises** `HomeAssistantError`    |
| Hazard block (mid-move)      | ~6 s (post-IP)   | logged warning, **not** raised     |
| Short successful move        | ~3 s             | returns at `IN_PROGRESS` (~1-2 s)  |
| Long full-travel move        | ~70 s            | returns at `IN_PROGRESS` (~1-2 s)  |
| No event (dropped / offline) | never            | returns optimistically at 10 s     |

## The deliberate trade-off (and why not the alternative)

The hazard-block failure (`WHILEEXEC_BLOCKED_BY_HAZARD`) arrives **after**
`IN_PROGRESS`, i.e. after we've already returned success. We therefore **cannot raise
on it** — we only log it. Catching it would require waiting for the terminal `FAILED`,
which means waiting out the whole movement (up to ~70 s).

We chose **not** to do that because:

- `await` does not freeze HA or serialise unrelated commands — the event loop keeps
  running, scenes fan out concurrently (`asyncio.gather`), other entities are
  unaffected. **But** a sequential script's next blocking step *does* wait for the
  call to return, and a scene reports "done" only when its slowest member returns.
  Waiting for completion would make every cover step in a script pause for the full
  travel time.
- It matches the dominant HA convention: >90% of integrations raise on
  *send-acceptance*, not on physical completion. (Exceptions like `tailwind` only
  block because their SDK does.)
- It keeps the responsive UX: a `cover.close` returns in ~1-2 s.

So: **non-blocking acceptance wait** beats **blocking completion wait** as the default.
We accept that mid-movement failures are observable in logs but not raised.

## If we want to switch later

To start raising on mid-movement failures (catch the hazard block), change the
resolution point from `IN_PROGRESS` to the **terminal** state:

1. In `on_execution_state_changed`, stop resolving the ack on `IN_PROGRESS`; resolve
   only on `COMPLETED` (result) / `FAILED` (exception).
2. Keep — and probably shorten — `EXECUTION_RESULT_TIMEOUT`, since the call now blocks for
   real movement time. Pick a value that catches typical failures (the hazard block
   landed ~6 s in) without making long full-travel moves (~70 s) routinely block. A
   ~10-15 s optimistic cap is the obvious starting point; covers that exceed it return
   optimistically and a late failure is only logged (same tail as today, just shifted).
3. Rewrite the cover tests that assert `CLOSING`/`OPENING` immediately after a blocking
   call — with a completion wait, the post-call snapshot and timing change. The test
   harness already supports delivering explicit terminal events
   (`mock_client.execution_result_state`).
4. Re-evaluate scene/script UX: every cover step would then pause until the cover stops
   or the timeout. This is the main reason we did not pick this initially — confirm the
   product wants it before flipping.

The split-by-failure-type idea (raise on pre-move, swallow mid-move) is already what we
do; the only lever is whether to *also* wait-and-raise for the mid-move terminal, at
the cost of blocking.

## Out of scope

- **RTS reliability.** One-way RTS gives no real feedback; the PR's original
  shutter-false-positive motivation largely lives here and cannot be solved by any
  await strategy.
- `failure_type_code` (the `FailureType` IntEnum) is not surfaced to users — only the
  `failure_type` string goes into the `HomeAssistantError` message. (The enum is also
  not JSON-serialisable, which would have been a latent bug in the bus-event approach.)

## Touch points

- `coordinator.py` — `execution_results` map, `register_execution_result`,
  `_resolve_pending_results` (called on `ServerDisconnectedError`), the rewritten
  `on_execution_state_changed`.
- `executor.py` — register the execution result + `asyncio.timeout` await in
  `async_execute_command`.
- `const.py` — `EXECUTION_RESULT_TIMEOUT`.
- `strings.json` — `exceptions.command_failed`.
- `tests/.../conftest.py` — mock gateway auto-acknowledges with
  `execution_result_state` (default `IN_PROGRESS`; `FAILED`/`None` for failure/timeout
  tests).
