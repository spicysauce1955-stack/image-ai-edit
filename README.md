# image-ai-edit

Insert a user-supplied object (e.g. a fence) into a real photograph — photorealistically, via hosted APIs only. No self-hosted weights.

See [`docs/`](./docs/) for the full design notes:

- [Stack decision](./docs/stack-decision.md)
- [API catalog](./docs/api-catalog.md)
- [POC plan](./docs/poc-plan.md)
- [Open questions](./docs/open-questions.md)

## Quick start

```bash
uv pip install -p .venv/bin/python -e .
cp .env.example .env  # then fill in REPLICATE_API_TOKEN and GEMINI_API_KEY

.venv/bin/python scripts/poc.py SCENE.jpg REFERENCE.jpg \
  "place this fence along the back edge of the lawn" \
  --segment "ground,trees,sky"
```

Outputs land in `out/composites/` and `out/masks/`.
