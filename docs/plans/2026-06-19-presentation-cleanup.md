# Presentation Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish the app for a live demo by renaming it to "SlotIn", hiding/disabling features that aren't presentation-ready, and adding a chat-history reset.

**Architecture:** Pure UI/copy edits in the Next.js frontend plus one new backend endpoint (`DELETE /chat/history`) so the new "Delete chat" button actually wipes persisted history and the LangGraph checkpoint. No data-model or auth changes. After the demo, the disabled pieces (Settings link, RecommendTab, send button, model/cost footer) will be re-enabled by reverting these changes.

**Tech Stack:** Next.js 14 (App Router), React, Tailwind, Vitest + React Testing Library, FastAPI, LangGraph (SqliteSaver checkpointer), SQLAlchemy, pytest.

---

## File Structure

**Frontend — modify:**
- `frontend/components/TopNav.tsx` — brand rename, drop Settings link, narrow `ActivePage` type
- `frontend/components/AppShell.tsx` — drop the `settings` branch in `active` derivation, drop `model` / `dailyCost` props passed to `ChatPanel`, wire chat clear callback
- `frontend/components/ChatPanel.tsx` — remove model + cost footer in header, remove per-message token-usage line, swap send button for a red trash "delete chat" button, disable text input + Enter-to-send
- `frontend/components/calendar/appointmentModal/AppointmentModal.tsx` — drop the tab bar, render `MakeAppointmentTab` directly
- `frontend/app/calendar/page.tsx` — `onEmptyClick` must not pre-fill `end_at`
- `frontend/components/EventCard.tsx` — rename 3 × `Save` / `Saved ✓` button labels
- `frontend/components/EventChip.tsx` — rename `Save` / `Saved ✓` button label
- `frontend/components/EventDetailOverlay.tsx` — rename `Save to Calendar` / `Saved ✓` button label
- `frontend/lib/api.ts` — add `deleteChatHistory(sessionId)`
- `frontend/lib/ChatContext.tsx` — add `clearSession(sessionId)` that calls the API and resets local state

**Frontend — modify tests:**
- `frontend/components/__tests__/TopNav.test.tsx`
- `frontend/components/__tests__/ChatPanel.test.tsx`
- `frontend/components/__tests__/AppointmentModal.test.tsx`
- `frontend/components/__tests__/EventCard.test.tsx`
- `frontend/components/__tests__/EventChip.test.tsx`

**Backend — modify:**
- `backend/app/api/routes_chat.py` — add `DELETE /chat/history` endpoint that nukes `ChatMessage` rows + clears the LangGraph checkpoint for that thread
- `backend/tests/api/test_routes_chat.py` — cover the new endpoint

---

## Task 1: Rename brand to "SlotIn"

**Files:**
- Modify: `frontend/components/TopNav.tsx:14-16`
- Modify: `frontend/components/__tests__/TopNav.test.tsx:13-15,17-21,23-26,28-31`

- [ ] **Step 1: Update the test to expect the new brand name**

Edit `frontend/components/__tests__/TopNav.test.tsx`: replace every literal `'Event Tracker'` with `'SlotIn'`. Only line 14 contains it today:

```ts
    expect(screen.getByText('SlotIn')).toBeInTheDocument()
```

- [ ] **Step 2: Run test, confirm it fails**

```powershell
cd frontend
npx vitest run components/__tests__/TopNav.test.tsx
```

Expected: the `renders brand name` test fails with `Unable to find an element with the text: SlotIn`.

- [ ] **Step 3: Rename the brand in `TopNav.tsx`**

In `frontend/components/TopNav.tsx`, change line 15 from `Event Tracker` to `SlotIn`:

```tsx
      <span className="font-serif font-bold text-base text-text-primary mr-5">
        SlotIn
      </span>
```

- [ ] **Step 4: Run TopNav tests, confirm they pass**

```powershell
npx vitest run components/__tests__/TopNav.test.tsx
```

Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```powershell
git add frontend/components/TopNav.tsx frontend/components/__tests__/TopNav.test.tsx
git commit -m "feat(frontend): rename brand to SlotIn"
```

