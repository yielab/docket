"""``docket pod show`` -- Rich rendering of the reports built by ``core.pod_report``."""

from __future__ import annotations

from typing import Any

from docket import ui
from docket.core.pod_report import network_text


def _kv(label: str, value: object) -> None:
    ui.console.print(f"  {label} {value}", markup=False, highlight=False, soft_wrap=True)


def render_pod(report: dict[str, Any]) -> None:
    ui.header("pod", report["pod"])
    ui.section("Members")
    ui.table(
        [
            [
                m["id"],
                m["role"],
                f"{m['model']['value']} ({m['model']['source']})",
                m["verifyCmd"] or "-",
            ]
            for m in report["members"]
        ],
        ["MEMBER", "ROLE", "MODEL", "VERIFY"],
    )
    ui.section("Settings")
    ui.table(
        [[key, str(e["value"]), e["source"]] for key, e in report["settings"].items()],
        ["KEY", "VALUE", "SOURCE"],
    )
    approval = report["approvalMode"]
    ui.section("Dispatch")
    note = "unset: park without a TTY, wait on one" if approval["source"] == "unset" else "set"
    _kv("Approval mode:", f"{approval['effective']} ({note})")
    _kv("Pipeline:", report["pipeline"]["source"])
    _kv("Network:", network_text(report["network"]))
    if report["configSource"]:
        drift = report["drift"] or "unknown"
        _kv(
            "Config source:",
            f"{report['configSource']} (digest {report['configDigest'][:12]}..., drift: {drift})",
        )


def _render_endpoint(report: dict[str, Any]) -> None:
    model = report["model"]
    _kv("Role:", report["role"] or "(none)")
    _kv("Pod:", report["pod"] or "(not a pod member)")
    _kv("Workspace:", report["workspace"])
    _kv("Model:", f"{model['value']} ({model['source']})")
    endpoint = report["endpoint"]
    ready = "ready" if endpoint["ready"] else f"NOT ready - {endpoint['issue']}"
    _kv("Endpoint:", f"{endpoint['baseUrl'] or '(unresolved)'} ({ready})")
    provider = report["provider"]
    credential = provider["credential"]
    _kv(
        "Provider:",
        f"{provider['name'] or '(unresolved)'} ({provider['scope'] or 'unresolved'},"
        f" {provider['dialect']})",
    )
    _kv("Credential:", f"{credential['name'] or '(none)'} ({credential['source']})")


def _render_tools(report: dict[str, Any]) -> None:
    tools = report["tools"]
    mcp = [m["name"] for m in tools["mcpServers"]]
    ui.section("Tools")
    _kv("Tools allowed:", ", ".join(tools["allowed"]) or "(none)")
    _kv("Tools denied: ", ", ".join(d["name"] for d in tools["denied"]) or "(none)")
    _kv("MCP servers:  ", ", ".join(mcp) or "(none configured)")
    ui.section("Guardrail policies")
    if report["policies"]:
        ui.table(
            [[p["id"], p["hook"], p["action"]] for p in report["policies"]],
            ["ID", "HOOK", "ACTION"],
        )
    else:
        ui.dim("  No guardrail policies apply to this role.")


def _render_context(report: dict[str, Any]) -> None:
    prompt = report["prompt"]
    ui.section("Prompt composition")
    ui.table(
        [[s["name"], str(s["bytes"]), s["status"]] for s in prompt["sections"]],
        ["SECTION", "BYTES", "STATUS"],
    )
    ui.dim(f"  Static-context budget: {prompt['budgetTokens']} tokens ({prompt['budgetSource']})")
    pi = report["projectInstructions"]
    skills = ", ".join(f"{s['name']} ({s['scope']})" for s in report["skills"]) or "none"
    ui.section("Context")
    _kv("Project instr.:", f"{', '.join(pi['files'])} ({pi['source']})" if pi["source"] else "none")
    _kv("Skills:", skills)
    ui.section("Exporters")
    if report["exporters"]:
        for exp in report["exporters"]:
            _kv(
                f"{exp['name']:<14}",
                f"{exp['dialect']:<10} {exp['state']:<16} ({exp['scope']},"
                f" privacy: {exp['privacy']['label']})",
            )
    else:
        _kv("none", "enabled")


def render_member(report: dict[str, Any]) -> None:
    ui.header("member", report["id"])
    _render_endpoint(report)
    _render_tools(report)
    _render_context(report)
    if report["pipeline"] is not None:
        _kv("Pipeline:", report["pipeline"]["source"])
    _kv("Network:", network_text(report["network"]))
    if report["configSource"]:
        drift = report["drift"] or "unknown"
        _kv(
            "Config source:",
            f"{report['configSource']} (digest {report['configDigest'][:12]}..., drift: {drift})",
        )
    if report["podSettings"] is not None:
        ui.section("Pod settings")
        ui.table(
            [[k, str(e["value"]), e["source"]] for k, e in report["podSettings"].items()],
            ["KEY", "VALUE", "SOURCE"],
        )
