# Benchmark Results

Benchmark date: 2026-07-19

Environment:

- OS: Windows
- Python: 3.12.13
- Package manager: uv
- Benchmark mode: release readiness smoke benchmarks

## Algorithmic Complexity

| Operation | Expected Complexity |
| --- | --- |
| Topology validation | `O(V + E)` |
| Graph construction | `O(V + E)` |
| Connected components | `O(V + E)` |
| Articulation points | `O(V + E)` |
| Bridges | `O(V + E)` |
| Degree centrality | `O(V + E)` |
| Betweenness centrality | `O(V * E)` |
| Cycle detection | `O(V + E)` |

## Smoke Benchmark Results

Synthetic topology shape:

- One shared DNS node.
- `N` service nodes.
- One service-to-DNS dependency per service.
- One additional service-to-service dependency after the first 10 services.

| Size | Build Graph | Full Graph Analysis | Risk Analysis | Security Report |
| ---: | ---: | ---: | ---: | ---: |
| 100 services | 2.53 ms | 26.02 ms | 11.26 ms | 38.34 ms |
| 500 services | 32.83 ms | 918.47 ms | 227.27 ms | 881.94 ms |
| 1,000 services | 31.21 ms | 3,020.29 ms | 741.71 ms | 3,965.94 ms |

## Release Verification

| Command | Result |
| --- | --- |
| `uv run black src tests` | Passed |
| `uv run ruff check src tests` | Passed |
| `uv run mypy` | Passed |
| `uv run pytest` | Passed, 150 tests, 95%+ coverage |
| `uv build` | Passed |

## Notes

The graph engine delegates centrality and structural analysis to NetworkX.
Exact betweenness centrality is the dominant cost in full graph analysis.
Risk analysis avoids exact centrality and uses validation plus articulation
point detection for its low-risk rule.