---

## Task 2: Remove Settings link from top nav

**Files:**
- Modify: `frontend/components/TopNav.tsx:3-9`
- Modify: `frontend/components/AppShell.tsx:60-63`
- Modify: `frontend/components/__tests__/TopNav.test.tsx`

- [ ] **Step 1: Add a failing test asserting Settings is gone**

In `frontend/components/__tests__/TopNav.test.tsx`, append a new test inside the `describe('TopNav', …)` block:

```ts
  it('does not render a Settings link', () => {
    render(<TopNav active="dashboard" date="Hamburg · June 8" />)
    expect(screen.queryByText('Settings')).not.toBeInTheDocument()
  })
```

- [ ] **Step 2: Run test, confirm it fails**

```powershell
npx vitest run components/__tests__/TopNav.test.tsx
```

Expected: the new `does not render a Settings link` test fails because the link is still present.

- [ ] **Step 3: Remove Settings from `LINKS` and narrow `ActivePage` in `TopNav.tsx`**

Replace lines 3-9 with:

```tsx
type ActivePage = 'dashboard' | 'calendar'

const LINKS: { href: string; label: string; page: ActivePage }[] = [
  { href: '/',          label: 'Dashboard', page: 'dashboard' },
  { href: '/calendar',  label: 'Calendar',  page: 'calendar'  },
]
```

- [ ] **Step 4: Update `AppShell.tsx` active derivation**

In `frontend/components/AppShell.tsx`, replace lines 60-63 with:

```tsx
  const active: 'dashboard' | 'calendar' =
    pathname?.startsWith('/calendar') ? 'calendar' : 'dashboard'
```

- [ ] **Step 5: Run frontend tests, confirm they pass**

```powershell
npx vitest run components/__tests__/TopNav.test.tsx
npx tsc --noEmit -p .
```

Expected: TopNav tests all pass; tsc reports no errors.

- [ ] **Step 6: Commit**

```powershell
git add frontend/components/TopNav.tsx frontend/components/AppShell.tsx frontend/components/__tests__/TopNav.test.tsx
git commit -m "chore(frontend): hide Settings link from top nav for demo"
```

---

## Task 3: Remove model name and token costs from ChatPanel header & messages

**Files:**
- Modify: `frontend/components/ChatPanel.tsx:8-17, 38-41, 76-80`
- Modify: `frontend/components/AppShell.tsx:135-142`
- Modify: `frontend/components/__tests__/ChatPanel.test.tsx`

- [ ] **Step 1: Update ChatPanel tests to use the new props shape**

In `frontend/components/__tests__/ChatPanel.test.tsx`, replace every `<ChatPanel sessionId="dashboard" model="gpt-4o-mini" dailyCost={0.0048} …/>` with `<ChatPanel sessionId="dashboard" …/>` (drop `model` and `dailyCost`). Add this new test inside `describe('ChatPanel', …)`:

```ts
  it('does not show the model name or token usage in the header', () => {
    render(<ChatPanel sessionId="dashboard" onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />)
    expect(screen.queryByText(/gpt-4o-mini/)).not.toBeInTheDocument()
    expect(screen.queryByText(/today/)).not.toBeInTheDocument()
  })
```

- [ ] **Step 2: Run tests, confirm they fail**

```powershell
npx vitest run components/__tests__/ChatPanel.test.tsx
```

Expected: the new test fails (the header still renders `gpt-4o-mini · $0.00 today`) and TypeScript complains about the unused props.

- [ ] **Step 3: Drop `model` and `dailyCost` props and their usage in `ChatPanel.tsx`**

Replace lines 8-17 with:

```tsx
interface Props {
  sessionId: string
  onCardClick: (id: string) => void
  onFeedback: (id: string, sentiment: Sentiment | null) => void
  onSave: (id: string, save: boolean) => void
}

export default function ChatPanel({ sessionId, onCardClick, onFeedback, onSave }: Props) {
```

