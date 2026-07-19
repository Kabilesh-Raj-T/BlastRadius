# Risk Engine

The ChokePoint risk engine consumes a `Topology` or a NetworkX graph produced
from a topology and emits a structured `RiskReport`.

## API

```python
from chokepoint.report import RiskAnalyzer

report = RiskAnalyzer().analyze(topology)
payload = report.export_json()
```

Use `RiskAnalyzer().analyze_graph(graph)` when the caller already has a
ChokePoint NetworkX graph.

## Rule Levels

| Level | Rules |
| --- | --- |
| Critical | Shared DNS, shared identity, shared CDN, shared secrets manager |
| High | Shared monitoring, shared networking |
| Medium | Shared CI/CD, shared email |
| Low | Single-service articulation |

Shared dependency rules trigger when at least two nodes directly or transitively
depend on a categorized node. Single-service articulation uses graph
articulation data and reports low risk when an articulation point sits on one
service dependency path.

## Report Fields

Each finding includes:

- `risk_score`
- `criticality`
- `blast_radius`
- `dependency_chain`
- `impacted_nodes`
- `impacted_providers`
- `explanation`

The report-level `risk_score` is the highest finding score. Scores are bounded
from `0` to `100` and combine severity, blast radius, and provider diversity.
