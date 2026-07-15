# DFM M1 Compatible Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the proven legacy STEP injection analyzer behind the M0 Hermes DFM contracts with a persisted execution plan, isolated worker process, recoverable lifecycle, and approved behavior baseline.

**Architecture:** The existing agent and two DFM model tools remain stable. `DFMService` compiles an immutable injection legacy-baseline plan, `JobManager` persists and executes that snapshot, `StepAnalyzer` adapts it to a versioned child-process protocol, and an isolated worker invokes the migrated deterministic OpenCascade implementation. Future drawing requirements and process adapters enter through plan inputs and provenance rather than changing the worker transport or agent loop.

**Tech Stack:** Python 3, dataclasses, Protocol, JSON/JSON Lines, `subprocess`, `threading`, `pathlib`, pythonocc-core/OpenCascade, pytest, Hermes tool registry and profile-aware Manifest storage.

## Global Constraints

- M1 production support is injection only; `generic`, `machining`, and all other process keys fail with `unsupported_capability`.
- Do not modify the Hermes agent loop, message alternation, prompt cache behavior, `_HERMES_CORE_TOOLS`, or the public `dfm_project` / `dfm_analysis` action sets.
- Do not import Django, DeepAgents, MinIO, Desktop, request context, or application models from the worker or DFM domain package.
- Do not auto-install OpenCascade or add a user-facing non-secret `HERMES_*` environment variable.
- Start workers with an argv list and `shell=False`; timeout and cancellation terminate the full Windows/POSIX process tree.
- Persist process, scope, versions, input hashes, parameters, units, provenance, and Run-to-Plan association before execution.
- Do not emit model-generated measurements, invented standards, placeholder Findings, or success without a valid completion result.
- Preserve the legacy full injection pipeline until comparison fixtures approve later check-family refactors.
- Every production behavior starts with a failing test and finishes with focused plus regression verification.

---

### Task 1: Freeze M1 plan and worker contracts

**Files:**
- Modify: `tools/dfm/contracts.py`
- Modify: `tools/dfm/analyzers/base.py`
- Test: `tests/tools/dfm/test_contracts.py`
- Create: `tests/tools/dfm/test_m1_contracts.py`

**Interfaces:**
- Consumes: M0 `PlanRecord`, `RunRecord`, `AnalyzerContext`, JSON Manifest serialization.
- Produces: `EffectiveParameter`, `PlanOperation`, `WorkerRequest`, `WorkerEvent`, `WorkerResult`; extended `PlanRecord` and `RunRecord` with backward-compatible defaults; `AnalyzerContext.plan`.

- [ ] **Step 1: Write failing round-trip and validation tests**

```python
def test_m1_plan_and_run_round_trip_preserves_execution_snapshot():
    plan = PlanRecord(
        "plan_1", "step", ["step"], "ready", "2026-07-15T00:00:00Z",
        process="injection", process_adapter_version="legacy-injection-v1",
        scope_id="injection.legacy-baseline", scope_version="1.0.0",
        input_ids=["input_1"], input_hashes={"input_1": "a" * 64},
        parameters={"min_wall_mm": EffectiveParameter(1.2, "mm", "injection_legacy_default")},
        operations=[PlanOperation("step.load", "load_step", [])],
    )
    run = RunRecord("run_1", "step", "worker-v1", RunStatus.QUEUED, "t", "t", plan_id=plan.plan_id, plan_snapshot=plan.to_dict())
    assert PlanRecord.from_dict(plan.to_dict()) == plan
    assert RunRecord.from_dict(run.to_dict()).plan_snapshot["scope_id"] == "injection.legacy-baseline"

def test_worker_event_rejects_unknown_type_and_invalid_percent():
    with pytest.raises(DFMError, match="worker_event_invalid"):
        WorkerEvent.from_dict({"schema_version": 1, "type": "mystery"})
    with pytest.raises(DFMError, match="worker_event_invalid"):
        WorkerEvent.from_dict({"schema_version": 1, "type": "progress", "percent": 101})
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/tools/dfm/test_m1_contracts.py -q`  
Expected: FAIL because the M1 contract classes and extended fields do not exist.

- [ ] **Step 3: Implement immutable JSON-compatible contracts**

