# Exports

ChokePoint exports topology and report data for automation, security review,
and documentation workflows.

## CLI

```bash
chokepoint export topology.yaml --format sarif
chokepoint export topology.yaml --format openapi
chokepoint export topology.yaml --format csv
chokepoint export topology.yaml --format mermaid
chokepoint export topology.yaml --format html
```

## API

```python
from chokepoint.report import (
    export_csv,
    export_mermaid,
    export_openapi,
    export_sarif,
    generate_security_report,
)

report = generate_security_report(topology)
sarif = export_sarif(report)
csv_payload = export_csv(topology)
```

## Diff

Topology diffs are available through the graph API and CLI:

```bash
chokepoint diff before.yaml after.yaml --json
```

```python
from chokepoint.graph import diff_topologies

diff = diff_topologies(before, after)
```

The diff reports added, removed, and changed nodes plus added and removed
edges.
