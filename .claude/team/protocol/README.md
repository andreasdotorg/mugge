# Team Protocol — mugge

This directory contains the orchestration protocol and supporting documents
for team-based development of this project. These are copies of the shared
team protocol from `~/mobile/gabriela-bogk/team-protocol/`, included here
so the project is self-contained and can be resumed from any session.

## Files

| File | Purpose |
|------|---------|
| `orchestration.md` | Main orchestration protocol — team model, work phases, rules |
| `global-lessons-learned.md` | Global process lessons learned (shared across all projects) |
| `state-format.md` | Canonical formats for stories, decisions, defects, status |
| `work-management-repo-local.md` | Repo-local work management backend specification |

## Reading Order (at session start)

1. `orchestration.md` (how the team works)
2. `../config.md` (this project's team shape)
3. `global-lessons-learned.md` (global process lessons)
4. `../lessons-learned.md` (project-specific lessons)
5. `../../docs/project/` state files (status, decisions, defects, stories)
6. `../../CLAUDE.md` (domain conventions)
7. `../consultation-matrix.md` (domain-specific consultation rules)
8. Role prompts in `../roles/` as needed

## Role Prompts

All role prompts are in `../roles/`. Custom project-specific roles:
- `audio-engineer.md` — Live Audio Engineer (domain specialist)
- `technical-writer.md` — Technical Writer (promoted to core, manages doc suite)
- `security-specialist.md` — Security Specialist (scoped to live performance availability)
- `ux-specialist.md` — UI/UX Specialist (interaction design across MIDI/headless/web)
- `product-owner.md` — Product Owner (story intake from owner inputs)
- `architect.md` — Architect (extends base with real-time performance scope)

Standard roles (from shared protocol):
- `architect-base.md`, `project-manager.md`, `change-manager.md`,
  `quality-engineer.md`, `advocatus-diaboli.md`, `researcher.md`, `worker.md`
