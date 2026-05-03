# image-ai-edit

Insert a user-supplied object (e.g. a fence) into a real photograph — photorealistically, via hosted APIs only. No self-hosted weights.

## Docs

**Design**
- [Stack decision](./docs/stack-decision.md) — chosen 2026 API stack and why
- [API catalog](./docs/api-catalog.md) — full vendor matrix
- [POC plan](./docs/poc-plan.md) — milestones and success criteria
- [Open questions](./docs/open-questions.md)

**Code**
- [Architecture](./docs/architecture.md) — layer map, capability interfaces, data flow
- [Runbook](./docs/runbook.md) — running the POC, troubleshooting, reading output
- [Contributing](./docs/contributing.md) — recipes for adding providers and capabilities

## Quick start

```bash
uv pip install -p .venv/bin/python -e .
cp .env.example .env  # then fill in GEMINI_API_KEY (and REPLICATE_API_TOKEN if using --segment)

.venv/bin/python scripts/poc.py SCENE.jpg REFERENCE.jpg \
  "place this fence along the back edge of the lawn"
```

Outputs land in `out/composites/`. See the [runbook](./docs/runbook.md) for everything else.