Replace lines 38-41 (the header block) with:

```tsx
      <div className="px-3.5 py-2.5 border-b border-border bg-accent-gold-light flex-shrink-0">
        <p className="font-serif font-bold text-xs text-text-primary">Chat Assistant</p>
      </div>
```

Delete the per-message token-usage block (lines 76-80):

```tsx
                {msg.tokenUsage && (
                  <p className="text-[8px] text-text-muted mt-1 text-right">
                    {msg.tokenUsage.input_tokens} in · {msg.tokenUsage.output_tokens} out · ${msg.tokenUsage.estimated_cost_usd.toFixed(4)}
                  </p>
                )}
```

- [ ] **Step 4: Update the `<ChatPanel … />` call site in `AppShell.tsx`**

In `frontend/components/AppShell.tsx`, replace lines 135-142 with:

```tsx
          <ChatPanel
            sessionId="dashboard"
            onCardClick={openOverlay}
            onFeedback={handleFeedback}
            onSave={handleSave}
          />
```

- [ ] **Step 5: Run tests, confirm they pass**

```powershell
npx vitest run components/__tests__/ChatPanel.test.tsx
npx tsc --noEmit -p .
```

Expected: all ChatPanel tests pass and tsc is clean.

- [ ] **Step 6: Commit**

```powershell
git add frontend/components/ChatPanel.tsx frontend/components/AppShell.tsx frontend/components/__tests__/ChatPanel.test.tsx
git commit -m "chore(chat): hide model name and token costs for demo"
```

---

## Task 4: Backend `DELETE /chat/history` endpoint

The DB rows and the LangGraph checkpoint are independent persistence layers. The endpoint deletes both so the next `POST /chat` truly starts a blank turn for that `session_id`.

**Files:**
- Modify: `backend/app/api/routes_chat.py:117-152` (append the new route)
- Modify: `backend/tests/api/test_routes_chat.py` (append new tests)

- [ ] **Step 1: Write failing tests**

In `backend/tests/api/test_routes_chat.py`, append:

```python
from datetime import datetime, timezone


def test_delete_chat_history_deletes_rows(client, user, db_session, monkeypatch):
    """DELETE /chat/history?session_id=X removes all ChatMessage rows for that
    user + session_id, leaves other sessions alone, and returns 204."""
    from app.api import routes_chat

    async def _noop_clear(thread_id):  # noqa: ARG001
        return None

    monkeypatch.setattr(routes_chat, "clear_session_checkpoint", _noop_clear)

    db_session.add_all([
        ChatMessage(id="m1", session_id="s1", user_id="local", role="user",
                    content="hi", created_at=datetime.now(timezone.utc)),
        ChatMessage(id="m2", session_id="s1", user_id="local", role="assistant",
                    content="hello", created_at=datetime.now(timezone.utc)),
        ChatMessage(id="m3", session_id="s2", user_id="local", role="user",
                    content="other session", created_at=datetime.now(timezone.utc)),
    ])
    db_session.commit()

    res = client.delete("/chat/history?session_id=s1")
    assert res.status_code == 204

    remaining = db_session.query(ChatMessage).order_by(ChatMessage.id).all()
    assert [r.id for r in remaining] == ["m3"]


def test_delete_chat_history_clears_checkpoint(client, user, db_session, monkeypatch):
    """The endpoint must also clear the LangGraph checkpoint for that thread,
    or the next turn would still see the deleted conversation in agent state."""
    from app.api import routes_chat

    called_with: list[str] = []

    async def _spy_clear(thread_id: str) -> None:
        called_with.append(thread_id)

    monkeypatch.setattr(routes_chat, "clear_session_checkpoint", _spy_clear)

    res = client.delete("/chat/history?session_id=demo-1")
    assert res.status_code == 204
    assert called_with == ["demo-1"]
```

- [ ] **Step 2: Run tests, confirm they fail**

