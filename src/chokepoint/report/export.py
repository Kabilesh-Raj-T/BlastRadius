"""Security report and topology export formats."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from chokepoint.models import Topology
from chokepoint.report.generator import GeneratedReport

SARIF_SCHEMA_URL = "https://json.schemastore.org/sarif-2.1.0.json"
OPENAPI_VERSION = "3.1.0"
PROJECT_VERSION = "1.0.0"


class ReportExporter:
    """Export ChokePoint data to integration-friendly formats."""

    def sarif(self, report: GeneratedReport) -> str:
        """Export a generated report as SARIF 2.1.0."""
        rules = {
            finding.category.value: {
                "id": finding.category.value,
                "name": finding.category.value.replace("_", " ").title(),
                "shortDescription": {"text": finding.explanation},
                "defaultConfiguration": {
                    "level": _sarif_level(finding.risk_level.value)
                },
            }
            for finding in report.risk_report.findings
        }
        results = [
            {
                "ruleId": finding.category.value,
                "level": _sarif_level(finding.risk_level.value),
                "message": {"text": finding.explanation},
                "properties": {
                    "nodeId": finding.node_id,
                    "riskScore": finding.risk_score,
                    "blastRadius": finding.blast_radius,
                    "impactedNodes": list(finding.impacted_nodes),
                },
            }
            for finding in report.risk_report.findings
        ]
        payload: dict[str, Any] = {
            "$schema": SARIF_SCHEMA_URL,
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "ChokePoint",
                            "informationUri": "https://github.com/chokepoint/chokepoint",
                            "rules": list(rules.values()),
                        }
                    },
                    "results": results,
                    "properties": {
                        "riskScore": report.risk_score,
                        "findingCount": report.risk_report.finding_count,
                    },
                }
            ],
        }
        return json.dumps(payload, indent=2)

    def openapi(self) -> str:
        """Export ChokePoint report schemas as an OpenAPI document."""
        payload: dict[str, Any] = {
            "openapi": OPENAPI_VERSION,
            "info": {
                "title": "ChokePoint Report API",
                "version": PROJECT_VERSION,
            },
            "paths": {
                "/reports": {
                    "post": {
                        "summary": "Submit a ChokePoint security report",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/GeneratedReport"
                                    }
                                }
                            },
                        },
                        "responses": {"202": {"description": "Accepted"}},
                    }
                }
            },
            "components": {
                "schemas": {
                    "GeneratedReport": GeneratedReport.model_json_schema(),
                }
            },
        }
        return json.dumps(payload, indent=2)

    def csv(self, topology: Topology) -> str:
        """Export topology dependency edges as CSV."""
        stream = io.StringIO()
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(
            [
                "source",
                "target",
                "relationship",
                "source_provider",
                "target_provider",
                "source_type",
                "target_type",
            ]
        )
        for edge in sorted(
            topology.edges,
            key=lambda item: (item.source, item.target, item.relationship.value),
        ):
            source = topology.nodes[edge.source]
            target = topology.nodes[edge.target]
            writer.writerow(
                [
                    edge.source,
                    edge.target,
                    edge.relationship.value,
                    source.provider,
                    target.provider,
                    source.node_type.value,
                    target.node_type.value,
                ]
            )
        return stream.getvalue()

    def mermaid(self, topology: Topology) -> str:
        """Export topology as a Mermaid flowchart."""
        lines = ["flowchart LR"]
        for node in sorted(topology.nodes.values(), key=lambda item: item.id):
            lines.append(f'  {_mermaid_id(node.id)}["{_escape_mermaid(node.name)}"]')
        for edge in sorted(
            topology.edges,
            key=lambda item: (item.source, item.target, item.relationship.value),
        ):
            lines.append(
                "  "
                f"{_mermaid_id(edge.source)} -->|{edge.relationship.value}| "
                f"{_mermaid_id(edge.target)}"
            )
        return "\n".join(lines) + "\n"


def export_sarif(report: GeneratedReport) -> str:
    """Export a generated report as SARIF."""
    return ReportExporter().sarif(report)


def export_openapi() -> str:
    """Export the ChokePoint OpenAPI description."""
    return ReportExporter().openapi()


def export_csv(topology: Topology) -> str:
    """Export topology dependencies as CSV."""
    return ReportExporter().csv(topology)


def export_mermaid(topology: Topology) -> str:
    """Export topology dependencies as Mermaid."""
    return ReportExporter().mermaid(topology)


def _sarif_level(risk_level: str) -> str:
    if risk_level in {"critical", "high"}:
        return "error"
    if risk_level == "medium":
        return "warning"
    return "note"


def _mermaid_id(value: str) -> str:
    return "n_" + "".join(
        character if character.isalnum() else "_" for character in value
    )


def _escape_mermaid(value: str) -> str:
    return value.replace('"', '\\"')
