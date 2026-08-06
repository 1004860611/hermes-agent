import hashlib
import io
import json
from pathlib import Path

import pytest

from tools.dfm.analyzers.base import AnalyzerContext, CancellationToken
from tools.dfm.analyzers.parasolid import ParasolidAnalyzer
from tools.dfm.backends.nx.contracts import (
    NXArtifact,
    NXCalculatorCapability,
    NXCapability,
    NXJobStatus,
)
from tools.dfm.contracts import InputRecord, PlanOperation, PlanRecord, ResolvedArgument
from tools.dfm.errors import DFMError

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "dfm" / "nx"
SCHEMA_ROOT = Path(__file__).resolve().parents[3] / "tools" / "dfm" / "schemas"


class FakeNXClient:
    def __init__(self):
        self.cancelled = []
        self.submitted = []
        self.payload = json.dumps({
            "schema_version": 1,
            "process": "die_casting",
            "measurements": [],
            "producer_contract": "measurement_only",
        }).encode()

    def capability(self):
        return NXCapability(
            "available",
            "NX2406",
            "plugin-1.0",
            {"parasolid_xt": "available"},
            {
                "inspect_topology": NXCalculatorCapability(
                    "certified", output_quantities=("valid_brep",)
                )
            },
        )

    def submit(self, request, input_path):
        self.submitted.append((request, input_path))
        return NXJobStatus("nxjob_1", "queued")

    def status(self, job_id):
        return NXJobStatus(job_id, "succeeded", "complete", 100)

    def cancel(self, job_id):
        self.cancelled.append(job_id)
        return NXJobStatus(job_id, "cancelled")

    def artifacts(self, job_id):
        return [
            NXArtifact(
                "measurements",
                "measurements",
                "measurements.json",
                "application/json",
                hashlib.sha256(self.payload).hexdigest(),
                len(self.payload),
            )
        ]

    def download(self, job_id, artifact, target):
        target.write(self.payload)


class TaskContractNXClient(FakeNXClient):
    def __init__(self):
        super().__init__()
        self.payload = (
            FIXTURE_ROOT / "task_contract_measurements.json"
        ).read_bytes()

    def capability(self):
        return NXCapability.from_dict(
            json.loads((FIXTURE_ROOT / "task_contract_capability.json").read_text())
        )


def _context(tmp_path: Path):
    input_path = tmp_path / "inputs" / "part.x_t"
    input_path.parent.mkdir(exist_ok=True)
    input_path.write_text("Parasolid transmit text", encoding="ascii")
    input_record = InputRecord(
        "input_parasolid_1",
        "parasolid",
        "part.x_t",
        "inputs/part.x_t",
        input_path.stat().st_size,
        "a" * 64,
        "now",
        format_id="parasolid_xt",
        representation="brep",
    )
    plan = PlanRecord(
        "plan_1",
        "parasolid",
        ["parasolid"],
        "ready",
        "now",
        process="die_casting",
        scope_id="die_casting.topology-baseline",
        scope_version="1.0.0",
        input_ids=[input_record.input_id],
        operations=[
            PlanOperation("geometry.load", "load_geometry"),
            PlanOperation("geometry.topology", "inspect_topology", ["geometry.load"]),
        ],
    )
    return AnalyzerContext(
        "dfm_1", tmp_path, "parasolid", [input_record], "run_1", plan
    )


def test_nx_contract_fixtures_match_formal_json_schemas():
    jsonschema = pytest.importorskip("jsonschema")
    operation = json.loads((FIXTURE_ROOT / "task_contract_request.json").read_text())
    request = {
        "schema_version": 1,
        "run_id": "run_1",
        "process": "die_casting",
        "scope_id": "die_casting.golden-product",
        "scope_version": "1.0.0",
        "input": {
            "input_id": "input_1",
            "sha256": "a" * 64,
            "format_id": "parasolid_xt",
        },
        "operations": [operation],
    }
    capability = json.loads(
        (FIXTURE_ROOT / "task_contract_capability.json").read_text()
    )
    measurements = json.loads(
        (FIXTURE_ROOT / "task_contract_measurements.json").read_text()
    )

    for payload, schema_name in (
        (request, "nx_request.schema.json"),
        (capability, "nx_capability.schema.json"),
        (measurements, "measurement.schema.json"),
    ):
        schema = json.loads((SCHEMA_ROOT / schema_name).read_text())
        jsonschema.Draft202012Validator(schema).validate(payload)

    region_schema = json.loads((SCHEMA_ROOT / "region.schema.json").read_text())
    region = operation["arguments"]["region"]["value"]
    jsonschema.Draft202012Validator(region_schema).validate(region)


