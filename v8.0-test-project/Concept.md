# Concept: Model Evaluation Pipeline

> Draft — written outside the pipeline for review. Move this file into
> the new project repo, then refine it via `[/discuss]` before the
> first `[/loop]`. This project doubles as the CDD v8.0 field test.

## Why This Exists

Evaluating a model today means stitching together half a dozen
harnesses by hand: different CLIs, different dataset formats,
different result schemas. We want one repo where pointing a URL +
API key at the pipeline yields comparable scores across every
dimension we care about — Traditional Chinese understanding, agentic
ability, image understanding, math, coding/terminal use, and security.

## Who It Serves

Mark — AI engineer evaluating candidate models (hosted or self-served
behind an OpenAI-compatible endpoint) quickly and repeatably. One
person operates it; no serving infrastructure, no cluster.

## What It Is

An **orchestrator over existing harnesses, not a re-implementation of
benchmarks.** The repo's own code is limited to:

1. **Unified model config** — a `ModelEndpoint` (base_url, api_key,
   model name, request params). Every benchmark consumes this and
   nothing else. No local serving, ever.
2. **Benchmark adapters + registry** — one adapter per benchmark,
   wrapping the official harness (subprocess or library call). Adding
   a future benchmark = one new adapter + one registry entry. This IS
   the scalability requirement.
3. **Dataset download scripts** — `scripts/download/<bench>.py|sh`,
   idempotent, separate from run time.
4. **Result normalization** — every run emits one record in a single
   schema: `{benchmark, model, endpoint, timestamp, metrics{}, config,
   harness_version}` → `results/<bench>/<run-id>.json` + an aggregate
   table.
5. **Docker wrappers** for benchmarks that need an execution
   environment (agentic, terminal). Non-agentic text/image benchmarks
   run natively.

## Benchmark Matrix (v1 targets)

| Dimension | Benchmark | Harness route | Status |
|---|---|---|---|
| 繁中理解 | TMMLU+ (`ikala/tmmluplus`, HF) | lm-evaluation-harness / lighteval via OpenAI-compatible API | committed |
| 繁中理解 (optional) | AIEC | — | open: AIEC (aiec.org.tw) is an evaluation/certification center; public dataset availability unverified |
| Agentic | τ²-bench (`sierra-research/tau2-bench`; consider `amazon-agi/tau2-bench-verified`) | official repo, in Docker | committed |
| Agentic | PinchBench (kilo.ai) | evaluates models as OpenClaw agent brains — requires OpenClaw runtime, in Docker | open: integration cost + task-set fit |
| Image | MMMU | VLMEvalKit or lmms-eval | committed; MMMU-Pro et al. later via same adapter |
| Math | candidates: AIME 2025/2026, MATH-500 | lighteval / simple-evals style | decide in [/discuss] |
| Coding / Terminal | candidates: LiveCodeBench, Terminal-Bench | official harnesses; Terminal-Bench needs Docker | decide in [/discuss] |
| 資安 | Promptfoo red-team | shell out to `promptfoo` CLI (Node) | committed |

## Design Principles

1. **Wrap, don't rebuild.** If an official harness exists, the adapter
   calls it. Custom scoring logic is a last resort and a red flag.
2. **API-only model access.** Every adapter talks to the endpoint via
   URL + key. A benchmark that can't is out of scope until it can.
3. **One result schema.** No score exists unless it lands in the
   normalized results format.
4. **Isolation where code runs.** Anything that executes model-driven
   actions (agentic, terminal) runs in Docker. Pure inference doesn't
   need it.
5. **Cheap smoke path.** Every benchmark supports `--limit N` so a
   10-sample run verifies wiring before burning tokens.
6. **Secrets in `.env`** (per CDD governance) — keys never in configs,
   logs, or results files.

## Scope

- In (v1): the matrix above, download scripts, unified config,
  normalized results, per-benchmark Docker where needed, `--limit`
  smoke mode.
- Deferred: batch-inference mode (design the client interface so a
  `batch` strategy can slot in; don't build it in v1), results
  dashboard/UI, CI scheduling, multi-endpoint comparison runs,
  statistical significance tooling.
- Out: model serving, fine-tuning, leaderboard hosting.

## Loop Roadmap (maps to successive [/loop] goals, not tickets)

1. **build** — skeleton + env setup + `ModelEndpoint` config + adapter
   interface/registry + TMMLU+ end-to-end (download → run `--limit 10`
   → normalized result). Cheapest full-pipe proof: pure API, no Docker.
2. **modify** — MMMU adapter (multimodal payload path).
3. **modify** — τ²-bench in Docker (exercises trial launch/monitoring).
4. **modify** — Promptfoo + the chosen math and coding benchmarks
   (candidate for a Parallel Group: disjoint adapter boundaries).
5. Later — PinchBench/OpenClaw, AIEC (if obtainable), batch inference.

## Success Criteria

- One command per benchmark: `run --bench <name> --endpoint <url>`
  produces a normalized result file; `--limit 10` finishes in minutes.
- Adding a benchmark touches only `adapters/<new>/` + registry — no
  core changes (proven by the v1 history itself).
- Fresh clone → README setup → first TMMLU+ smoke run without
  undocumented steps.

## Open Questions for [/discuss]

1. Math + coding final picks (AIME vs MATH-500; LiveCodeBench vs
   Terminal-Bench vs both — terminal use suggests Terminal-Bench).
2. Harness choice for text benchmarks: lm-evaluation-harness vs
   lighteval (pick ONE as the default text route).
3. AIEC: is the dataset actually distributable, or drop it?
4. PinchBench: is OpenClaw-agent evaluation what we mean by "agentic",
   or is τ²-bench sufficient for v1?
5. Results aggregation: flat JSON + one summary table enough, or do we
   want SQLite from day one? (Simplicity First says JSON.)