```python
@dataclass(frozen=True)
class EffectiveParameter:
    value: Any
    unit: str | None
    source: str

@dataclass(frozen=True)
class PlanOperation:
    operation_id: str
    operation: str
    depends_on: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class WorkerRequest:
    schema_version: int
    run_id: str
    input_path: str
    output_dir: str
    process: str
    scope_id: str
    analyzer_version: str
    parameters: dict[str, EffectiveParameter]

@dataclass(frozen=True)
class WorkerEvent:
    schema_version: int
    type: str
    stage: str | None = None
    percent: int | None = None
    kind: str | None = None
    path: str | None = None
    code: str | None = None
    message: str | None = None

@dataclass(frozen=True)
class WorkerResult:
    schema_version: int
    worker_version: str
    input_sha256: str
    process: str
    scope_id: str
    parameters: dict[str, EffectiveParameter]
    result_path: str
    artifacts: list[dict[str, str]] = field(default_factory=list)
```

Add keyword-only-compatible default fields after the existing required `PlanRecord`/`RunRecord` fields so M0 positional construction and old manifests continue to load. Add `plan: PlanRecord | None = None` to `AnalyzerContext`.

- [ ] **Step 4: Run focused and M0 regression tests**

Run: `python -m pytest tests/tools/dfm/test_m1_contracts.py tests/tools/dfm/test_contracts.py tests/tools/dfm/test_manifest_store.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/dfm/contracts.py tools/dfm/analyzers/base.py tests/tools/dfm/test_contracts.py tests/tools/dfm/test_m1_contracts.py
git commit -m "feat(dfm): define m1 execution contracts"
```

### Task 2: Add the injection process adapter and versioned default scope

**Files:**
- Create: `tools/dfm/processes/__init__.py`
- Create: `tools/dfm/processes/base.py`
- Create: `tools/dfm/processes/registry.py`
- Create: `tools/dfm/processes/injection.py`
- Create: `tools/dfm/scopes/injection/legacy_baseline_v1.json`
- Create: `tests/tools/dfm/test_process_adapters.py`

**Interfaces:**
- Consumes: `AnalyzerContext`, `EffectiveParameter`, `PlanOperation`, legacy analyzer parser defaults after Task 4.
- Produces: `ProcessAdapter` protocol; `ProcessAdapterRegistry`; `InjectionProcessAdapter.compile(context, raw_parameters) -> ProcessPlan`; `build_default_process_registry()`.

- [ ] **Step 1: Write failing injection-only registry tests**

```python
def test_default_process_registry_supports_injection_only():
    registry = build_default_process_registry()
    assert registry.keys() == ("injection",)
    with pytest.raises(DFMError) as exc:
        registry.get("machining")
    assert exc.value.code == "unsupported_capability"
    assert exc.value.details["supported_processes"] == ["injection"]

def test_injection_default_scope_has_versioned_parameter_provenance(context):
    plan = build_default_process_registry().get("injection").compile(context, {})
    assert plan.scope_id == "injection.legacy-baseline"
    assert plan.parameters["min_draft_deg"].source == "injection_legacy_default"
    assert plan.parameters["min_draft_deg"].unit == "degree"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/tools/dfm/test_process_adapters.py -q`  
Expected: FAIL because `tools.dfm.processes` is absent.

- [ ] **Step 3: Implement a minimal real-consumer protocol and registry**

```python
@runtime_checkable
class ProcessAdapter(Protocol):
    key: str
    version: str
    def capability(self, context: AnalyzerContext) -> Capability: ...
    def compile(self, context: AnalyzerContext, raw_parameters: Mapping[str, Any]) -> ProcessPlan: ...

class ProcessAdapterRegistry:
    def register(self, adapter: ProcessAdapter) -> None: ...
    def get(self, key: str) -> ProcessAdapter: ...
    def keys(self) -> tuple[str, ...]: ...

@dataclass(frozen=True)
class ProcessPlan:
    process: str
    adapter_version: str
    scope_id: str
    scope_version: str
    parameters: dict[str, EffectiveParameter]
    operations: list[PlanOperation]
```