def test_parasolid_analyzer_uses_http_client_contract_and_downloads_measurements(
    tmp_path,
):
    client = FakeNXClient()
    analyzer = ParasolidAnalyzer(client, poll_interval_seconds=0)

    capability = analyzer.capability(_context(tmp_path))
    artifacts = analyzer.run(_context(tmp_path), CancellationToken())

    assert capability.status.value == "available"
    assert client.submitted[0][0]["process"] == "die_casting"
    assert client.submitted[0][0]["scope_id"] == "die_casting.topology-baseline"
    assert artifacts[0].kind == "measurements"
    assert (tmp_path / artifacts[0].relative_path).is_file()


def test_http_client_is_not_replaced_by_local_execution_when_unconfigured(tmp_path):
    analyzer = ParasolidAnalyzer()

    capability = analyzer.capability(_context(tmp_path))

    assert capability.status.value == "dependency_missing"
    assert capability.details["transport"] == "http"


def test_parasolid_analyzer_uses_production_contract_for_metric_scoped_operations(tmp_path):
    client = TaskContractNXClient()
    context = _context(tmp_path)
    context.plan.operations.append(
        PlanOperation(
            operation_id="draft.fixed_half",
            calculator_id="measure_draft",
            depends_on=["geometry.topology"],
            metric_ids=["dc.geometry.draft.fixed_half"],
            required_quantities=["draft_angle_deg"],
            arguments=_task_arguments(),
        )
    )

    analyzer = ParasolidAnalyzer(client, poll_interval_seconds=0)
    artifacts = analyzer.run(context, CancellationToken())

    request = client.submitted[0][0]
    assert request["schema_version"] == 1
    assert request["operations"][-1] == json.loads(
        (FIXTURE_ROOT / "task_contract_request.json").read_text()
    )
    assert artifacts[0].kind == "measurements"


def test_parasolid_capability_rejects_arguments_outside_certification_scope(
    tmp_path,
):
    client = TaskContractNXClient()
    context = _context(tmp_path)
    context.plan.operations.append(
        PlanOperation(
            operation_id="draft.fixed_half",
            calculator_id="measure_draft",
            depends_on=["geometry.topology"],
            metric_ids=["dc.geometry.draft.fixed_half"],
            required_quantities=["draft_angle_deg"],
            arguments={"pull_direction": _task_arguments()["pull_direction"]},
        )
    )

    capability = ParasolidAnalyzer(client).capability(context)

    assert capability.status.value == "not_implemented"
    assert capability.details["incompatible_operation_contracts"][0]["reasons"] == [
        "required_arguments"
    ]


def test_parasolid_analyzer_rejects_measurement_linked_to_wrong_metric(tmp_path):
    client = TaskContractNXClient()
    payload = json.loads(client.payload)
    payload["measurements"][0]["metric_id"] = "dc.geometry.draft.moving_half"
    client.payload = json.dumps(payload).encode()
    context = _context(tmp_path)
    context.plan.operations.append(
        PlanOperation(
            operation_id="draft.fixed_half",
            calculator_id="measure_draft",
            depends_on=["geometry.topology"],
            metric_ids=["dc.geometry.draft.fixed_half"],
            required_quantities=["draft_angle_deg"],
            arguments=_task_arguments(),
        )
    )

    with pytest.raises(DFMError) as exc_info:
        ParasolidAnalyzer(client, poll_interval_seconds=0).run(
            context, CancellationToken()
        )

    assert exc_info.value.code == "nx_result_invalid"


def _task_arguments():
    operation = json.loads((FIXTURE_ROOT / "task_contract_request.json").read_text())
    return {
        key: ResolvedArgument.from_dict(value)
        for key, value in operation["arguments"].items()
    }
