# Graph Engine

The graph engine converts the ChokePoint `Topology` aggregate into a simple
undirected `networkx.Graph`. ChokePoint models infrastructure dependency
relationships as directed topology edges, but the first analysis pass focuses on
structural choke points in the undirected connectivity graph.

When multiple topology edges connect the same pair of nodes, the builder stores
all original `Edge` models on the single NetworkX edge. This preserves
relationship metadata while keeping the analysis graph compatible with standard
NetworkX algorithms for articulation points, bridges, connected components, and
centrality.

## API

```python
from chokepoint.graph import GraphAnalyzer, GraphBuilder

graph = GraphBuilder().build(topology)
report = GraphAnalyzer().analyze(graph)
```

`GraphBuilder.build(topology)` returns a `networkx.Graph`.
`GraphAnalyzer.analyze(graph)` returns an immutable `AnalysisReport`.

## Algorithms

| Operation | Algorithm | Time | Space |
| --- | --- | --- | --- |
| Build graph | Add every node and edge once | `O(V + E)` | `O(V + E)` |
| Validate graph | Attribute and preserved-edge checks | `O(V + E + R)` | `O(V + E)` |
| Connected components | Graph traversal | `O(V + E)` | `O(V)` |
| Articulation points | Low-link depth-first search | `O(V + E)` | `O(V)` |
| Bridges | Low-link depth-first search | `O(V + E)` | `O(V)` |
| Betweenness centrality | Unweighted Brandes algorithm | `O(V * E)` | `O(V + E)` |
| Degree centrality | Degree scan and normalization | `O(V + E)` | `O(V)` |
| Cycle detection | Undirected cycle basis | `O(V + E)` | `O(V + C)` |

`V` is the number of graph nodes, `E` is the number of NetworkX graph edges,
`R` is the number of preserved topology edge records, and `C` is the number of
cycles returned in the cycle basis.

## Validation

Validation verifies that the graph is undirected, is not a multigraph, contains
ChokePoint `Node` models on every NetworkX node, and contains preserved
ChokePoint `Edge` models plus relationship attributes on every NetworkX edge.
The analyzer refuses to produce an `AnalysisReport` for invalid graphs.