```powershell
cd backend
poetry run pytest tests/api/test_routes_chat.py -k delete -v
```

Expected: both tests error with "404 Not Found" / "AttributeError: module … has no attribute 'clear_session_checkpoint'".

- [ ] **Step 3: Add `clear_session_checkpoint` helper in `runtime.py`**

In `backend/app/agent/runtime.py`, append (after the existing `heal_orphan_tool_calls` helper):

```python
async def clear_session_checkpoint(thread_id: str) -> None:
    """Wipe every persisted checkpoint for a LangGraph thread so the next turn
    starts with an empty message history.

    Falls back to a `RemoveMessage`-based reset if the checkpointer doesn't
    expose `adelete_thread` (older langgraph versions)."""
    from langchain_core.messages import RemoveMessage

    checkpointer = await _get_async_checkpointer()
    config = {"configurable": {"thread_id": thread_id}}

    delete_thread = getattr(checkpointer, "adelete_thread", None)
    if callable(delete_thread):
        await delete_thread(thread_id)
        return

    agent = await build_async_agent()
    snapshot = await agent.aget_state(config)
    messages = snapshot.values.get("messages", []) if snapshot else []
    if not messages:
        return
    await agent.aupdate_state(
        config,
        {"messages": [RemoveMessage(id=m.id) for m in messages if getattr(m, "id", None)]},
    )
```

- [ ] **Step 4: Add the `DELETE /chat/history` route in `routes_chat.py`**

In `backend/app/api/routes_chat.py`, add the import at the top of the file (under the existing `from app.agent.runtime import heal_orphan_tool_calls`):

```python
from app.agent.runtime import clear_session_checkpoint, heal_orphan_tool_calls
```

(Replace the original single-name import.) Then append at the bottom of the file:

```python
@router.delete("/chat/history", status_code=204)
async def delete_chat_history(session_id: str, db: DbSession) -> None:
    """Wipe persisted chat for one session: ChatMessage rows + LangGraph checkpoint."""
    user_id = get_current_user_id()
    db.query(ChatMessage).filter(
        ChatMessage.user_id == user_id,
        ChatMessage.session_id == session_id,
    ).delete(synchronize_session=False)
    db.commit()
    await clear_session_checkpoint(session_id)
```

- [ ] **Step 5: Run tests, confirm they pass**

```powershell
poetry run pytest tests/api/test_routes_chat.py -v
```

Expected: all chat-route tests pass, including the two new ones.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/api/routes_chat.py backend/app/agent/runtime.py backend/tests/api/test_routes_chat.py
git commit -m "feat(chat): add DELETE /chat/history endpoint"
```

---

## Task 5: Frontend `deleteChatHistory` API client

**Files:**
- Modify: `frontend/lib/api.ts:248-300`

- [ ] **Step 1: Add `deleteChatHistory` next to `getChatHistory`**

In `frontend/lib/api.ts`, immediately after the existing `getChatHistory` function (before `postChat`), add:

```ts
export async function deleteChatHistory(sessionId: string): Promise<void> {
  if (MOCK) {
    console.info("[mock] DELETE /chat/history", sessionId);
    return;
  }
  const res = await fetch(
    `${API_URL}/chat/history?session_id=${encodeURIComponent(sessionId)}`,
    { method: "DELETE", headers: headers() },
  );
  if (!res.ok) throw new Error(`API ${res.status} /chat/history`);
}
```

- [ ] **Step 2: Type-check**

```powershell
cd frontend
npx tsc --noEmit -p .
```

Expected: no errors.

- [ ] **Step 3: Commit**

```powershell
git add frontend/lib/api.ts
git commit -m "feat(api): add deleteChatHistory client"
```

---

## Task 6: `ChatContext.clearSession` + hook surface

**Files:**
- Modify: `frontend/lib/ChatContext.tsx:25-77, 126-146`
- Modify: `frontend/hooks/useChat.ts`

- [ ] **Step 1: Extend the context type and provider**

In `frontend/lib/ChatContext.tsx`, replace the `ChatCtxValue` interface (line 25):

```tsx
interface ChatCtxValue {
  sessions: Record<string, SessionState>
  sendMessage: (sessionId: string, text: string) => Promise<void>
  ensureHydrated: (sessionId: string) => void
  clearSession: (sessionId: string) => Promise<void>
}
```

Add an import at the top of the file:

```tsx
import { deleteChatHistory, getChatHistory, postChat } from '@/lib/api'
```

(Replace the existing `getChatHistory, postChat` import line.)

Inside `ChatProvider`, after the existing `sendMessage` definition (around line 124, before the JSX `return`), add:

```tsx
  const clearSession = useCallback(async (sessionId: string) => {
    await deleteChatHistory(sessionId)
    setSessions((all) => ({ ...all, [sessionId]: EMPTY }))
    // Drop the hydrated marker so a future remount can refetch (it would
    // return an empty list, but this keeps the data path consistent).
    setHydrated((s) => { const n = new Set(s); n.delete(sessionId); return n })
  }, [])
