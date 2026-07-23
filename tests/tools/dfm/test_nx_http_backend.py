import hashlib
import io
import json
from pathlib import Path

from tools.dfm.analyzers.base import AnalyzerContext, CancellationToken
from tools.dfm.analyzers.parasolid import ParasolidAnalyzer
from tools.dfm.backends.nx.contracts import NXArtifact, NXCapability, NXJobStatus
from tools.dfm.contracts import InputRecord, PlanOperation, PlanRecord


class FakeNXClient:
    def __init__(self):
        self.cancelled = []
        self.submitted = []
        self.payload = json.dumps(
            {"process": "die_casting", "measurements": [], "evaluations": []}
        ).encode()

    def capability(self):
        return NXCapability(
            "available",
            "NX2406",
            "plugin-1.0",
            {"parasolid_xt": "available"},
            {"inspect_topology": "certified"},
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
            PlanOperation("geometry.load", "load_step"),
            PlanOperation("geometry.topology", "inspect_topology", ["geometry.load"]),
        ],
    )
    return AnalyzerContext(
        "dfm_1", tmp_path, "parasolid", [input_record], "run_1", plan
    )


def test_parasolid_analyzer_uses_http_client_contract_and_downloads_measurements(tmp_path):
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
