import argparse
import json

from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from hermes_cli.dfm import build_parser, collect_diagnostics, dfm_command


def test_dfm_doctor_reports_workspace_config_and_capabilities(tmp_path, capsys):
    token = set_hermes_home_override(tmp_path / "home")
    try:
        report = collect_diagnostics()
        assert report["ok"] is True
        assert report["workspace"]["writable"] is True
        assert report["config"]["valid"] is True
        assert set(report["capabilities"]) == {"step", "drawing", "fusion"}
        assert all(item["status"] != "available" for item in report["capabilities"].values())

        code = dfm_command(argparse.Namespace(dfm_action="doctor", json=True))
        output = json.loads(capsys.readouterr().out)
    finally:
        reset_hermes_home_override(token)

    assert code == 0
    assert output["workspace"]["writable"] is True


def test_dfm_parser_registers_doctor_subcommand():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    dfm_parser = build_parser(subparsers)
    dfm_parser.set_defaults(func=dfm_command)

    args = parser.parse_args(["dfm", "doctor", "--json"])

    assert args.dfm_action == "doctor"
    assert args.json is True


def test_dfm_is_a_builtin_cli_subcommand():
    from hermes_cli.main import _BUILTIN_SUBCOMMANDS

    assert "dfm" in _BUILTIN_SUBCOMMANDS