```

Then update the provider value:

```tsx
  return (
    <ChatCtx.Provider value={{ sessions, sendMessage, ensureHydrated, clearSession }}>{children}</ChatCtx.Provider>
  )
```

And update the hook return at the bottom of the file:

```tsx
export function useChatSession(sessionId: string) {
  const ctx = useChatCtx()
  useEffect(() => { ctx.ensureHydrated(sessionId) }, [sessionId, ctx])
  const session = ctx.sessions[sessionId] ?? EMPTY
  return {
    ...session,
    sendMessage: (text: string) => ctx.sendMessage(sessionId, text),
    clearSession: () => ctx.clearSession(sessionId),
  }
}
```

- [ ] **Step 2: Type-check**

```powershell
npx tsc --noEmit -p .
```

Expected: no errors.

- [ ] **Step 3: Commit**

```powershell
git add frontend/lib/ChatContext.tsx
git commit -m "feat(chat): expose clearSession on the chat hook"
```

---

## Task 7: Replace send button with trash "Delete chat" button

The text input stays in the DOM so the layout is unchanged, but it is disabled and Enter no longer sends. The button next to it now triggers `clearSession`.

**Files:**
- Modify: `frontend/components/ChatPanel.tsx:19-32, 89-110`
- Modify: `frontend/components/__tests__/ChatPanel.test.tsx`

- [ ] **Step 1: Replace the send-button tests**

In `frontend/components/__tests__/ChatPanel.test.tsx`:

- Remove the test `calls sendMessage on submit` (the button no longer sends).
- Remove the test `disables input while streaming` (the input is permanently disabled now; the regression isn't meaningful).
- Add these two tests inside the `describe('ChatPanel', …)` block:

```ts
  it('disables the message input', () => {
    render(<ChatPanel sessionId="dashboard" onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />)
    expect(screen.getByPlaceholderText(/Ask anything/)).toBeDisabled()
  })

  it('calls clearSession when the Delete chat button is clicked and confirmed', async () => {
    const clearSession = vi.fn().mockResolvedValue(undefined)
    vi.mocked(useChat).mockReturnValue({
      messages: [], isStreaming: false, error: null, sendMessage: vi.fn(), clearSession,
    } as any)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<ChatPanel sessionId="dashboard" onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /delete chat/i }))
    await waitFor(() => expect(clearSession).toHaveBeenCalledOnce())
  })
```

- [ ] **Step 2: Run tests, confirm they fail**

```powershell
cd frontend
npx vitest run components/__tests__/ChatPanel.test.tsx
```

Expected: the two new tests fail because the button still says "send" and the input isn't permanently disabled.

- [ ] **Step 3: Pull `clearSession` from the hook and disable the input**

In `frontend/components/ChatPanel.tsx`, replace lines 17-32 with:

```tsx
export default function ChatPanel({ sessionId, onCardClick, onFeedback, onSave }: Props) {
  const { messages, isStreaming, currentTool, error, clearSession } = useChat(sessionId)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, currentTool])

  async function handleDelete() {
    if (!window.confirm('Delete the entire chat history?')) return
    await clearSession()
  }
