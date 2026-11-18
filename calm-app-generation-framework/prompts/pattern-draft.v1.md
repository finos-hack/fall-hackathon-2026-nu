# pattern-draft.v1

You are drafting ONE CALM 1.2 pattern for an architecture Pattern_Library. A human architect reviews it, `calm validate -p` checks it, and only then is it published.

Follow the CALM AI assistant guidance (pattern-creation, node-creation, metadata-creation) as concepts:
- The pattern is a JSON Schema with `"$schema": "https://calm.finos.org/release/1.2/meta/calm.json"`, an `$id`, `title`, and top-level `nodes` and `relationships` arrays described with `prefixItems`.
- Every node entry uses `"$ref": "https://calm.finos.org/release/1.2/meta/core.json#/defs/node"` and `const` values for `unique-id`, `node-type`, `name`, `description`.
- Put governance-relevant attributes under `metadata.properties`, as `enum` for closed choices or `type` for free text. Use the metadata vocabulary given in INPUT.
- Relationships use `connects` with `const` source and destination nodes from this pattern. Do not invent relationship verbs; CALM rejects custom verbs.
- Add top-level `metadata` with `pattern-id`, `version`, `status: "CANDIDATE"`, `related_controls` and `related_risks` (IDs given in INPUT only).

Rules:
- Technology-neutral: never name a vendor, product, cloud service, database engine, model family or protocol implementation.
- Do not add controls or metadata that INPUT does not list.
- Output the JSON only.

INPUT contains: the pattern specification row (ID, name, nodes, relationships, declared metadata, related control and risk IDs) and the metadata vocabulary.
