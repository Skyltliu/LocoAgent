Build it as a walking skeleton, then add each subsystem as an
  independent, feature-flagged slice — which is essentially how the repo
  is structured (the feature_flags for memory / relevant_memory /
  context_reduction / prompt_cache and the per-subsystem ablation
  benchmarks are the tell).

  Note: the main agent class is `locoagent` (locoagent/runtime.py). Earlier notes
  called it "Locoagent" — same thing, renamed below to match the code.

  Phase 0 — Primitives (no locoagent yet)

  Why: every later phase needs a way to describe "the repo right now,"
  persist state between runs, and call a model without paying real API
  cost/latency while developing. Building these first, with no agent
  logic attached, keeps them independently testable and gives Phase 1
  something to compose instead of inventing plumbing mid-loop.

  workspace.py
    · now() — current UTC timestamp helper
    · clip(text, limit) / middle(text, limit) — output truncation
    · WorkspaceContext.build(cwd, repo_root_override=None) — snapshot cwd/repo/branch/status/commits
    · WorkspaceContext.text() — render the snapshot into prompt text
    · WorkspaceContext.fingerprint() — hash of the snapshot for cache/staleness checks
  session_store.py
    · SessionStore.path(session_id) / .save(session) / .load(session_id) / .latest() — JSON persistence
  providers/clients.py
    · FakeModelClient.__init__(outputs) / .complete(prompt, max_new_tokens, **kwargs) — scripted, deterministic client

  Phase 1 — Single-turn skeleton

  Why: proves the request → prompt → model → parsed-answer path end to
  end before any tool complexity is added. Getting parse()/retry_notice
  right early matters because every later phase (tools, checkpoints,
  memory) still flows through this same "read one model turn" contract —
  bugs here would otherwise surface confusingly deep in later phases.

  runtime.py
    · locoagent.__init__(...) minimal — hold client/workspace/session
    · locoagent._ensure_session_shape() — normalize session dict on load
    · locoagent.record(item) — append an item to session history
    · locoagent.parse(raw) / locoagent.retry_notice(problem=None) — raw text → (kind, payload); malformed-output nudge
    · locoagent.extract(text, tag) / locoagent.extract_raw(text, tag) / locoagent.parse_attrs(text) / locoagent.parse_xml_tool(raw) — tag/attr extraction helpers backing parse()
  prompt_prefix.py
    · build_prompt_prefix(workspace, tools, built_at=None) — identity + rules + workspace.text()
  runtime.py
    · locoagent.build_prefix() — wraps build_prompt_prefix with current workspace/tools
    · locoagent.prompt(user_message) — naive prompt = prefix + request
    · locoagent.ask(user_message) — ask loop: build → complete → parse → return on final
  ✅ Runnable: answers questions about the repo snapshot.

  Phase 2 — Tools (the actual point)

  Why: a model that can only talk about the repo isn't an agent — it has
  to be able to change it. This phase turns the single-turn skeleton into
  a real loop (act → observe → continue) and introduces the guardrails
  (path confinement, arg validation, approval, repeated-call detection,
  max_steps/attempt caps) that keep an autonomous loop from doing
  something destructive or spinning forever. Everything from Phase 3
  onward exists to make this loop durable, efficient, and safe at scale —
  none of it matters without this phase working first.

  tool_context.py
    · ToolContext.path(raw_path) — confine a relative path to the workspace root
    · ToolContext.shell_env() — filtered env for shell tool calls
  tools.py
    · legal_tool_names() / build_tool_registry(context) / tool_example(name) — spec registry + one-shot examples
    · validate_tool(context, name, args) — arg/schema validation before execution
    · tool_list_files(context, args) · tool_read_file(context, args) · tool_search(context, args) ·
      tool_run_shell(context, args) · tool_write_file(context, args) · tool_patch_file(context, args) —
      the 6 base tool runners
    · tool_delegate(context, args) — 7th runner, gated behind max_depth (wired fully in Phase 9)
  tool_executor.py
    · ToolExecutionResult — return value shape (output, metadata, error)
    · ToolExecutor.execute(name, args) — validate → run → wrap result
  runtime.py
    · locoagent.build_tools() / locoagent._normalize_allowed_tools(allowed_tools) / locoagent._apply_tool_allowlist(tools) — tool wiring + allowlist
    · locoagent.execute_tool(name, args) / locoagent.run_tool(name, args) — dispatch into ToolExecutor
    · locoagent.tool_list_files/.tool_read_file/.tool_search/.tool_run_shell/.tool_write_file/.tool_patch_file/.tool_delegate — thin per-tool wrappers
    · locoagent.validate_tool(name, args) / locoagent.tool_example(name) / locoagent.tool_context() — validation + context plumbing
    · locoagent.approve(name, args) — approval policy hook before risky tools run
    · locoagent.repeated_tool_call(name, args) — loop guard for identical repeated calls
    · locoagent.ask(...) extended: loop handles kind == "tool" → execute → record → continue; enforces max_steps and an attempt cap (locoagent.record_attempt-style bookkeeping)
  ✅ Runnable: real coding agent for short tasks.

  Phase 3 — Durability & observability

  Why: once the loop can run for many steps (Phase 2), a crash, a step-
  limit stop, or a bad model call shouldn't erase progress or leave you
  unable to tell what happened. task_state.py/run_store.py make runs
  resumable and inspectable; extracting the loop into agent_loop.py at
  the same time keeps locoagent focused on capabilities (tools, memory,
  prompting) while AgentLoop owns orchestration — a split every
  subsequent phase (checkpointing especially) relies on.

  task_state.py
    · TaskState.create(task_id, user_request, run_id="") / .from_dict(data) / .to_dict() — state (de)serialization
    · TaskState.record_attempt() / .record_tool(name) — counters
    · TaskState.stop(stop_reason, status=STATUS_STOPPED, final_answer="") and the specializations
      .stop_step_limit(...) / .stop_retry_limit(...) / .stop_model_error(...) / .finish_success(final_answer)
  run_store.py
    · RunStore.start_run(task_state) — allocate a run dir
    · RunStore.write_task_state(task_state) / .load_task_state(task_id) — task_state.json round-trip
    · RunStore.append_trace(task_state, event) — trace.jsonl writer
    · RunStore.write_report(task_state, report) / .load_report(task_id) — report.json round-trip
    · RunStore._write_json_atomic(path, payload) — shared atomic-write helper
  runtime.py
    · locoagent.emit_trace(task_state, event, payload=None) — trace event helper used throughout the loop
    · locoagent.build_report(task_state) — assemble the run's final report
    · locoagent.new_task_id() / locoagent.new_run_id() — id generation
  agent_loop.py (loop extracted out of locoagent.ask)
    · AgentLoop.__init__(agent)
    · AgentLoop._request_model(task_state, user_message, prompt, prompt_metadata, run_started_at, purpose) — one model call + trace
    · AgentLoop._persist_model_failure(task_state, user_message, exc, run_started_at, prompt_metadata) — error path → task_state/report
    · AgentLoop._finish_success(task_state, user_message, final, run_started_at) — success path → task_state/report
    · AgentLoop.run(user_message) — the extracted loop, plus a finalization pass on budget exhaustion

  Phase 4 — Working memory

  Why: as tasks grow past what fits in raw history, the agent needs a
  compact, structured summary of what it has learned (which files
  matter, what's been done, freshness of what it read) rather than
  re-reading everything each turn. This is what Phase 5's budgeting
  reduces around and what Phase 7's resume rehydrates from — it has to
  exist before either can be meaningful.

  features/memory.py
    · default_memory_state() — initial memory dict shape
    · set_task_summary/remember_file/append_note/set_file_summary/invalidate_file_summary/
      invalidate_stale_file_summaries(state, ..., workspace_root=None) — mutate memory state
    · file_freshness/resolve_workspace_path/canonicalize_path(raw_path, workspace_root=None) — freshness-hash + path normalization
    · summarize_read_result(result, limit=180) — turn a tool result into a file summary
    · retrieval_candidates(state, query, limit=3, workspace_root=None) / retrieval_view(...) — episodic-note recall
    · render_memory_text(state, workspace_root=None) — task summary + recent files + file summaries + episodic notes → prompt text
    · is_effectively_empty(state, workspace_root=None) / normalize_memory_state(state, workspace_root=None)
    · LayeredMemory — thin OO wrapper over the above (to_dict, canonical_path, set_task_summary, remember_file,
      append_note, set_file_summary, invalidate_file_summary(s), retrieval_candidates/_view, render_memory_text, promote_durable)
  runtime.py
    · locoagent.remember(bucket, item, limit) — bounded list append used by note-taking
    · locoagent.memory_text() — LayeredMemory.render_memory_text() wired into the prompt
    · locoagent.update_memory_after_tool(name, args, result) / locoagent.note_tool(name, args, result) — post-tool memory updates

  Phase 5 — Context budgeting

  Why: naive prefix + full history (Phase 1) eventually blows the context
  window on long tasks. With working memory now available (Phase 4) as a
  compressible substitute for raw history, this phase decides how to
  spend a fixed token budget across prefix/memory/history sections and in
  what order to degrade when it doesn't fit — replacing the naive builder
  is only safe now that there's a principled fallback (summaries) instead
  of just truncating blindly.

  context_manager.py
    · ContextManager.__init__(...) — section budgets config
    · ContextManager.build(user_message) — top-level entry point
    · ContextManager._compute_section_floors() / ._render_sections(section_texts, budgets, selected_notes=None) /
      ._render_sections_without_reduction(...) — budget allocation + reduction order
    · ._render_relevant_memory(selected_notes, budget) / ._per_note_budget(budget, note_count, header) — memory section budgeting
    · ._render_history_section(budget) / ._compressed_history_entries(history, recent_start) /
      ._summarize_old_tool_item(item) / ._raw_history_text(history) / ._render_history_item(item, line_limit) — history compression
    · ._reusable_file_summary(path) — reuse a memory file summary instead of re-quoting raw content
    · ._assemble_prompt(rendered) / ._metadata(prompt, rendered, budgets, reduction_log, selected_notes, user_message, section_texts)
    · _tail_clip(text, limit) / SectionRender.raw_chars() / .rendered_chars() — support helpers
  runtime.py
    · locoagent._build_prompt_and_metadata(user_message) — swaps the naive builder for ContextManager.build
    · locoagent.prompt_metadata(user_message, prompt) — exposes the metadata alongside the prompt
    · locoagent.feature_enabled(name) — reads context_reduction / relevant_memory / etc. feature flags
    · locoagent.history_text() — raw fallback used when context_reduction is off

  Phase 6 — Prefix caching

  Why: the prefix (identity + rules + tool specs + workspace snapshot) is
  identical across most turns of a task, so recomputing/resending it
  every call wastes tokens and money. This only becomes worth building
  once the prefix is well-defined and stable (Phase 1) and there's a
  fingerprint to detect when it actually changes (workspace.fingerprint()
  from Phase 0) — caching an unstable prefix would just thrash.

  runtime.py
    · locoagent.tool_signature() — locoagent/prompt_prefix.py::tool_signature(tools), folded into the fingerprint
    · locoagent._apply_prefix_state(prefix_state) — install a (re)built prefix + its fingerprint
    · locoagent.refresh_prefix(force=False) — fingerprint gate: rebuild build_prompt_prefix() only when workspace/tool
      fingerprint changed (or force=True)
  prompt_prefix.py
    · tool_signature(tools) — stable hash of the active tool set, mixed into the workspace fingerprint
  providers/clients.py
    · OpenAICompatibleModelClient.complete(..., prompt_cache_key=None, prompt_cache_retention=None) and
      AnthropicCompatibleModelClient.complete(..., prompt_cache_key=None, prompt_cache_retention=None) —
      accept prompt_cache_key = hash of the (now-stable) prefix, passed through to the provider

  Phase 7 — Checkpoint / resume

  Why: long tasks get interrupted (process restart, budget exhaustion,
  user stopping mid-run) and re-running from scratch wastes the work
  already done. Resuming safely requires everything built so far: memory
  to rehydrate (Phase 4), a way to detect a stale/mismatched workspace
  (Phase 0's fingerprint, Phase 6's identity), and durability to know
  where the task left off (Phase 3). This is why resume is deliberately
  the last of the natural-dependency-chain phases.

  checkpoint.py
    · current_runtime_identity(agent) — provider/model/workspace fingerprint tuple, schema-versioned
    · checkpoint_state(agent) / current_checkpoint(agent) — read/derive the stored checkpoint
    · create_checkpoint(agent, task_state, user_message, trigger) — write a new checkpoint
    · evaluate_resume_state(agent) — decide resume_status: fresh / stale / workspace-mismatch / resumable
    · render_checkpoint_text(agent) — checkpoint → prompt text
    · infer_next_step(task_state) — best-guess continuation summary
  runtime.py
    · locoagent.current_runtime_identity()/.checkpoint_state()/.current_checkpoint()/.evaluate_resume_state()/
      .render_checkpoint_text()/.create_checkpoint(...)/.infer_next_step(...) — thin wrappers over checkpoint.py
    · locoagent.invalidate_stale_memory() — features/memory.py invalidate_stale_file_summaries on resume
  agent_loop.py / runtime.py
    · AgentLoop.run(...) branches on resume_status and on budget_reductions from context_manager metadata

  Phase 8 — Security / redaction

  Why: once run_shell (Phase 2) and traces/reports (Phase 3) exist, real
  environment variables and command output can leak secrets into
  persisted, potentially-shared artifacts. This phase is independent of
  the other subsystems by design (a flag-gated slice) but has to come
  after there's actually something — shell env, traces, reports — worth
  redacting.

  security.py
    · looks_sensitive_env_name(name) / is_secret_env_name(name, secret_env_names=None) — secret-env detection
    · configured_secret_env_items(env=None, secret_env_names=None) / detected_secret_env_items(...) /
      secret_env_summary(...) / detected_secret_env_summary(...) — reporting helpers
    · redact_text(text, env=None, secret_env_names=None) / redact_artifact(value, key=None, env=None, secret_env_names=None) —
      apply to traces/reports
    · shell_env(env=None, allowlist=(), root=".") — allowlisted env for run_shell tool
  runtime.py
    · locoagent.looks_sensitive_env_name/.is_secret_env_name/.configured_secret_env_items/.detected_secret_env_items/
      .secret_env_summary/.detected_secret_env_summary/.redact_text/.redact_artifact/.shell_env — wrappers wired
      into emit_trace, build_report, and tool_run_shell

  Phase 9 — Sub-agent delegation

  Why: some sub-tasks (e.g. read-only investigation) are cheaper and
  safer to hand to a scoped child agent than to do inline — but spawning
  a child means reusing the entire agent (locoagent itself, tools, prompting)
  recursively, so it can only be built once locoagent is a complete, working
  agent in its own right. Depth-limiting exists to bound the recursion
  this phase introduces.

  runtime.py
    · locoagent.spawn_delegate(args) — read-only, depth+1 child locoagent instance
    · locoagent.tool_delegate(args) — the delegate tool wrapper, exposed only while depth < max_depth
  tools.py
    · tool_delegate(context, args) — runner invoked by spawn_delegate; legal_tool_names() includes "delegate"
      only when allowed

  Phase 10 — Durable memory

  Why: working memory (Phase 4) dies with the task/session — but some
  learnings (a project convention, a recurring gotcha) are worth keeping
  across tasks entirely. This phase promotes select working-memory notes
  into a separate, persistent store, gated by a rejection filter so
  ephemeral or task-specific notes don't pollute it; it depends on
  working memory existing first as the source of candidates.

  features/memory.py
    · DurableMemoryStore.__init__(root) — durable-notes root
    · DurableMemoryStore.topic_slugs() / .load_index() / .load_topic_notes(topic) — read side
    · DurableMemoryStore._subject_key(text) / ._write_index(topics) / ._write_topic(topic, notes) — write side
    · DurableMemoryStore.retrieval_candidates(query, limit=3) — durable-store recall
    · DurableMemoryStore.promote(promotions) — write accepted promotions to disk
  runtime.py
    · locoagent.reject_durable_reason(note_text) — filter for what shouldn't be promoted
    · locoagent.extract_durable_promotions(user_message, final_answer) — candidate extraction at task end
    · locoagent.promote_durable_memory(user_message, final_answer) — extract → filter → DurableMemoryStore.promote
    · locoagent.record_process_note_for_tool(name, metadata) — episodic note for a tool call, feeding future promotion

  Phase 11 — Real providers + CLI

  Why: everything through Phase 10 was validated against FakeModelClient
  (Phase 0) so behavior stays deterministic and testable while the agent
  itself is being built. This phase is deliberately last: swap in real
  model providers and a human-facing CLI only once the agent's behavior
  is trusted, so any surprises at this point are attributable to the
  provider/CLI integration rather than the agent logic underneath it.

  providers/clients.py
    · OllamaModelClient.__init__(model, host, temperature, top_p, timeout) / .complete(prompt, max_new_tokens, **kwargs)
    · OpenAICompatibleModelClient.__init__(model, base_url, api_key, temperature, timeout) / .complete(...)
    · AnthropicCompatibleModelClient.__init__(model, base_url, api_key, temperature, timeout, thinking=None) / .complete(...)
    · _normalize_versioned_base_url(base_url) — shared URL handling
    · _extract_openai_text(data) / _extract_openai_text_from_sse(body_text) / _extract_openai_response_from_sse(body_text) /
      _extract_usage_cache_details(data) — OpenAI-compatible response + streaming + cache-metadata parsing
    · _extract_anthropic_text(data) / _extract_anthropic_metadata(data) — Anthropic-compatible response parsing
  config.py
    · find_project_env(start) / load_project_env(start, override=True) / _parse_env_line(line) / _strip_quotes(value) — .env loading
    · provider_env(name, legacy_names=(), default="") — provider API key/host lookup
  cli.py
    · _effective_provider(args) / _effective_model(args, provider) / _configured_secret_names(args) — arg/env resolution
    · _build_model_client(args) — instantiate the right client from Phase 11's provider classes
    · build_agent(args) — construct a locoagent via locoagent.from_session (runtime.py) or fresh
    · build_welcome(agent, model, host) — REPL banner
    · build_arg_parser() — CLI flags, including reset
    · main(argv=None) — entry point: parse args → build agent → REPL commands loop
  runtime.py
    · locoagent.from_session(cls, model_client, workspace, session_store, session_id, **kwargs) — resume-from-session constructor
    · locoagent.reset() — REPL "reset" command support

  Principle: each phase leaves you with a runnable agent and is testable
  in isolation; phases 4–10 are independent subsystems gated behind
  flags, so order among them is flexible — but memory (4) before
  context-budgeting (5) before caching (6) before resume (7) is the
  natural dependency chain.