```

(Note: this drops the `input`/`setInput`/`handleSubmit` state — they are no longer used. Remove the unused `useState` import if Vitest/tsc warns.)

- [ ] **Step 4: Replace the input footer**

Replace lines 89-110 (the `Input` block) with:

```tsx
      {/* Input — disabled for demo; trash button clears the chat instead */}
      <div className="flex gap-1.5 px-3 py-2 border-t border-border">
        <input
          value=""
          disabled
          readOnly
          placeholder="Ask anything about events…"
          className="flex-1 text-[10px] border border-border rounded px-2 py-1.5 bg-bg-surface"
        />
        <button
          aria-label="Delete chat"
          onClick={handleDelete}
          className="bg-red-600 text-white rounded px-2.5 py-1.5 text-xs font-semibold hover:bg-red-700"
        >
          🗑
        </button>
      </div>
```

- [ ] **Step 5: Run tests, confirm they pass**

```powershell
npx vitest run components/__tests__/ChatPanel.test.tsx
npx tsc --noEmit -p .
```

Expected: ChatPanel tests pass; tsc clean.

- [ ] **Step 6: Smoke-test in the browser**

```powershell
cd frontend; npm run dev
```

Open http://localhost:3000, scroll to the chat panel:
- The header should say "Chat Assistant" only (no model line).
- The message input is greyed out.
- The button to its right is red with a trash icon.
- Clicking it pops a confirm dialog; confirming wipes the chat (backend must be running).

- [ ] **Step 7: Commit**

```powershell
git add frontend/components/ChatPanel.tsx frontend/components/__tests__/ChatPanel.test.tsx
git commit -m "feat(chat): replace send button with Delete chat trash button"
```

---

## Task 8: Hide tab switcher in AppointmentModal (only "Make an appointment")

**Files:**
- Modify: `frontend/components/calendar/appointmentModal/AppointmentModal.tsx:1-68`
- Modify: `frontend/components/__tests__/AppointmentModal.test.tsx`

- [ ] **Step 1: Add a failing test asserting tabs are gone**

In `frontend/components/__tests__/AppointmentModal.test.tsx`, append inside the `describe('AppointmentModal — Make tab', …)` block:

```ts
  it('does not render the tab switcher', () => {
    render(<AppointmentModal
      mode="create"
      initial={{ day: '2026-06-16', start_at: null, end_at: null, title: '' }}
      onClose={() => {}}
      onSaved={() => {}}
    />)
    expect(screen.queryByTestId('tab-make')).not.toBeInTheDocument()
    expect(screen.queryByTestId('tab-recommend')).not.toBeInTheDocument()
    expect(screen.queryByText(/Recommend me something/i)).not.toBeInTheDocument()
  })
```

- [ ] **Step 2: Run test, confirm it fails**

```powershell
npx vitest run components/__tests__/AppointmentModal.test.tsx
```

Expected: new test fails because `tab-make` / `tab-recommend` are still in the DOM.

- [ ] **Step 3: Replace the tab bar with `MakeAppointmentTab` only**

In `frontend/components/calendar/appointmentModal/AppointmentModal.tsx`, replace lines 1-68 with:

```tsx
'use client'
import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import MakeAppointmentTab, { type MakeInitial } from './MakeAppointmentTab'

export type AppointmentModalMode = 'create' | 'edit'

export interface AppointmentModalProps {
  mode: AppointmentModalMode
  initial: MakeInitial
  onClose: () => void
  onSaved: () => void
}

function Inner(props: AppointmentModalProps) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') props.onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [props.onClose])

  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  return (
    <div
      data-testid="appointment-modal-backdrop"
      className="fixed inset-0 z-50 flex items-center justify-center bg-text-primary/55 px-4"
      onClick={props.onClose}
    >
      <div
        className="relative bg-bg-page rounded-xl w-full max-w-md flex flex-col shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <MakeAppointmentTab
          mode={props.mode}
          initial={props.initial}
          onClose={props.onClose}
          onSaved={props.onSaved}
        />
      </div>
    </div>
  )
}

