# YAML Parser

ChokePoint accepts YAML topology documents that describe nodes and dependency
relationships. Parsing produces a validated `Topology`.

## Basic Shape

```yaml
clouds:
  - aws

dns:
  - cloudflare

identity:
  - okta

services:
  frontend:
    depends_on:
      - cloudflare
      - okta
```

## Supported Sections

Top-level sections are fixed and unknown sections are rejected:

- `clouds`
- `dns`
- `identity`
- `services` and `service`
- `databases` and `database`
- `caches` and `cache`
- `queues` and `queue`
- `storage`
- `networks` and `network`
- `compute`
- `secrets` and `secret`
- `external`

Sections can be simple lists, object lists with `id`, mappings of resource id to
configuration, or a single resource configuration for singular sections such as
`database`.

## Resource Fields

Each resource may define:

- `id`
- `name`
- `provider`
- `metadata`
- Any relationship name from the ChokePoint model, such as `depends_on`,
  `reads_from`, `writes_to`, or `connects_to`

Relationship fields must be lists of node ids. All dependency targets must be
declared somewhere in the same document.

## Errors

The parser raises `TopologyParseError` with the source label and YAML path when
documents are malformed, use unsupported sections or fields, declare duplicate
nodes, reference missing dependencies, or contain non-JSON metadata.
