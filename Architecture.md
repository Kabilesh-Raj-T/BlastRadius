# Architecture

ChokePoint follows clean architecture principles. Domain concepts live at the
center of the package, while input parsing, graph analysis, reporting, and
command-line concerns remain isolated around that core.

## Package Layout

```text
src/chokepoint/
    cli/
    graph/
    models/
    parser/
    report/
    utils/
    visualization/
```

## System Diagram

```mermaid
flowchart LR
    cli["CLI"] --> parser["Parsers"]
    parser --> models["Topology Models"]
    models --> graph["Graph Engine"]
    graph --> report["Risk Reports"]
    report --> cli
    report --> exports["Exports"]
```

## Boundaries

- `models` contains domain types and value objects.
- `parser` converts external infrastructure descriptions into domain models.
- `graph` builds and analyzes dependency graphs from domain models.
- `report` turns analysis results into user-facing report data.
- `utils` contains shared formatting helpers used across adapters.
- `visualization` reserves the visualization boundary for graph rendering
  concerns.
- `cli` owns command-line input and delegates work to application services.

## Dependency Direction

Dependencies point inward toward stable domain concepts. Interface definitions
belong near the code that consumes them, while concrete integrations are passed
in from outer layers. This keeps parsing, reporting, and CLI adapters
replaceable without reshaping the domain model.

## Dependency Injection

ChokePoint uses constructor or function-parameter injection for dependencies
that cross architectural boundaries. Examples include filesystem access,
configuration sources, clocks, serializers, graph backends, and output writers.
Pure domain operations should remain independent from infrastructure details.

## Testing Strategy

Tests should start at the narrowest useful boundary. Domain behavior belongs in
unit tests, while parser, report, and CLI workflows can use integration-style
tests when module boundaries need to be exercised together.