export default function AppointmentModal(props: AppointmentModalProps) {
  if (typeof document === 'undefined') return null
  return createPortal(<Inner {...props} />, document.body)
}
```

- [ ] **Step 4: Delete RecommendTab tests (file is now orphan-imported nowhere)**

Leave `frontend/components/calendar/appointmentModal/RecommendTab.tsx` and its test on disk so post-demo work can re-enable the tab by reverting the change above. No edit needed in this task.

- [ ] **Step 5: Run tests, confirm they pass**

```powershell
npx vitest run components/__tests__/AppointmentModal.test.tsx
npx tsc --noEmit -p .
```

Expected: all AppointmentModal tests pass; tsc clean.

- [ ] **Step 6: Commit**

```powershell
git add frontend/components/calendar/appointmentModal/AppointmentModal.tsx frontend/components/__tests__/AppointmentModal.test.tsx
git commit -m "chore(calendar): hide Recommend tab from appointment modal for demo"
```

---

## Task 9: Don't pre-fill `end_at` when opening "Make an appointment"

**Files:**
- Modify: `frontend/app/calendar/page.tsx:56-66`

- [ ] **Step 1: Stop suggesting an end time in `onEmptyClick`**

In `frontend/app/calendar/page.tsx`, replace lines 56-66 with:

```tsx
  function onEmptyClick(dayKey: string, startMinutes: number) {
    setModal({
      mode: 'create',
      initial: {
        day: dayKey,
        start_at: minutesToIso(dayKey, startMinutes),
        end_at: null,
        title: '',
      },
    })
  }
```

- [ ] **Step 2: Smoke-test in the browser**

With `npm run dev` running, open /calendar, click an empty slot in the week view. The "End" time field in the modal should be empty (not auto-filled with start + 60 min).

- [ ] **Step 3: Commit**

```powershell
git add frontend/app/calendar/page.tsx
git commit -m "feat(calendar): stop pre-filling end time for new appointments"
```

---

## Task 10: Rename Save / Saved → Slot in / Slot Out (event-save buttons only)

The appointment "Save" button in `MakeAppointmentTab.tsx` is for saving appointments, not for saving events — leave it alone.

**Files:**
- Modify: `frontend/components/EventCard.tsx:125, 151, 181`
- Modify: `frontend/components/EventChip.tsx:60`
- Modify: `frontend/components/EventDetailOverlay.tsx:220`
- Modify: `frontend/components/__tests__/EventCard.test.tsx:53-54, 57-60`
- Modify: `frontend/components/__tests__/EventChip.test.tsx`

- [ ] **Step 1: Update the EventCard tests**

In `frontend/components/__tests__/EventCard.test.tsx`:

- Line 53: replace `screen.getByText('Save')` with `screen.getByText('Slot in')`.
- Line 59: replace `screen.getByText('Saved ✓')` with `screen.getByText('Slot Out')`.

Final block for those two tests:

```ts
  it('calls onSave when Save clicked', () => {
    const onSave = vi.fn()
    render(<EventCard variant="feed" data={mockEventCtx} onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={onSave} />)
    fireEvent.click(screen.getByText('Slot in'))
    expect(onSave).toHaveBeenCalledWith('evt_001', true)
  })

  it('shows Saved when is_saved is true', () => {
    render(<EventCard variant="feed" data={{ ...mockEventCtx, is_saved: true }} onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />)
    expect(screen.getByText('Slot Out')).toBeInTheDocument()
  })