Load the scope JSON through `importlib.resources`/a package-relative `Path`; validate its exact ID/version/process and reject unknown user parameter keys. Normalize `pull_dir` to three floats and positive numeric thresholds. Values supplied by confirmed project facts use `project_fact`; scope values use `injection_legacy_default`.

- [ ] **Step 4: Run adapter tests**

Run: `python -m pytest tests/tools/dfm/test_process_adapters.py -q`  
Expected: PASS and no OpenCascade import.

- [ ] **Step 5: Commit**

```bash
git add tools/dfm/processes tools/dfm/scopes tests/tools/dfm/test_process_adapters.py
git commit -m "feat(dfm): add injection process adapter"
```

### Task 3: Implement the versioned worker event protocol and process runner

**Files:**
- Create: `tools/dfm/runtime/events.py`
- Create: `tools/dfm/runtime/process.py`
- Create: `tests/tools/dfm/fixtures/worker_fixture.py`
- Create: `tests/tools/dfm/test_worker_events.py`
- Create: `tests/tools/dfm/test_process_runner.py`

**Interfaces:**
- Consumes: `WorkerEvent`, `CancellationToken`, `DFMError`.
- Produces: `encode_worker_event(event) -> str`; `parse_worker_event(line) -> WorkerEvent | None`; `ProcessResult`; `ProcessRunner.run(argv, cwd, timeout_seconds, cancellation, on_event) -> ProcessResult`.

- [ ] **Step 1: Write failing parser and real-child-process tests**

```python
def test_process_runner_streams_events_and_keeps_stderr_separate(tmp_path):
    events = []
    result = ProcessRunner().run(
        [sys.executable, str(FIXTURE), "success"], tmp_path, 5,
        CancellationToken(), events.append,
    )
    assert result.returncode == 0
    assert [event.type for event in events] == ["progress", "completed"]
    assert "fixture diagnostic" in result.stderr

def test_process_runner_times_out_and_cancels_process_tree(tmp_path):
    with pytest.raises(DFMError) as timeout:
        ProcessRunner().run([sys.executable, str(FIXTURE), "hang"], tmp_path, 1, CancellationToken(), lambda _: None)
    assert timeout.value.code == "worker_timeout"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/tools/dfm/test_worker_events.py tests/tools/dfm/test_process_runner.py -q`  
Expected: FAIL because event/runtime modules are absent.

- [ ] **Step 3: Implement JSON Lines parsing and cross-platform process-tree control**

Use prefix `__HERMES_DFM_EVENT__ ` followed by one compact JSON object. Ignore non-prefixed stdout as diagnostics. Use `CREATE_NEW_PROCESS_GROUP` on Windows and `start_new_session=True` on POSIX; on cancellation/timeout use `taskkill /PID <pid> /T /F` or `os.killpg(pid, SIGTERM)`, wait briefly, then hard-kill if required. Never use `shell=True`.

- [ ] **Step 4: Run focused tests including paths with spaces and Chinese characters**

Run: `python -m pytest tests/tools/dfm/test_worker_events.py tests/tools/dfm/test_process_runner.py -q`  
Expected: PASS with no surviving fixture child process.

- [ ] **Step 5: Commit**

```bash
git add tools/dfm/runtime/events.py tools/dfm/runtime/process.py tests/tools/dfm/fixtures/worker_fixture.py tests/tools/dfm/test_worker_events.py tests/tools/dfm/test_process_runner.py
git commit -m "feat(dfm): add isolated worker runtime"
```

### Task 4: Migrate the legacy analyzer and wrap it as a Hermes worker

**Files:**
- Create by exact mechanical copy: `tools/dfm/geometry/step/legacy_analyzer.py`
- Create: `tools/dfm/geometry/__init__.py`
- Create: `tools/dfm/geometry/step/__init__.py`
- Create: `tools/dfm/workers/__init__.py`
- Create: `tools/dfm/workers/step_worker.py`
- Create: `tests/tools/dfm/test_step_worker.py`

**Interfaces:**
- Consumes: `WorkerRequest`, event encoder, migrated legacy `build_parser()`, `normalize_args()`, `thresholds_dict()`, and `main(argv)`.
- Produces: `python -m tools.dfm.workers.step_worker --request <request.json>`; a valid `WorkerResult` and contained artifacts.

