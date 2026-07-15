---
name: dfm-analysis
description: Use when analyzing injection-molded part manufacturability from STEP/STP CAD, PDF engineering drawings, or PNG/JPG drawing images with the built-in dfm_project and dfm_analysis tools.
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
2. Call `dfm_project` with `add_input` for every STEP/STP or drawing `@file:` reference.
3. Call project `status`. Inspect the input mode and every analyzer `capability`.
4. Ask only for missing facts that affect valid checks: material, molding process, units, nominal wall, or pull direction. Record answers with `confirm_fact`; keep them `confirmed`, not inferred.
5. Call `dfm_analysis` with `plan`. In M1, omitted process selection means the
   built-in `injection` adapter and its default `injection.legacy-baseline`
   scope. Inspect the returned process, scope version, input hashes, operations,
   and parameter provenance. Explain blocked checks and assumptions before
   execution.
6. Call `start` only when the selected capability is `available`. Preserve its `run_id`.
7. Poll run `status` without blocking the conversation. Use `cancel` when requested. Call `result` only after `succeeded`.
8. Summarize Findings with measurement, rule, evidence, confidence, and artifact path. State unresolved checks separately.

## Capability handling

- `dependency_missing`: explain the missing backend and suggest `hermes dfm doctor`; never install automatically.
- `not_implemented` or `unsupported_capability`: state the limitation and offer supported partial analysis.
- `disabled`: ask the user to configure and enable the capability in a new session.
- `unhealthy`: preserve project and Run IDs and report diagnostics.

M1 executes STEP geometry only for injection molding. If the user requests
machining, casting, sheet metal, or another process, do not relabel the
injection plan: report `unsupported_capability` and the supported process list.
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
