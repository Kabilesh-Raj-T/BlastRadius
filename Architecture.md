# Architecture

ChokePoint follows clean architecture principles. Domain concepts live at the
center of the package, while input parsing, graph analysis, reporting,
visualization, and command-line concerns remain isolated around that core.

## Package Layout

```text
src/chokepoint/
    cli/
    parser/
    graph/
    models/
    report/
    visualization/
    utils/
```

## Boundaries

- `models` contains domain types and value objects.
- `parser` converts external infrastructure descriptions into domain models.
- `graph` builds and analyzes dependency graphs from domain models.
- `report` turns analysis results into user-facing report data.
- `visualization` renders graph and report data for human inspection.
- `cli` owns command-line input and delegates work to application services.
- `utils` contains narrowly scoped support code that is independent of product
  behavior.

## Dependency Direction

Dependencies point inward toward stable domain concepts. Interface definitions
belong near the code that consumes them, while concrete integrations are passed
in from outer layers. This keeps parsing, reporting, visualization, and CLI
adapters replaceable without reshaping the domain model.

## Dependency Injection

ChokePoint uses constructor or function-parameter injection for dependencies
that cross architectural boundaries. Examples include filesystem access,
configuration sources, clocks, serializers, graph backends, and output writers.
Pure domain operations should remain independent from infrastructure details.

## Testing Strategy

Tests should start at the narrowest useful boundary. Domain behavior belongs in
unit tests, while parser, report, visualization, and CLI workflows can use
integration-style tests when module boundaries need to be exercised together.