- [ ] **Step 1: Write failing worker capability and request tests**

```python
def test_worker_rejects_non_injection_before_occ_import(tmp_path):
    request = make_request(tmp_path, process="machining")
    result = run_worker(request)
    assert result.returncode != 0
    assert event(result.stdout, "error")["code"] == "unsupported_capability"

def test_worker_reports_dependency_missing_without_fabricated_result(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT))
    result = run_worker(make_request(tmp_path), python=python_without_occ)
    assert event(result.stdout, "error")["code"] == "dependency_missing"
    assert not (tmp_path / "out" / "worker_result.json").exists()
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/tools/dfm/test_step_worker.py -q`  
Expected: FAIL because the worker and migrated module are absent.

- [ ] **Step 3: Mechanically copy the proven analyzer, preserving attribution**

Copy `backend/aimold_app/agents/skill/dfm-analysis/scripts/dfm_analyze.py` from the named Django workspace to `tools/dfm/geometry/step/legacy_analyzer.py` without algorithm edits. Add a module note naming the migration source and commit hash/path if available. This exact large-file migration is mechanical; subsequent integration edits use patches.

- [ ] **Step 4: Implement the thin worker wrapper**

The wrapper validates request schema/process/path containment, probes `OCC`, converts effective parameters into a temporary legacy config, monkey-patches only the legacy event emitter to the versioned Hermes event encoder, invokes `legacy_analyzer.main(argv)`, scans the output directory, writes `worker_result.json`, and emits `artifact` plus `completed`. It returns nonzero and emits a stable `error` on dependency or execution failure.

- [ ] **Step 5: Run no-OCC and real-OCC tests**

Run: `python -m pytest tests/tools/dfm/test_step_worker.py -q`  
Expected: unconditional protocol tests PASS; real STEP test PASS when `OCC` is installed, otherwise SKIP with an explicit dependency reason.

- [ ] **Step 6: Commit**

```bash
git add tools/dfm/geometry tools/dfm/workers tests/tools/dfm/test_step_worker.py
git commit -m "feat(dfm): migrate legacy step worker"
```

### Task 5: Connect StepAnalyzer and persisted Plan execution

**Files:**
- Modify: `tools/dfm/analyzers/step.py`
- Modify: `tools/dfm/runtime/jobs.py`
- Modify: `tools/dfm/service.py`
- Modify: `tests/tools/dfm/test_jobs.py`
- Modify: `tests/tools/dfm/test_service.py`
- Create: `tests/tools/dfm/test_step_analyzer.py`

**Interfaces:**
- Consumes: process registry, `ProcessRunner`, persisted `PlanRecord`, `WorkerRequest` and worker events.
- Produces: production `StepAnalyzer.capability()` and `run()`; `JobManager.start(..., plan: PlanRecord)`; deterministic plan compilation in `DFMService.analysis("plan")`.

- [ ] **Step 1: Write failing service/analyzer lifecycle tests**

```python
def test_service_compiles_and_persists_default_injection_plan(service_with_worker):
    plan = service_with_worker.analysis("plan", project_id=project_id)["plan"]
    assert plan["process"] == "injection"
    assert plan["scope_id"] == "injection.legacy-baseline"
    assert plan["input_hashes"][input_id] == input_sha256
    assert plan["parameters"]["min_draft_deg"]["source"] == "injection_legacy_default"

def test_job_executes_the_persisted_plan_snapshot(service_with_worker):
    started = service_with_worker.analysis("start", project_id=project_id, plan_id=plan_id)
    run = poll_terminal(started["run"]["run_id"])
    assert run["plan_id"] == plan_id
    assert run["plan_snapshot"]["scope_id"] == "injection.legacy-baseline"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/tools/dfm/test_step_analyzer.py tests/tools/dfm/test_service.py tests/tools/dfm/test_jobs.py -q`  
Expected: FAIL because StepAnalyzer remains M0-unavailable and JobManager discards Plan details.

- [ ] **Step 3: Implement plan compilation and immutable execution**

