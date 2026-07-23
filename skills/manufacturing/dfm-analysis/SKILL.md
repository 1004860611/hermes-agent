---
name: dfm-analysis
description: Use when analyzing injection-molded or die-cast part manufacturability from STEP/STP CAD, reserved Parasolid x_t input, PDF engineering drawings, or PNG/JPG drawing images with the built-in dfm_project and dfm_analysis tools.
license: MIT
metadata:
  hermes:
    tags: [DFM, manufacturing, STEP, CAD, engineering-drawing]
    requires_toolsets: [dfm]
---

# DFM Analysis

Manage every analysis as a durable DFM project. Treat tools as the source of engineering facts; use conversation to clarify intent and explain evidence.

## Workflow

The control boundary is `Agent -> plan -> Agent -> start`: planning is a
deterministic service operation, and the Agent must inspect the persisted plan
and capability before deciding whether execution is valid. Starting a plan does
not bypass that decision or return control to the Agent Loop from inside the
worker.

1. Call `dfm_project` with `create`, unless continuing a known `project_id`.
2. Call `dfm_project` with `add_input` for every STEP/STP, Parasolid x_t, or drawing `@file:` reference. An accepted x_t intake does not mean its geometry reader is available; inspect capability before planning.
3. Call project `status`. Inspect the input mode and every analyzer `capability`.
4. Pass `process=injection` or `process=die_casting` when the user has selected it; never infer the process from part shape. Ask only the process adapter's returned missing facts. If `dfm_analysis(plan)` returns `status=clarification_required`, it is a hard stop: do **not** answer the questions yourself and do **not** call `confirm_fact` in the same turn. Call the Hermes `clarify` tool for each open question so Desktop shows its blocking question panel; wait for the user's response, then call `confirm_fact` with exactly that response. Use the canonical fact names returned by the service; keep them `confirmed`, not inferred.
5. Call `dfm_analysis` with `plan`. Omitted process selection keeps the project's
   current process; a new project defaults to the compatible `injection` adapter
   and `injection.legacy-baseline` scope. Die casting currently exposes only its
   approved topology gate. Inspect the returned process, scope version, input hashes, operations,
   and parameter provenance. Explain blocked checks and assumptions before
   execution.
6. Call `start` only when the selected capability is `available`. Preserve its `run_id`.
7. `start` is non-blocking. Immediately save the returned `run_id` and pass that exact ID to every subsequent `status`, `result`, or `cancel` call; never omit it or invent a replacement. The run publishes background stage, percentage,
   heartbeat, and incremental artifact updates to supported clients. Return
   control to the user after starting; do not spend Agent turns on terminal
   sleep loops or rapid status polling. Use `status` when the user asks, after
   reconnecting, or after a meaningful external wait. Use `cancel` when
   requested. Call `result` only after `succeeded`.
8. Summarize Findings with measurement, rule, evidence, confidence, and artifact path. State unresolved checks separately. For a successful STEP run, present `dfm_report.pptx` as the primary human-readable report; retain JSON and Markdown as traceable engineering artifacts. Do not ask the model to recreate the deterministic PPTX.

## Capability handling

- `dependency_missing`: explain the missing backend (OpenCascade or python-pptx) and suggest `hermes dfm doctor`; never install automatically.
- `not_implemented` or `unsupported_capability`: state the limitation and offer supported partial analysis.
- `disabled`: ask the user to configure and enable the capability in a new session.
- `unhealthy`: preserve project and Run IDs and report diagnostics.

STEP geometry supports the established injection scope and the initial die-casting
topology gate. Do not run injection thresholds under a die-casting label. If the
user requests machining, sheet metal, or another process, report
`unsupported_capability` and the supported process list. Parasolid x_t remains
an explicit reserved capability until an approved licensed reader is installed.
Drawing-only and Fusion execution remain explicit unavailable capabilities.

## Engineering integrity

- Never invent measurements, thresholds, risk scores, Findings, or successful checks.
- Never invent engineering standards, standard codes, drawing requirements, or
  claim that the legacy default scope is a customer or regulatory standard.
- Never convert visual impression or model inference into a confirmed engineering fact.
- Never claim a STEP-only check ran against drawing-only input.
- Never treat a technical test artifact as a production DFM conclusion.
- Prefer explicit unavailable or blocked results over guesses.

## Recovery

After interruption, call project `status`, then run `status` with the recorded IDs. Do not create a replacement project or duplicate Run unless the user requests a new revision.

For a failed or slow run, inspect the `diagnostics.events`,
`diagnostics.stdout`, and `diagnostics.stderr` paths returned by run status.
Partial artifacts remain attached to the Run even when it times out. Never
automatically start a replacement Run after timeout.
