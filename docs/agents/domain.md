# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

**Layout for this repo: single-context.** One vocabulary for the whole repo — a single root `GLOSSARY.md` — and one decision log at `docs/adr/`. There is no `GLOSSARY-MAP.md` and no per-context `GLOSSARY.md`; this repo is not a monorepo and is not divided into contexts. If it ever grows genuine per-context vocabularies, switch to multi-context then, not before.

## Before exploring, read these

- **`GLOSSARY.md`** at the repo root, or
- **`GLOSSARY-MAP.md`** at the repo root if it exists: it points at one `GLOSSARY.md` per context. Read each one relevant to the topic. (Not this repo, today.)
- **`docs/adr/`**: read ADRs that touch the area you're about to work in. In multi-context repos, also check `src/<context>/docs/adr/` for context-scoped decisions.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved. At setup time this repo has neither `GLOSSARY.md` nor `docs/adr/`; that is expected, and they get created on first real use.

## File structure

Single-context repo (this repo):

```
/
├── GLOSSARY.md                        ← created on first real term
├── docs/
│   ├── adr/                           ← created on first real decision
│   │   ├── 0001-event-sourced-orders.md
│   │   └── 0002-postgres-for-write-model.md
│   └── agents/                        ← this skill's own config
│       ├── issue-tracker.md
│       ├── triage-labels.md
│       └── domain.md
├── work/                              ← 投递流程与档案真源（见 AGENTS.md）
└── resume-autofill/                   ← 简历助手扩展
```

Multi-context repo (presence of `GLOSSARY-MAP.md` at the root) — **not** this repo, shown for reference:

```
/
├── GLOSSARY-MAP.md
├── docs/adr/                          ← system-wide decisions
└── src/
    ├── ordering/
    │   ├── GLOSSARY.md
    │   └── docs/adr/                  ← context-specific decisions
    └── billing/
        ├── GLOSSARY.md
        └── docs/adr/
```

## Naming history

Newer versions of these skills renamed the domain files: `CONTEXT.md` → `GLOSSARY.md` and `CONTEXT-MAP.md` → `GLOSSARY-MAP.md`. Only the `GLOSSARY` names are read now. This repo currently has neither the old nor the new files; if a `CONTEXT.md` or `CONTEXT-MAP.md` ever shows up here, rename it with `git mv` and fix the references in this file rather than keeping both names alive.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `GLOSSARY.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders), but worth reopening because…_