`DFMService.analysis("plan")` selects STEP, injection, and the legacy baseline; merges confirmed facts into adapter parameters; stores input IDs/hashes and capability. `analysis("start")` loads the named plan and passes the complete record to `JobManager.start`. The manager stores `plan_id`/`plan_snapshot`, reconstructs `AnalyzerContext(..., plan=plan)` in `_execute`, and never recomputes the plan.

- [ ] **Step 4: Implement StepAnalyzer worker adaptation**

Capability is available only when the worker module and `OCC` are importable. `run()` creates `runs/<run_id>/request.json` and `artifacts/`, invokes the runner, validates completion/result versions and every artifact path, then returns `ArtifactRecord` values. Cancellation and timeout errors propagate with stable codes to JobManager.

- [ ] **Step 5: Run focused and M0 regression tests**

Run: `python -m pytest tests/tools/dfm/test_step_analyzer.py tests/tools/dfm/test_service.py tests/tools/dfm/test_jobs.py tests/tools/dfm/test_m0_e2e.py -q`  
Expected: PASS; M0 injected analyzers still work through backward-compatible defaults.

- [ ] **Step 6: Commit**

```bash
git add tools/dfm/analyzers/step.py tools/dfm/runtime/jobs.py tools/dfm/service.py tests/tools/dfm/test_step_analyzer.py tests/tools/dfm/test_service.py tests/tools/dfm/test_jobs.py
git commit -m "feat(dfm): execute persisted injection plans"
```

### Task 6: Update agent guidance and diagnostics without growing the tool surface

**Files:**
- Modify: `skills/manufacturing/dfm-analysis/SKILL.md`
- Modify: `hermes_cli/dfm.py`
- Modify: `tests/tools/dfm/test_skill_contract.py`
- Modify: `tests/hermes_cli/test_dfm_command.py`
- Modify: `tests/tools/dfm/test_tool_surface.py`

**Interfaces:**
- Consumes: service capability, injection default scope, existing `hermes dfm doctor`, stable DFM tool schemas.
- Produces: executable Skill instructions and doctor output for worker/process/scope versions.

- [ ] **Step 1: Write failing behavior-contract tests**

```python
def test_skill_uses_default_injection_scope_and_forbids_invented_standards():
    text = SKILL.read_text(encoding="utf-8")
    assert "injection.legacy-baseline" in text
    assert "unsupported_capability" in text
    assert "不得编造" in text or "never invent" in text.lower()

def test_public_action_sets_remain_stable():
    schema = registry.get_schema("dfm_analysis")
    assert schema["parameters"]["properties"]["action"]["enum"] == ["plan", "start", "status", "cancel", "result"]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/tools/dfm/test_skill_contract.py tests/hermes_cli/test_dfm_command.py tests/tools/dfm/test_tool_surface.py -q`  
Expected: FAIL because M1 guidance/diagnostics are absent.

- [ ] **Step 3: Update Skill and doctor**

Document the Agent -> plan -> Agent -> start -> status/result flow, injection-only boundary, default scope behavior, clarification on blocked plans, and prohibition on fabricated measurements/standards. Doctor reports worker import path, OCC dependency, supported process list, scope ID/version, workspace writability, and config without installing dependencies.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/tools/dfm/test_skill_contract.py tests/hermes_cli/test_dfm_command.py tests/tools/dfm/test_tool_surface.py -q`  
Expected: PASS and tool action enums unchanged.

- [ ] **Step 5: Commit**

```bash
git add skills/manufacturing/dfm-analysis/SKILL.md hermes_cli/dfm.py tests/tools/dfm/test_skill_contract.py tests/hermes_cli/test_dfm_command.py tests/tools/dfm/test_tool_surface.py
git commit -m "docs(dfm): guide m1 injection workflow"
```

### Task 7: Freeze the Django/Hermes baseline and verify the M1 vertical slice

**Files:**
- Create: `tests/tools/dfm/baseline.py`
- Create: `tests/tools/dfm/test_m1_baseline.py`
- Create or import approved fixtures under: `tests/fixtures/dfm/step/`
- Create: `tests/tools/dfm/test_m1_e2e.py`
- Modify: `docs/plans/2026-07-13-dfm-hermes-agent-development-roadmap.md`

**Interfaces:**
- Consumes: legacy Django analyzer path, Hermes worker, explicit injection profile, real tool discovery and temporary `HERMES_HOME`.
- Produces: relationship/tolerance comparison report; complete M1 E2E evidence; roadmap status update only after verification.

- [ ] **Step 1: Write failing comparison and E2E tests**

```python
def test_legacy_and_hermes_measurements_are_equivalent(approved_fixture, explicit_profile):
    old = run_legacy(approved_fixture, explicit_profile)
    new = run_hermes_worker(approved_fixture, explicit_profile)
    assert new["stats"]["valid_brep"] == old["stats"]["valid_brep"]
    assert new["stats"]["bbox_size_mm"] == pytest.approx(old["stats"]["bbox_size_mm"], abs=0.01)
    assert comparable_metrics(new["issues"]) == pytest.approx(comparable_metrics(old["issues"]), rel=1e-5, abs=1e-4)

