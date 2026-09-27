# Clarifications

Architecture and control-flow questions and answers, logged as they come up.
Newest entries at the bottom.

---

### 2026-09-11 — How does the graph work now, and how does the manager pick who speaks?

**Q:** Help me understand. How is it working now. How is the graph configured. How manager picks.

**A:**

Graph shape: `START → manager → {subset of persona nodes} → END`, checkpointed
to SQLite per `thread_id`.

- **State** is `MessagesState` (append-only `messages` list) plus one extra
  field, `next_speakers: list[str]`, written only by the manager and read only
  by the routing function.

- **Manager node** runs first every turn. It sends the full message history
  (including past manager notes and persona replies from that thread) to the
  LLM via `.with_structured_output(RoutingDecision)` — a Pydantic model with
  `speakers: list[str]` and `reasoning: str`, so the model can't return
  anything but a name list plus a short reason. The returned names are
  filtered against the real persona keys, with a fallback to the first
  persona if none are valid (safety net, not the normal path). The manager
  then appends a visible `AIMessage(name="manager", ...)` chat bubble
  explaining who's replying and why, and writes the filtered names to
  `next_speakers`.

- **Routing** uses `add_conditional_edges("manager", route_to_speakers,
  list(PERSONAS))`, where `route_to_speakers` just returns
  `state["next_speakers"]`. The graph is static (all 6 persona nodes always
  exist as possible destinations), but only the edges named in
  `next_speakers` actually fire on a given turn — that's the mechanism behind
  "not all six every time."

- **Persona nodes** are closures over their own system prompt (persona
  description + a shared `GROUP_CHAT_STYLE` block enforcing short, casual,
  friend-like replies). Selected personas run in parallel, each seeing the
  same history (user message + manager's note), and each appends one
  `AIMessage(name=<persona>)`.

- **API layer** (`/chat` in `server.py`) diffs message count before/after
  `graph.ainvoke(...)` and returns only the new messages as `{persona,
  content}` pairs. The frontend renders the `manager`-named message as a
  small italic system note and the rest as normal chat bubbles.

Why this shape: the manager doesn't generate its own commentary — it's a
pure filter over a fixed set of possible speakers. Structured output keeps
its only job (picking valid names) cheap and unambiguous, and the static
graph + conditional-edge pattern makes future milestones (manager-asks-user,
termination condition) additive rather than a rewrite.

---

### 2026-09-27 — Is the current thread on the "manager thinks out loud" strategy or "friends only"?

**Q:** Is it on manager thinks out loud or friends only?

**A:** As of M4 there are two selectable strategies (`app/graph.py`), fixed
per-thread at creation via `threads.strategy` in the SQLite thread index and
never changed mid-conversation:

- **`confidence`** — the manager is a visible participant: its routing
  decisions appear as their own chat bubble ("Routing to: Optimist — ..."),
  and the final verdict is an explicit `AIMessage(name="manager", ...)`
  attributed to the manager.
- **`background`** — the manager's routing is never shown; personas appear
  to talk to each other directly, and the verdict comes from a `group`
  voice instead of a named manager.

Checking `data/checkpoints.db`'s `threads` table directly (rather than
assuming from `DEFAULT_STRATEGY`) showed the two most recent threads were
both created with `strategy = 'confidence'` — so the current session is on
the manager-visible strategy, not friends-only.
