# Docs

Living design notes for `image-ai-edit`. Mirror of the project notes in the Obsidian vault at `~/ideaverse/OpenClaw/projects/image-ai-edit/`.

**Design**
| File | Purpose |
|---|---|
| [stack-decision.md](./stack-decision.md) | Chosen 2026 API stack and why |
| [api-catalog.md](./api-catalog.md) | Full vendor matrix (segmentation, edit, image-to-3D, AR) |
| [poc-plan.md](./poc-plan.md) | First POC: scope, milestones, success criteria |
| [open-questions.md](./open-questions.md) | Things to test or decide before scaling |

**Code**
| File | Purpose |
|---|---|
| [architecture.md](./architecture.md) | Layer map, file map, capability interfaces, data flow |
| [runbook.md](./runbook.md) | How to run the POC, troubleshoot it, read its output |
| [server.md](./server.md) | FastAPI app: setup, endpoints, examples |
| [https-tunnel-guide.md](./https-tunnel-guide.md) | Full walkthrough: phone-testing the AR pipeline over HTTPS |
| [contributing.md](./contributing.md) | Recipes: add a provider, add a capability, style conventions |

## TL;DR

**Use case.** User uploads a photo of their backyard + a photo of a specific fence → output a photorealistic image of that exact fence placed in the yard.

**Constraint.** All ML runs through hosted APIs. No self-hosted weights.

**Pipeline.**

```
backyard.jpg + fence_reference.jpg
    │
    ▼  Replicate · Grounded-SAM        (text → mask)
    │
    ▼  (optional) Replicate · SAM 2    (click-refine)
    │
    ▼  Google Gemini 2.5 Flash Image   (multi-image edit)
    │
    ▼  (optional) fal.ai · IC-Light    (relight to scene)
    │
final.png
```