def test_m1_real_tool_vertical_slice(temp_hermes_home, approved_fixture):
    project = dispatch("dfm_project", {"action": "create", "name": "M1 E2E"})
    dispatch("dfm_project", {"action": "add_input", "project_id": project["project_id"], "path": str(approved_fixture)})
    plan = dispatch("dfm_analysis", {"action": "plan", "project_id": project["project_id"]})
    run = dispatch("dfm_analysis", {"action": "start", "project_id": project["project_id"], "plan_id": plan["plan"]["plan_id"]})
    result = poll_result(project["project_id"], run["run"]["run_id"])
    assert result["run"]["status"] == "succeeded"
    assert {a["kind"] for a in result["run"]["artifacts"]} >= {"report_json", "report_markdown"}
```

- [ ] **Step 2: Run tests and verify RED or explicit dependency skip**

Run: `python -m pytest tests/tools/dfm/test_m1_baseline.py tests/tools/dfm/test_m1_e2e.py -q`  
Expected: FAIL until migration integration is complete; if OCC is unavailable, only tests marked as real-OCC SKIP with a clear reason.

- [ ] **Step 3: Add approved fixtures and comparison helpers**

Use synthetic fixtures from the existing Django generator or explicitly approved non-sensitive files. Compare relationships and numerical tolerances, not total issue counts. Record the exact legacy source path/hash, worker version, profile JSON, platform, and OCC version in failure output.

- [ ] **Step 4: Run the full M1 verification matrix**

Run: `python -m pytest tests/tools/dfm tests/hermes_cli/test_dfm_command.py tests/test_toolsets.py -q`  
Expected: PASS, with only documented dependency-gated skips.

Run: `python -m py_compile tools/dfm_tool.py tools/dfm/*.py tools/dfm/analyzers/*.py tools/dfm/processes/*.py tools/dfm/runtime/*.py tools/dfm/workers/*.py tools/dfm/geometry/step/*.py hermes_cli/dfm.py`  
Expected: exit 0.

Run: `git diff --check`  
Expected: exit 0.

- [ ] **Step 5: Update roadmap only from verified evidence**

Mark M1 `已完成` only if a real approved STEP fixture passes both legacy comparison and Hermes E2E with OCC installed. Otherwise mark `评审中` or `受阻` and link the exact passing protocol/runtime evidence plus the missing dependency/baseline evidence.

- [ ] **Step 6: Commit**

```bash
git add tests/tools/dfm/baseline.py tests/tools/dfm/test_m1_baseline.py tests/tools/dfm/test_m1_e2e.py tests/fixtures/dfm/step docs/plans/2026-07-13-dfm-hermes-agent-development-roadmap.md
git commit -m "test(dfm): verify m1 compatible migration"
```

## M1 Completion Gate

- Injection is the only production process and the default scope is versioned.
- A persisted Plan snapshot, not live model output, drives every Run.
- The real worker runs outside Django through argv, supports timeout/cancellation, and emits validated events/artifacts.
- The migrated analyzer remains behaviorally equivalent on approved fixtures within recorded tolerances.
- Failure, timeout, cancellation, invalid artifacts, and restart remain recoverable through Manifest state.
- The public DFM tool action sets, default-off toolset behavior, Agent Loop, Desktop upload, and prompt caching remain unchanged.
