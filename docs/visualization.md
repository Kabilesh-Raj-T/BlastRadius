# Visualization

ChokePoint can generate Graphviz visualizations from a `Topology`.

## API

```python
from chokepoint.visualization import GraphvizVisualizer, VisualizationLayout

visualizer = GraphvizVisualizer()
dot = visualizer.export_dot(topology, layout=VisualizationLayout.HIERARCHICAL)
visualizer.write(topology, "topology.dot")
```

SVG and PNG rendering use the Graphviz `dot` executable:

```python
svg = visualizer.render_svg(topology)
png = visualizer.render_png(topology)
```

If Graphviz is not installed, DOT generation still works and render methods
raise `GraphvizRenderError`.

## Layouts

- `hierarchical` uses the Graphviz `dot` engine.
- `cluster` groups nodes by provider clusters.
- `radial` uses the Graphviz `twopi` engine.

## Color Scheme

| Color | Meaning |
| --- | --- |
| Red | Articulation points |
| Orange | Bridges |
| Blue | Cloud providers |
| Green | Applications |
| Gray | Infrastructure |

Every DOT output includes a legend cluster. Large graphs use deterministic node
ordering, edge concentration, spline edges, and overlap avoidance.

## Interactive HTML

For browser-based inspection, `render_interactive_html(topology)` returns a
standalone HTML document with search and provider/type filtering:

```python
from chokepoint.visualization import render_interactive_html

html = render_interactive_html(topology)
```

Topology data is embedded with script-safe JSON encoding, and dynamic node
details are rendered with DOM text nodes rather than raw HTML.
