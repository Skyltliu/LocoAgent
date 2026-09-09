Build it as a walking skeleton, then add each subsystem as an
  independent, feature-flagged slice — which is essentially how the repo
  is structured (the feature_flags for memory / relevant_memory /
  context_reduction / prompt_cache and the per-subsystem ablation
  benchmarks are the tell).

  Phase 0 — Primitives (no Locoagent yet)

  workspace.py (build / text / fingerprint, clip, now) · session_store.py
  (load/save JSON) · providers/clients.py::FakeModelClient (scripted,
  deterministic).

  Phase 1 — Single-turn skeleton

  Locoagent.__init__ minimal (hold client/workspace/session),
  _ensure_session_shape, record.
  parse / extract / retry_notice — raw text → (kind, payload).
  build_prefix (identity + rules + workspace.text()), a naive prompt =
  prefix + request.
  ask loop: build → complete → parse → return on final.
  ✅ Runnable: answers questions about the repo snapshot.

  Phase 2 — Tools (the actual point)

  tool_context.py, tools.py (6 specs + validate_tool + runners), path()
  confinement, tool_executor.py.
  Loop handles kind == "tool": execute → record → continue; max_steps +
  attempt cap; approve() + policy; repeated_tool_call guard.
  ✅ Runnable: real coding agent for short tasks.

  Phase 3 — Durability & observability

  task_state.py, run_store.py (start_run, append_trace, write_task_state,
  write_report), emit_trace, build_report.
  Extract the loop into agent_loop.py; add the finalization pass on
  budget exhaustion.

  Phase 4 — Working memory

  features/memory.py::LayeredMemory (task summary, recent files, file
  summaries w/ freshness hash, episodic notes), render_memory_text,
  retrieval_candidates.
  update_memory_after_tool / note_tool wiring; memory_text() into the
  prompt.

  Phase 5 — Context budgeting

  context_manager.py::build (section budgets, reduction order, history
  compression, _metadata).
  Swap the naive builder for _build_prompt_and_metadata; wire
  feature_enabled.

  Phase 6 — Prefix caching

  refresh_prefix with the fingerprint gate; tool_signature into the
  fingerprint; prompt_cache_key = prefix hash, passed to the client.

  Phase 7 — Checkpoint / resume

  checkpoint.py (create_checkpoint, evaluate_resume_state,
  current_runtime_identity, render_checkpoint_text, schema version, stale
  / workspace-mismatch statuses).
  Loop branches on resume_status / budget_reductions;
  invalidate_stale_memory.

  Phase 8 — Security / redaction

  security.py (secret-env detection, redact_text, redact_artifact,
  shell_env allowlist); apply to traces/reports and run_shell env.

  Phase 9 — Sub-agent delegation

  spawn_delegate (read-only, depth+1 child); delegate tool exposed only
  under max_depth.

  Phase 10 — Durable memory

  DurableMemoryStore, extract_durable_promotions, reject_durable_reason,
  promote_durable_memory, record_process_note_for_tool.

  Phase 11 — Real providers + CLI

  Ollama / OpenAI- / Anthropic-compatible clients + completion-metadata
  extraction; cli.py, .env loading, from_session, reset, REPL commands.

  Principle: each phase leaves you with a runnable agent and is testable
  in isolation; phases 4–10 are independent subsystems gated behind
  flags, so order among them is flexible — but memory (4) before
  context-budgeting (5) before caching (6) before resume (7) is the
  natural dependency chain.