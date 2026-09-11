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

  Not yet in scope: nothing to trim here — these primitives are already
  in their final shape and don't get rewritten by any later phase (only
  extended: Phase 11 adds sibling classes next to FakeModelClient, it
  doesn't touch it).

  Phase 1 — Single-turn skeleton

  Why: proves the request → prompt → model → parsed-answer path end to
  end before any tool complexity is added. Getting parse()/retry_notice
  right early matters because every later phase (tools, checkpoints,
  memory) still flows through this same "read one model turn" contract —
  bugs here would otherwise surface confusingly deep in later phases.

  runtime.py
    · locoagent.__init__(...) minimal — hold client/workspace/session
    · locoagent._ensure_session_shape() — normalize session dict on load. At this phase
      it's just `self.session.setdefault("history", [])`; the other four
      setdefault/type-check blocks (memory / checkpoints / runtime_identity /
      resume_state) belong to Phase 4 and Phase 7 respectively — see those
      phases' scope notes.
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

  Not yet in scope (comes later):
    · locoagent.parse(raw) — only needs the `<final>` and empty/plain-text branches
      returning ("final", ...) / ("retry", ...). Skip the `<tool>`/`<tool ...>`
      branches entirely — there's nothing to call one yet.
    · locoagent.parse_xml_tool / locoagent.parse_attrs / locoagent.extract_raw — don't write
      these yet. They only exist to parse the XML-attribute tool-call format
      used by write_file/patch_file, which don't exist until Phase 2 — write
      them alongside those tools instead.
    · locoagent.prompt(user_message) — the final version is `prompt, _ =
      self._build_prompt_and_metadata(user_message)`; at this phase there is no
      `_build_prompt_and_metadata` yet, so implement it as the literal naive
      concatenation (`self.prefix + "\n\n" + user_message`). The swap to the
      metadata-returning builder happens in Phase 5.
    · locoagent.ask(user_message) — the final version is a 2-line delegate to
      `AgentLoop(self).run(user_message)`. At this phase write it as a small
      self-contained loop with no `kind == "tool"` branch (Phase 2), no
      task_state/trace (Phase 3), no AgentLoop extraction (Phase 3), no
      checkpoint/resume branching (Phase 7), no redaction (Phase 8), and no
      durable-memory promotion (Phase 10).

  Phase 2 — Tools (the actual point)

  Why: a model that can only talk about the repo isn't an agent — it has
  to be able to change it. This phase turns the single-turn skeleton into
  a real loop (act → observe → continue) and introduces the guardrails
  (path confinement, arg validation, approval, repeated-call detection,
  max_steps/attempt caps) that keep an autonomous loop from doing
  something destructive or spinning forever. Everything from Phase 3
  onward exists to make this loop durable, efficient, and safe at scale —
  none of it matters without this phase working first.

  runtime.py
    · locoagent.history_text() — naive turn-by-turn transcript → text (tool calls + results,
      user/assistant turns). This is new at this phase, not Phase 1: a single-turn
      Phase-1 prompt has no prior history to show, but a multi-step tool loop does —
      without this, the model can't see the outcome of a tool it just called and the
      loop can't make progress. From this phase on, locoagent.prompt()'s naive formula
      becomes `prefix + history_text() + request`.
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

  Not yet in scope (comes later):
    · locoagent.parse(raw) now fills in the `<tool>`(JSON) and `<tool ...>`(XML)
      branches, using parse_xml_tool/parse_attrs/extract_raw — this is where
      those three helpers actually get written.
    · locoagent.ask(...) — this is still the Phase-1 loop living directly on locoagent,
      just extended with tool handling; it has NOT yet been moved into
      agent_loop.py (Phase 3), and still has no task_state/trace (Phase 3),
      no checkpoint/resume branching (Phase 7), no redaction (Phase 8), no
      durable-memory promotion (Phase 10).
    · ToolContext.shell_env_provider (wired from locoagent.shell_env) — security.py
      doesn't exist yet (Phase 8), so this phase's `shell_env()` should be a
      minimal stand-in (e.g. pass through `dict(os.environ)` or a small
      hardcoded allowlist inline), not the real `securitylib.shell_env(...)`.
    · The "delegate" tool — leave it out entirely. Don't add a "delegate"
      entry to BASE_TOOL_SPECS/legal_tool_names/TOOL_EXAMPLES, don't add the
      `depth < max_depth` registration branch in build_tool_registry, and
      don't wire ToolContext.spawn_delegate. All of that — plus
      tools.py::tool_delegate and locoagent.spawn_delegate — is Phase 9.

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

  Not yet in scope (comes later):
    · AgentLoop.run(...) — move the Phase-2 loop body in wholesale (build →
      complete → parse → tool/retry/final handling) plus TaskState/RunStore
      calls and the budget-exhaustion finalization prompt at the bottom.
      Leave out: the `resume_status`/`budget_reductions` checkpoint-trigger
      branches and every `agent.create_checkpoint(...)` call (Phase 7);
      `agent.promote_durable_memory(...)` calls (Phase 10).
    · AgentLoop._request_model / ._persist_model_failure / ._finish_success —
      same trim: no `create_checkpoint(...)` calls yet (Phase 7), and
      `_persist_model_failure`'s `agent.redact_text(str(exc))` should just be
      `str(exc)` for now (Phase 8 adds redaction).
    · locoagent.emit_trace — scope is just `self.run_store.append_trace(task_state,
      payload)` plus the event/timestamp fields; the
      `payload = self.redact_artifact(payload or {})` line is a Phase 8 addition.
    · locoagent.build_report — scope is run_id/task_id/status/stop_reason/
      final_answer/tool_steps/attempts/task_state/prompt_metadata only.
      checkpoint_id/resume_status fields are Phase 7, durable_promotions/
      rejections/superseded are Phase 10, redacted_env is Phase 8 — add them
      to the dict as those phases land, not now.

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

  Not yet in scope (comes later):
    · locoagent._ensure_session_shape() gains `self.session.setdefault("memory",
      memorylib.default_memory_state())`; __init__'s literal session dict
      gains the matching `"memory": memorylib.default_memory_state()` key.
    · locoagent.feature_flags / locoagent.feature_enabled(name) — this is where the
      flags dict and the gate mechanism first need to exist, since
      update_memory_after_tool checks `self.feature_enabled("memory")`. Only
      the "memory" key matters yet; Phase 5 adds "context_reduction" /
      "relevant_memory" to the same dict, Phase 6 adds "prompt_cache" — no new
      mechanism, just more keys over time.
    · features/memory.py::invalidate_stale_file_summaries / retrieval_candidates
      / retrieval_view — implement these now, but they stay uncalled: nothing
      invokes locoagent.invalidate_stale_memory() until Phase 7's resume path, and
      nothing renders relevant-memory retrieval until Phase 5's
      ContextManager._render_relevant_memory.

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
    · locoagent.history_text() — already exists since Phase 2; it gets demoted here, not introduced.
      ContextManager grows its own independent raw-history formatter
      (_raw_history_text / _render_history_section) that becomes the actual
      history-in-prompt source (budgeted, and compressible when context_reduction
      is on). locoagent.history_text() keeps existing afterward only for
      metadata["history_chars"] char-counting and (from Phase 9) seeding a
      delegate child's memory notes — it stops being what the model actually sees.

  Not yet in scope (comes later):
    · locoagent._build_prompt_and_metadata — at this phase it should call
      `self.build_prefix()` directly (no caching yet — that's Phase 6's
      `refresh_prefix()`), skip `self.evaluate_resume_state()` and every
      resume_status/stale_* metadata field (Phase 7), and skip
      `metadata.update(self.detected_secret_env_summary())` (Phase 8). Its
      metadata dict at this phase is just: prefix_chars, workspace_chars,
      memory_chars, history_chars, request_chars, tool_count, workspace_docs,
      recent_commits — plus whatever context_manager.build(...) itself returns.

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

  Not yet in scope (comes later):
    · locoagent._build_prompt_and_metadata — now calls `self.refresh_prefix()`
      instead of `self.build_prefix()`, and adds prefix_hash/prompt_cache_key/
      workspace_fingerprint/tool_signature/workspace_changed/prefix_changed to
      metadata. Still no resume_status fields (Phase 7) or
      detected_secret_env_summary() (Phase 8).
    · AgentLoop._request_model — now reads `prompt_metadata.get("prompt_cache_key")`
      and passes prompt_cache_key/prompt_cache_retention into
      `model_client.complete(...)`; Phase 3's version of this method called
      `complete(prompt, max_new_tokens)` with no cache kwargs.

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

  Not yet in scope (comes later):
    · locoagent._ensure_session_shape() gains the `checkpoints` (current_id/items),
      `runtime_identity`, and `resume_state` setdefault/type-check blocks —
      this is where checkpoint.py's session keys first get backfilled.
    · AgentLoop.run(...) / ._request_model / ._persist_model_failure /
      ._finish_success — this is where the `agent.create_checkpoint(...)`
      calls that Phase 3 explicitly deferred finally get added (model-failure
      path, tool-executed step, freshness/workspace-mismatch triggers,
      run-finished, and the step-limit/retry-limit stop path), plus the
      resume_status/budget_reductions branches at the top of the loop.
    · locoagent._build_prompt_and_metadata — now calls `self.evaluate_resume_state()`
      and adds resume_status/stale_summary_invalidations/stale_paths/
      runtime_identity_mismatch_fields to metadata.
    · locoagent.invalidate_stale_memory() — defined back in Phase 4 but only gets
      called for the first time now, from the resume-evaluation path.
    · Still not in scope: redact_text/redact_artifact calls (Phase 8),
      promote_durable_memory calls (Phase 10).

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

  Not yet in scope (comes later): none — this phase is where every deferred
  redaction hook from earlier phases finally gets filled in:
    · locoagent.emit_trace gains `payload = self.redact_artifact(payload or {})`
      (deferred since Phase 3).
    · locoagent.build_report gains `"redacted_env": self.detected_secret_env_summary()`
      (deferred since Phase 3).
    · locoagent._build_prompt_and_metadata gains
      `metadata.update(self.detected_secret_env_summary())` (deferred since Phase 5).
    · AgentLoop._persist_model_failure switches from `str(exc)` to
      `agent.redact_text(str(exc))` (deferred since Phase 3).
    · ToolContext.shell_env_provider switches from the Phase 2 stand-in to
      the real `securitylib.shell_env(allowlist=self.shell_env_allowlist, root=self.root)`.

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

  Not yet in scope (comes later): none — this phase is where the "delegate"
  tool that Phase 2 explicitly left out finally gets added: BASE_TOOL_SPECS /
  legal_tool_names / TOOL_EXAMPLES / validate_tool all gain their "delegate"
  entries, build_tool_registry adds the `depth < max_depth` registration
  branch, and ToolContext.spawn_delegate gets wired to the new
  locoagent.spawn_delegate.

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

  Not yet in scope (comes later): none new to build here, but this is where
  the `agent.promote_durable_memory(user_message, final)` calls that Phase 3
  left out finally get added — in AgentLoop._finish_success and in the
  step-limit/retry-limit stop path at the bottom of AgentLoop.run.

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

  Not yet in scope: nothing — unlike every prior phase, this one doesn't
  complete anything left half-built earlier. It's purely additive: new
  provider classes sitting next to FakeModelClient, and a new CLI entrypoint
  that constructs a locoagent exactly as Phases 0–10 already defined it, just
  with a real model_client instead of the fake one.

  Principle: each phase leaves you with a runnable agent and is testable
  in isolation; phases 4–10 are independent subsystems gated behind
  flags, so order among them is flexible — but memory (4) before
  context-budgeting (5) before caching (6) before resume (7) is the
  natural dependency chain.