```

- [ ] **Step 2: Update the EventChip tests**

In `frontend/components/__tests__/EventChip.test.tsx`, replace the regex matchers that key off "save" / "saved":

```ts
  it('shows Slot in button when is_saved is false', () => {
    vi.mocked(useSWR).mockReturnValue({ data: mockEvent, error: undefined, mutate: vi.fn() } as any)
    render(<EventChip eventId="evt-1" />)
    expect(screen.getByRole('button', { name: /slot in/i })).toBeInTheDocument()
    expect(screen.queryByText(/slot out/i)).not.toBeInTheDocument()
  })

  it('shows Slot Out when is_saved is true', () => {
    vi.mocked(useSWR).mockReturnValue({ data: { ...mockEvent, is_saved: true }, error: undefined, mutate: vi.fn() } as any)
    render(<EventChip eventId="evt-1" />)
    expect(screen.getByRole('button', { name: /slot out/i })).toBeInTheDocument()
  })

  it('calls saveToCalendar with the event id on Slot in click', async () => {
    const mutate = vi.fn()
    vi.mocked(useSWR).mockReturnValue({ data: mockEvent, error: undefined, mutate } as any)
    vi.mocked(saveToCalendar).mockResolvedValue({} as any)
    render(<EventChip eventId="evt-1" />)
    fireEvent.click(screen.getByRole('button', { name: /slot in/i }))
    await waitFor(() => expect(saveToCalendar).toHaveBeenCalledWith('evt-1'))
  })
```

- [ ] **Step 3: Run tests, confirm they fail**

```powershell
npx vitest run components/__tests__/EventCard.test.tsx components/__tests__/EventChip.test.tsx
```

Expected: the relabeled tests fail because the components still render "Save"/"Saved ✓".

- [ ] **Step 4: Rename labels in EventCard**

In `frontend/components/EventCard.tsx`, replace each of the three occurrences of:

```tsx
{isSaved ? 'Saved ✓' : 'Save'}
```

with:

```tsx
{isSaved ? 'Slot Out' : 'Slot in'}
```

(Lines 125, 151, 181.)

- [ ] **Step 5: Rename label in EventChip**

In `frontend/components/EventChip.tsx:60`, replace:

```tsx
{event.is_saved ? 'Saved ✓' : 'Save'}
```

with:

```tsx
{event.is_saved ? 'Slot Out' : 'Slot in'}
```

- [ ] **Step 6: Rename label in EventDetailOverlay**

In `frontend/components/EventDetailOverlay.tsx:220`, replace:

```tsx
{isSaved ? 'Saved ✓' : 'Save to Calendar'}
```

with:

```tsx
{isSaved ? 'Slot Out' : 'Slot in'}
```

- [ ] **Step 7: Run all affected tests, confirm they pass**

```powershell
npx vitest run components/__tests__/EventCard.test.tsx components/__tests__/EventChip.test.tsx components/__tests__/EventDetailOverlay.test.tsx
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```powershell
git add frontend/components/EventCard.tsx frontend/components/EventChip.tsx frontend/components/EventDetailOverlay.tsx frontend/components/__tests__/EventCard.test.tsx frontend/components/__tests__/EventChip.test.tsx
git commit -m "feat(events): rename Save/Saved buttons to Slot in/Slot Out"
```

---

## Task 11: Final verification

- [ ] **Step 1: Run the full frontend test suite**

```powershell
cd frontend
npx vitest run
npx tsc --noEmit -p .
```

Expected: all suites green, no TypeScript errors.

- [ ] **Step 2: Run the full backend test suite**

```powershell
cd backend
poetry run pytest
```

Expected: all suites green.

- [ ] **Step 3: Smoke-test the demo flow end-to-end**

Start both servers (`backend: poetry run uvicorn app.main:app --reload`; `frontend: npm run dev`) and walk through:

- TopNav reads "SlotIn"; no Settings link.
- Chat header shows only "Chat Assistant"; input is greyed; trash button is red and clears history (verify a new chat starts clean after refresh).
- Clicking an empty calendar slot opens the modal with only the "Make an appointment" form, end time blank.
- Saving an event from the feed / detail overlay / chip shows "Slot in" → "Slot Out" toggle.

- [ ] **Step 4: No commit needed**

Verification only.
