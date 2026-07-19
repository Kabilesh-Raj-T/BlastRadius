"""Interactive HTML graph export."""

from __future__ import annotations

import json

from chokepoint.models import Topology


class InteractiveHtmlVisualizer:
    """Render a searchable, filterable HTML topology graph."""

    def render(self, topology: Topology) -> str:
        """Render topology as standalone interactive HTML.

        Args:
            topology: Topology to render.

        Returns:
            Standalone HTML document.
        """
        graph_data = {
            "nodes": [
                {
                    "id": node.id,
                    "name": node.name,
                    "provider": node.provider,
                    "node_type": node.node_type.value,
                }
                for node in sorted(topology.nodes.values(), key=lambda item: item.id)
            ],
            "edges": [
                {
                    "source": edge.source,
                    "target": edge.target,
                    "relationship": edge.relationship.value,
                }
                for edge in sorted(
                    topology.edges,
                    key=lambda item: (
                        item.source,
                        item.target,
                        item.relationship.value,
                    ),
                )
            ],
        }
        data = _script_safe_json(graph_data)
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>ChokePoint Interactive Graph</title>
  <style>
    body {{ font-family: Inter, Arial, sans-serif; margin: 0; color: #111827; }}
    header {{ display: flex; gap: 0.75rem; padding: 1rem; }}
    header {{ border-bottom: 1px solid #d1d5db; }}
    input, select {{ padding: 0.5rem; border: 1px solid #9ca3af; }}
    main {{ display: grid; grid-template-columns: 18rem 1fr; }}
    main {{ min-height: calc(100vh - 4rem); }}
    aside {{ border-right: 1px solid #d1d5db; overflow: auto; padding: 1rem; }}
    svg {{ width: 100%; height: calc(100vh - 4rem); background: #f9fafb; }}
    .node {{ cursor: pointer; }}
    .edge {{ stroke: #9ca3af; stroke-width: 1.4; }}
    .label {{ font-size: 12px; pointer-events: none; }}
  </style>
</head>
<body>
  <script id="graph-data" type="application/json">{data}</script>
  <header>
    <input id="search" aria-label="Search graph" placeholder="Search nodes">
    <select id="provider" aria-label="Filter provider"></select>
    <select id="nodeType" aria-label="Filter type"></select>
  </header>
  <main>
    <aside><strong>Nodes</strong><div id="list"></div></aside>
    <svg id="graph" role="img" aria-label="Infrastructure dependency graph"></svg>
  </main>
  <script>
    const data = JSON.parse(document.getElementById("graph-data").textContent);
    const search = document.getElementById("search");
    const provider = document.getElementById("provider");
    const nodeType = document.getElementById("nodeType");
    const list = document.getElementById("list");
    const svg = document.getElementById("graph");

    function fillSelect(select, values, label) {{
      select.innerHTML = `<option value="">${{label}}</option>`;
      values.forEach(value => select.add(new Option(value, value)));
    }}

    fillSelect(
      provider,
      [...new Set(data.nodes.map(node => node.provider))].sort(),
      "All providers"
    );
    fillSelect(
      nodeType,
      [...new Set(data.nodes.map(node => node.node_type))].sort(),
      "All types"
    );

    function visibleNodes() {{
      const term = search.value.toLowerCase();
      return data.nodes.filter(node =>
        (!provider.value || node.provider === provider.value) &&
        (!nodeType.value || node.node_type === nodeType.value) &&
        (!term || (`${{node.id}} ${{node.name}} ${{node.provider}} ` +
          `${{node.node_type}}`).toLowerCase().includes(term))
      );
    }}

    function render() {{
      const nodes = visibleNodes();
      const ids = new Set(nodes.map(node => node.id));
      const edges = data.edges.filter(edge =>
        ids.has(edge.source) && ids.has(edge.target)
      );
      const width = svg.clientWidth || 900;
      const height = svg.clientHeight || 600;
      const radius = Math.max(120, Math.min(width, height) * 0.38);
      const centerX = width / 2;
      const centerY = height / 2;
      const positions = new Map();
      nodes.forEach((node, index) => {{
        const angle = (Math.PI * 2 * index) / Math.max(nodes.length, 1);
        positions.set(node.id, {{
          x: centerX + Math.cos(angle) * radius,
          y: centerY + Math.sin(angle) * radius,
        }});
      }});
      svg.innerHTML = "";
      edges.forEach(edge => {{
        const source = positions.get(edge.source);
        const target = positions.get(edge.target);
        const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
        line.setAttribute("x1", source.x);
        line.setAttribute("y1", source.y);
        line.setAttribute("x2", target.x);
        line.setAttribute("y2", target.y);
        line.setAttribute("class", "edge");
        svg.appendChild(line);
      }});
      nodes.forEach(node => {{
        const position = positions.get(node.id);
        const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
        group.setAttribute("class", "node");
        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        circle.setAttribute("cx", position.x);
        circle.setAttribute("cy", position.y);
        circle.setAttribute("r", "18");
        circle.setAttribute(
          "fill",
          node.node_type === "service" ? "#2ca02c" : "#7f7f7f"
        );
        const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
        label.setAttribute("x", position.x + 24);
        label.setAttribute("y", position.y + 4);
        label.setAttribute("class", "label");
        label.textContent = node.name;
        group.append(circle, label);
        svg.appendChild(group);
      }});
      list.replaceChildren();
      nodes.forEach(node => {{
        const item = document.createElement("p");
        const code = document.createElement("code");
        const detail = document.createElement("span");
        code.textContent = node.id;
        detail.textContent = `${{node.node_type}} / ${{node.provider}}`;
        item.append(code, document.createElement("br"), detail);
        list.appendChild(item);
      }});
    }}

    [search, provider, nodeType].forEach(input =>
      input.addEventListener("input", render)
    );
    window.addEventListener("resize", render);
    render();
  </script>
</body>
</html>
"""


def render_interactive_html(topology: Topology) -> str:
    """Render a topology as interactive standalone HTML."""
    return InteractiveHtmlVisualizer().render(topology)


def _script_safe_json(value: object) -> str:
    """Serialize JSON so it is safe inside a script element."""
    return (
        json.dumps(value, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
