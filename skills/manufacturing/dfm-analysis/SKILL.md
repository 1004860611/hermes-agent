---
name: dfm-analysis
description: Use when analyzing injection-molded part manufacturability from STEP/STP CAD or inspecting PDF/PNG/JPG engineering drawings with the built-in dfm_project and dfm_analysis tools.
license: MIT
metadata:
  hermes:
    tags: [DFM, manufacturing, STEP, OCCT, CAD, engineering-drawing]
    requires_toolsets: [dfm]
---

# DFM Analysis

Manage every analysis as a durable DFM project. Tools are the source of
engineering facts; conversation is used to obtain missing facts and explain
traceable results.

## Workflow

1. Call `dfm_project` with `action=create` or resume a known project.
2. Call `dfm_project` with `action=add_input` for each STEP/STP or drawing
   reference. New NX/Parasolid input is not
   supported.
3. Inspect project `status` and the `occt` capability before planning.
4. Use `process=injection` for native geometry analysis. Ask only the
   clarification questions returned by the service. Never answer or confirm a
   fact on the user's behalf.
5. Call `dfm_analysis` with `action=plan`, `analyzer_key=occt` and an explicit
   `verification_level=experimental`. Version 0.1.0 has no certified
   calculators and never silently downgrades a certified request.
6. Inspect the persisted input hashes, `injection.geometry-core@4.0.0`
   operation DAG, rule provenance and `assumed_pull_direction`. If the pull
   direction was not confirmed, explain that the frozen `+Z` default was used.
7. Use `action=start` only for an available plan. Save the returned `run_id`
   and pass that exact ID to `status`, `result` or `cancel`. Start is
   non-blocking; do not busy-poll. Native OCCT measurements can legitimately
   remain in one named stage for several minutes. An unchanged percentage is
   not evidence that Hermes disconnected or that the worker is deadlocked.
8. Summarize measurements, Evaluation/Findings, recognized features, quality,
   topology references and artifact paths. State unresolved or experimental
   checks explicitly.

## Capability handling

- `geometry_engine_missing`: suggest `hermes dfm doctor`; never install system
  dependencies automatically.
- `verification_unavailable`: ask whether the user accepts an experimental
  plan; never imply certified coverage.
- `not_implemented`, `unsupported_capability`, `disabled`, `unhealthy`: report
  the exact limitation and preserve project/run IDs.

Drawing-only and fusion execution remain explicit unavailable capabilities.
The initial native engine supports injection only.

## Engineering integrity

- Never invent measurements, thresholds, findings, standards or successful checks.
- Never turn visual/model inference into a confirmed material, unit or pull direction.
- Geometry engine output is objective and experimental. Hermes alone performs
  rules, Evaluation, Finding and reporting.
- Prefer an explicit blocked/unavailable result over a guess.

## Recovery

After interruption, call project status and then run status with the recorded
ID. Inspect diagnostics events/stdout/stderr for failures. Never automatically
start a replacement run after timeout. Before the configured worker timeout,
call `cancel` with `confirm_cancel=true` only when the user explicitly asked to
stop that run. Never cancel, terminate the native PID, or start a replacement
solely because progress has not changed.
