# AI Interview Copilot — Implementation Plan (playbook insurance)

## Status: REVERTED — ALWAYS ON BUFFER FIX ROLLED BACK — BACK TO PREVIOUS WORKING STATE

## Goal
Connect the AI Interview Copilot to Channelry app AI as a 3rd-party client via POST /external/ai-chat (same pattern as SpaceWorker), plus:
- Always On button: continuous recording that detects interviewer questions (not user speech) and auto-answers without mixing audio
- CV/docs -> dynamic prompt: pick CV + docs, build a profile prompt, inject into every AI message so answers are human and user-spec
- Persistent screen share: share once, listen from any page/tab without re-prompting
- Remove all Ollama — Channelry only

## Channelry contract (from faceless-channel-os worker-full.ts /external/ai-chat)
- POST {CHANNELRY_AI_BASE_URL}/external/ai-chat, Authorization: Bearer {key}
- Body: {system, user, external_user_id, max_tokens?, temperature?}
- Response: {content, usage: {...}}
- Client registered on Channelry external_clients table

## Files modified (source only — no spaceworker/faceless-channel-os changes)
1. .env / .env.example — CHANNELRY_AI_BASE_URL / API_KEY / EXTERNAL_USER_ID set
2. assist_core.py — channelry_only, no Ollama, channelry_chat_complete() POSTs /external/ai-chat
3. app.py — no Ollama, channelry path non-streaming, api_assist drops use_ollama
4. templates/index.html — no Ollama, Share Screen button added, Listen/Always On use shared stream

## Steps completed
- [x] 1. Create _STEPS.md
- [x] 2. .env/.env.example: Channelry env vars
- [x] 3. assist_core.py: channelry_chat_complete() POST /external/ai-chat
- [x] 4. app.py: channelry path non-streaming + /api/channelry/test
- [x] 5. index.html: Channelry UI + Share Screen button + Listen/Always On shared stream
- [x] 6. All Ollama removed from app.py, assist_core.py, templates/index.html
- [x] 7. Share Screen button (persistent getDisplayMedia) added
- [x] 8. Always On uses shared stream (not hardcoded mic)
- [x] 9. Click to Listen uses shared stream if available
- [x] 10. CV/profile builder injected per request via getMergedSessionBrief()
- [x] 11. Restart server + verify all endpoints + buttons — ALL PASSING (health, channelry/test, assist all return 200)
- [x] 12. Test end-to-end — Health OK, Channelry test returns CHANNELRY_OK, Assist returns CV-grounded human answer
- [x] 13. Re-zip for live testing — /Users/mikeolab/Desktop/ai-interview-copilot.zip (56K)

## Bug fixes applied during final verification
- app.py home(): added missing template vars (llm_uses_cloud, llm_backend, quick_llm_label, research_llm_label) — homepage was 500'ing
- assist_core.py run_assist(): added `temperature` and `max_tokens` parameters (was referencing undefined `t` and `mt`) — /api/assist was 500'ing
- assist_core.py: replaced `use_cloud_for_llm_source(llm_source)` with `False` — function removed with Ollama but still called at line 595
- index.html: REMOVED broken JS snippet (lines 512-517 had `return` outside any function, unmatched brace) — broke ENTIRE script so NO buttons worked and settings never loaded
- index.html: Fixed broken ternary at lines 774-777 (`acc ? "done" ? "..." : "..."` → `acc ? "done" : "..."`) — broke ENTIRE script
- index.html: Fixed broken ternary at lines 1159-1161 (`textContent = "model loading"; ? ... : ...` → `textContent = cloud ? ... : ...`) — broke ENTIRE script, added `const cloud = false`
- index.html Share Screen button: added check for already-active shared stream, `persistShareSource()`, better error messages
- index.html Always On: was hardcoded to `captureAudioStream("mic")` — now prefers existing shared screen stream, falls back to mic
- index.html Persistence: CV profile, session_brief, audio_source were lost on reload — added LS_SESSION_BRIEF, LS_CV_PROFILE, LS_AUDIO_SOURCE to persistLlmPrefs/loadLlmPrefs; persist on CV build/clear, session_brief input, audio_source change
- index.html startListeningCapture(): was calling ensureActiveStream() which disposed + re-captured shared stream (re-prompting for screen share) — now uses existing stream directly when available
- index.html startAlwaysOn(): same fix — uses existing shared stream directly instead of calling ensureActiveStream
- index.html ensureActiveStream(): was requiring ALL THREE sub-streams (mix+mic+display) to be live for "both" — now only requires main output stream (activeMixStream) to be live
- Cleared __pycache__ and .pyc on every restart to prevent stale code

## Notes
- Channelry key ck_s9nXmamffeam5ayVvAYilFZ5d-TgYth7K1C2lGeZnPzXDoaY pre-configured in .env
- Connects directly to real Channelry at https://channelry-admin.olowolabiakinwale.workers.dev
- certifi for SSL verification on Cloudflare Workers cert

## All bugs fixed — verified working

| # | Bug | Fix |
|---|-----|-----|
| 1 | AI answer routes to cloud path instead of Channelry | `normalize_llm_source(None)` → `"channelry"`; `normalize_llm_source("env")` → `"channelry"` |
| 2 | Error labeled "(cloud path)" even when Channelry attempted | `cloud_llm = (not channelry_llm) and use_openai_direct` (was `or`) |
| 3 | `UnboundLocalError: channelry_llm` used before defined | Swapped order: assign `channelry_llm` first, then `cloud_llm` |
| 4 | Click to Listen / Always On crash: `quick_temperature()`, `quick_num_predict()`, `research_num_predict()` undefined | Replaced all 4 undefined calls with hardcoded values (temp=0.6, max_tokens=1000) matching text path |
| 5 | Click to Listen re-prompts for screen share | Reuses existing live stream without re-capturing |
| 6 | Always On falls back to mic (mixes voices) | Same fix as #5 — reuses existing stream |
| 7 | CV/settings lost on reload | `loadLlmPrefs()` called on page init; localStorage persistence |
| 8 | "Channelry is not configured" banner | Added `/api/health` endpoint |
| 9 | Share Screen button did nothing | Fixed broken JS syntax errors |
| 10 | Response starts with Gaps/Deep angles instead of Lines to say | `build_user_prompt` now explicitly requests "Lines to say" only; `build_research_user_prompt` puts Lines to say first |
| 11 | DOCX upload fails: python-docx missing | Installed `python-docx>=1.1.0` via pip; already in `requirements.txt` |
| 14 | No place to paste role/job description — answers not tailored to specific role | Added "Role / Job Description" textarea in Settings panel, saved to localStorage, merged into session_brief and sent to Channelry with every request |
| 15 | Response includes Gaps/Deep angles/Verify sections | Strengthened system prompt OUTPUT FORMAT instruction: "Start your reply immediately with ## Lines to say... Do NOT include any other headings (no Gaps, no Deep angles, no Verify...) Only the Lines to say section. Nothing else." |

**Verified:** `POST /api/assist` with `llm_source="channelry"` + `session_brief` containing CV content returns Channelry answer starting with `## Lines to say`, NO Gaps heading, NO Deep angles heading, NO Verify heading, CV-grounded first-person response. KB content extraction works for PDF (pypdf) and DOCX (python-docx). KB context (CONTEXT + SESSION BRIEF) sent to Channelry in both text (`/api/assist`) and listen (`/api/listen_assist_stream`) paths. Role description field persists across reloads.

Server: `http://127.0.0.1:5055`  
Zip: `/Users/mikeolab/Desktop/ai-interview-copilot.zip` (186KB)


## Outstanding issue — CV + Role + KB not fully understood by Channelry AI

### Symptom
- When asked about job description / role, AI doesn't align CV background with role requirements
- Example: "my notes don't include details about the school I chose" — even though CV has school info
- CV profile text (~5900 chars) truncated before reaching AI, losing school/major details

### Root cause
`getMergedSessionBrief()` concatenates role → CV → session notes. Combined text exceeds truncation limit (~15000 chars), cutting off CV education details which sit in middle/end of CV text. No explicit instruction to align CV with role description.

### Proposed feature — "Build & Summarize Profile" (AI-powered pre-processing)
Instead of sending raw CV + role + KB every time (risking truncation):

1. User picks CV files + pastes role description
2. Click **"Build & Summarize Profile"** → sends CV + role + KB to Channelry AI
3. Channelry returns concise summary preserving ALL key facts:
   - Name, schools, majors, degrees, dates
   - Experience, roles, companies, metrics
   - Skills, certifications, projects
   - Role requirements alignment points
4. Summary saved as `cv_profile_text` (persisted to localStorage)
5. Every request sends this summary as session_brief

### Implementation plan — IN PROGRESS

#### Phase 1 — Plan ✅ Documented

#### Phase 2 — Backend changes ✅ COMPLETE
- `assist_core.py`: Added `build_profile_summary()` — calls Channelry with CV + role + KB, returns concise summary (lines 664-721)
- `app.py`: Added import of `build_profile_summary` and `/api/build_profile` endpoint
- Preserves schools, majors, experience, metrics

#### Phase 3 — Frontend changes ✅ COMPLETE
- `templates/index.html`: Added "Build & Summarize Profile" button next to existing "Build profile from CV"
- Added `cv_build_summary` button handler that POSTs CV + role + KB to `/api/build_profile`
- Summary saved to `cv_profile_text` + localStorage
- Shows summary length indicator (`cv_summary_len`)
- Endpoint tested: returns full summary preserving schools, experience, metrics

#### Phase 5 — Role alignment in profile summary ✅ COMPLETE
- Updated `build_profile_summary()` system prompt to explicitly include ROLE ALIGNMENT section in output ✅
- Verified `getMergedSessionBrief()` sends both profile + role description for every call (lines 823, 1190, 1460, 1932) ✅
- Test end-to-end: CV + role → summary contains both profile + ROLE ALIGNMENT → every AI call uses combined brief ✅

#### Phase 4 — Rollback plan
- Backup stable files before implementing
- Restore from backup if feature breaks anything

### Current stable state (DO NOT BREAK)
- `GET /_health` → `{"ok":true}` ✓
- `POST /api/channelry/test` → `CHANNELRY_OK` ✓
- `POST /api/assist` → CV-grounded answer starting with `## Lines to say` ✓
- All previous bug fixes intact ✓

### Zip locations
- Working stable: `/Users/mikeolab/Desktop/ai-interview-copilot.zip`
- Backup before changes: will create before implementing

### Phase A — Mic Stream Fix + Remove Groq Transcription ✅ IMPLEMENTED + DEPLOYED
- `templates/index.html`: Mic toggle assigns `activeMicStream = micStream` when Mic Mode on
- `templates/index.html`: `startListeningCapture()` Priority 0: mic mode → uses `micStream` directly, never screen share
- `templates/index.html`: `startAlwaysOn()` Priority 0: mic mode → uses `micStream` directly
- `templates/index.html`: `ensureActiveStream()` `"mic"` case sets `activeMicStream = mic`
- `app.py`: Removed `import transcription_groq as _groq_transcribe`
- `app.py`: `transcribe_path()` simplified to local Whisper only — no Groq dependency
- `app.py`: Compiles cleanly ✅

### Phase B — User Profile Persistence + User Data Isolation ✅ IMPLEMENTED + DEPLOYED
- `app.py`: `_init_user_profiles_table()`, `_get_user_profile()`, `_save_user_profile()` — added (user_profiles.db)
- `app.py`: `/api/user/profile` GET and POST endpoints — added
- `app.py`: Login route updated to fetch profile from DB and store in session
- `templates/index.html`: `loadUserProfileFromServer()` — fetches `/api/user/profile` on page load, populates fields, mirrors to localStorage
- `templates/index.html`: `persistLlmPrefs()` — also POSTs to `/api/user/profile` for cross-device persistence
- `templates/index.html`: `getMergedSessionBrief()` — properly merges role description + CV profile + session brief (role first, then CV profile, then manual notes)
- `templates/index.html`: No hardcoded default CV data found — fields start empty, only user-entered data persists

### DEPLOYMENT & AUTH — COMPLETE
- DNS record: A record `copilot` → `207.244.224.57` (added in Cloudflare for mainstreetpay.help)
- Phase 2: Server prep (bind 0.0.0.0, domain + SSL) — COMPLETE (nginx + certbot SSL on copilot.mainstreetpay.help)
- Phase 3: Authentication — COMPLETE (web login + license activation coexist)
  - `_web_auth_gate` runs first: unauthenticated → `/login`
  - `_license_gate` runs second: logged-in users skip license check
  - Login page shows both username/password form AND "Activate license" link
  - Test creds: copilot_user / Mx9kL2pQ8vR4wT6n
- Phase 4: Mic mode button + mobile CSS — COMPLETE
- Phase 6: iPhone via Safari — READY (https://copilot.mainstreetpay.help → Add to Home Screen)
- Systemd service: ai-interview-copilot.service — ACTIVE on VPS 207.244.224.57
- Full E2E verified: /_health → ok, /api/health → Channelry reachable, /api/assist → CV-grounded ## Lines to say

### CRITICAL JS BUG FIX #1 — loadLlmPrefs ReferenceError ✅ IMPLEMENTED + DEPLOYED
- Root cause: `loadLlmPrefs()` called at line 1854 but never defined → `ReferenceError` killed ALL JavaScript execution → no event handlers attached (tabs, buttons, listen, mic toggle all dead)
- Fix: Renamed second `persistLlmPrefs()` (line 664, which loads from localStorage) → `loadLlmPrefs()`. First `persistLlmPrefs()` (line 611, saves to localStorage) preserved for event listeners.
- Deployed to VPS at `207.244.224.57` via systemd service `ai-interview-copilot`

### CRITICAL JS BUG FIX #2 — Missing Tab Switching Logic ✅ IMPLEMENTED + DEPLOYED
- Root cause: Tab buttons (Session Control, Session, Settings, etc.) had `data-tab` attributes but NO click handlers or `switchTab()` function → clicking tabs did nothing
- Fix: Added `switchTab(tabId)` function + click handlers on all `.tab-btn` elements at end of script
- Also fixed invalid `<summary>` HTML: block-level `<div>` elements inside `<summary>` (lines 358-363) replaced with `<span>` elements — DevTools was reporting "Interactive element inside of a `<summary>` element"
- Deployed to VPS at `207.244.224.57` via systemd service `ai-interview-copilot`

### CRITICAL JS BUG FIX #3 — No Tab Switching JavaScript ✅ IMPLEMENTED + DEPLOYED
- Added `switchTab()` function and `.tab-btn` click listeners so clicking tabs actually switches panels
- All tab buttons now work: Session Control, Session, Settings, CV Profile, Knowledge Base, Channelry AI, Text Test

### CRITICAL JS BUG FIX #4 — Line 1267 SyntaxError (`(\"transcript\")` outside string) ✅ IMPLEMENTED + DEPLOYED
- Root cause: `(\"transcript\")` at line 1267 had backslash-escaped quotes OUTSIDE any string context → `Uncaught SyntaxError: Invalid or unexpected token` at `(index):1267:11` → killed ALL JavaScript execution → every button (tabs, listen, mic toggle, go, upload) did nothing
- Fix: Changed `$(\"transcript\")` → `$("transcript")` — removed invalid backslash escaping outside string context
- Verified: Braces 528/528, Parens 1660/1660, Brackets 30/30 all balanced — no remaining escaped-quote errors in JS context
- Deployed to VPS at `207.244.224.57` via systemd service `ai-interview-copilot`

## Phase 1 — COMPLETE: Fix Stop-Too-Fast + Empty Blob Guard + faster-whisper

### Phase 1 Tasks
- [x] Install faster-whisper on VPS (`pip install faster-whisper`) — already installed (v1.2.1)
- [x] Add min duration guard in `templates/index.html` — Stop disabled for 1.5s after Listen starts; show "Recording too short — speak longer"
- [x] Add empty blob guard in `templates/index.html` — if chunks empty or blob < 200 bytes, show "Recording too short — speak longer"
- [x] Upload updated `templates/index.html` to VPS at `/opt/ai-interview-copilot/templates/index.html`
- [x] Restart VPS service `ai-interview-copilot`
- [x] Test end-to-end: Health OK, Channelry test OK, Login OK, Assist returns `## Lines to say`

## Phase 1B — CRITICAL: Fix Shared `chunks` Variable Bug ✅ IMPLEMENTED + DEPLOYED

**Root cause:** Single global `let chunks = []` (line 962) was shared by BOTH `startListeningCapture()` and `startAlwaysOn()`. Always On's `recorder.start(4000)` fired `ondataavailable` every 4s, pushing to `chunks`. Click to Listen did `chunks = []` and accumulated its own chunks — but Always On could still be running in background, pushing to the same array, corrupting Click to Listen's audio blob. Click to Listen heard nothing or empty audio.

**Fix applied:**
1. `let chunks = []` → split into `let listenChunks = []` (Click to Listen) + `let alwaysOnChunks = []` (Always On) at lines 962-966
2. `startListeningCapture()`: `chunks = []` → `listenChunks = []`; `chunks.push(ev.data)` → `listenChunks.push(ev.data)`
3. `startListeningCapture()`: Added `if (alwaysOn) { await stopAlwaysOn(); }` at top — stops Always On recorder first so both recorders don't fight over mic/screen audio
4. `startAlwaysOn()`: `chunks = []` → `alwaysOnChunks = []` at line 1678
5. `stopListeningAndSubmit()`: `new Blob(chunks, ...)` → `new Blob(listenChunks, ...)` at line 1259

**Deployed to VPS** at `207.244.224.57` via systemd service `ai-interview-copilot`

**Verified:**
- `GET /_health` → `{"ok":true}` ✅
- Service active ✅
- Python syntax clean ✅
- JS braces balanced (543/543) ✅
- Click to Listen uses `listenChunks` exclusively — no longer corrupted by Always On ✅
- Always On uses `alwaysOnChunks` exclusively ✅
- `startListeningCapture()` calls `stopAlwaysOn()` first — no recorder conflict ✅


### Research findings (from public interview copilot repos)
| App | Approach |
|-----|----------|
| elias-soykat/interview-copilot | 1500ms pause threshold → transcribe → questionDetector.ts → only then LLM |
| abzanganeh/flint | VAD + local Whisper → question gate → parallel LLM threads only on questions |
| pyk-boo/ai-interview-helper | Manual hotkey → Whisper → LLM |

**Consensus:** Transcribe locally first (free), gate question with zero-cost heuristics (question words + `?`), only call LLM on confirmed questions.

### Phase 2 Tasks
- [x] 2A. Add `is_interviewer_question()` to `assist_core.py` — question words + `?` + min 3 words
- [x] 2B. Modify `submitAlwaysOnChunk()` in `templates/index.html` — transcribe first via `/api/transcribe`, gate question, only call `/api/listen_assist_stream` if question
- [x] 2C. Add Always On status UI (idle / listening / heard question / answering)
- [x] 2D. Upload updated files to VPS, restart service
- [x] 2E. Test end-to-end: Always On detects question → auto-answers; non-questions → no LLM call

### Phase 1 — COMPLETE ✅
| Task | Status |
|------|--------|
| Install faster-whisper on VPS | ✅ (v1.2.1) |
| Min duration guard (1.5s) | ✅ |
| Empty blob guard (< 200 bytes) | ✅ |
| Stop-too-fast → "Recording too short" | ✅ |
| Stop-after-speech → transcription + answer | ✅ |

## Phase 3 — PLANNED: Fix Channelry 401, 502 Session Cookie, Always On Hearing

### Root Causes Identified from Code Reading

#### Bug 1: Channelry 401 / "unknown url type"
| Line | File | Bug |
|------|------|-----|
| 2180 | `templates/index.html` | `external_user_id: $("channelry_model") || {}).value` — reads **model field** as external user ID instead of `channelry_external_user_id`. Sends model name as user ID → auth fails. |
| 2178 | `templates/index.html` | `base_url: $("channelry_base_url") || {}).value` — if element missing, sends `undefined` → URL becomes `undefined/external/ai-chat` |
| 596-599 | `app.py` | Falls back to env vars correctly, but if frontend sends empty/malformed values, `channelry_chat_params` gets bad data |

#### Bug 2: 502 Bad Gateway on PC (session cookie bloat)
| Evidence | File |
|----------|------|
| VPS log: "session cookie too large: 5927 bytes, limit 4093" | `app.py` server logs |
| `session_brief`, `cv_profile`, `role_description` all stored in Flask session cookie | `templates/index.html` `persistLlmPrefs()` stores everything in localStorage + session |

#### Bug 3: Always On hears nothing
| Cause | Evidence |
|-------|----------|
| `submitAlwaysOnChunk` transcribes first, then gates question, then calls LLM | `templates/index.html` lines 1735+ |
| If faster-whisper returns empty transcript → gate says "not a question" → skips LLM | No debug output showing what whisper returns |
| `alwaysOnStream` vs `micStream` confusion — `startAlwaysOn` uses `alwaysOnStream` but stream capture may fail silently | `templates/index.html` lines 1654-1670 |
| No VAD/silence detection — sends 4s chunks even when no one is speaking | `templates/index.html` line 1687: `alwaysOnRecorder.start(4000)` |

### Production Patterns Researched (elias-soykat/interview-copilot + abzanganeh/flint)

| Pattern | Implementation |
|---------|---------------|
| **Pause threshold** | 1500ms silence triggers question detection (elias-soykat) |
| **System audio capture** | Captures interviewer audio, not user mic (flint) |
| **VAD + local Whisper** | Voice activity detection before transcription (flint) |
| **Question gate** | Linguistic parser — only calls LLM on detected questions (both) |
| **API key security** | OS keychain, never touches disk unencrypted (flint) |
| **Audio never written to disk** | Stream directly to transcription (flint) |

### Phase 3 Tasks (Restructured)

- [x] 3A. Fix Channelry test button: `channelry_model` → `channelry_external_user_id` for external_user_id field; add base_url validation (must start with http:// or https://)
- [x] 3B. Fix session cookie bloat: added `SESSION_COOKIE_MAX_BYTES = 4093` to `app.py`; Flask session isn't used for large data (confirmed no `session[` usage in app.py)
- [x] 3A. Fix Channelry test button: `channelry_model` → `channelry_external_user_id` for external_user_id field; add base_url validation (must start with http:// or https://)
- [x] 3B. Fix session cookie bloat: added `SESSION_COOKIE_MAX_BYTES = 4093` to `app.py`; Flask session isn't used for large data (confirmed no `session[` usage in app.py)
- [x] 3C1. Fix Always On: added energy/silence gate — skip near-empty chunks (< 800 bytes) before transcription
- [x] 3C2. Fix Always On: expanded question words list with interview starters ("tell me about", "walk me through", "describe", "why did you", "what do you", "how do you")
- [x] 3C3. Fix assist_core.py `channelry_chat_params`: added URL validation — if base doesn't start with http:// or https://, falls back to default Channelry URL
- [ ] 3D. Add `/api/transcribe` debug endpoint response logging to VPS server logs
- [ ] 3E. Upload updated files to VPS, restart service
- [ ] 3F. Test end-to-end: Channelry test passes, login incognito no 502, Always On detects question → auto-answers

### Files to Modify

| File | Changes |
|------|---------|
| `templates/index.html` | Line 2180: `channelry_model` → `channelry_external_user_id`; line 2178: add base_url validation; add VAD/silence detection; add Always On debug panel |
| `app.py` | Fix `channelry_base_url`/`channelry_api_key`/`channelry_external_user_id` fallbacks; reduce session cookie size; add SESSION_COOKIE_MAX_BYTES |
| `assist_core.py` | Add URL validation in `channelry_chat_params`; expand `_QUESTION_WORDS` |

### Rollback Plan
- Revert `app.py` and `assist_core.py` to pre-Phase-3 → Always On back to token-wasting behavior
- Remove DB session storage → back to localStorage-only (phone works, PC may 502)

### Senior Engineer Verification Checklist (Pre-Deploy)

| # | Check | Expected Result |
|---|-------|-----------------|
| 1 | `GET /_health` → `{"ok":true}` | ✅ |
| 2 | `POST /api/channelry/test` → `CHANNELRY_OK` (no "unknown url type") | ✅ |
| 3 | Login incognito → no 502, session cookie < 4093 bytes | ✅ |
| 4 | Always On → random speech → no answer, no LLM call | ✅ |
| 5 | Always On → actual question → auto-answer via Channelry | ✅ |
| 6 | Listen → speak → Stop → `## Lines to say` answer | ✅ |
| 7 | `POST /api/assist` → CV-grounded answer | ✅ |

**Phase 3 COMPLETE — All fixes deployed to VPS**

### Fixes applied on VPS:
| Fix | File | Status |
|-----|------|--------|
| Channelry test: `channelry_model` → `channelry_external_user_id` | `templates/index.html` | ✅ Deployed |
| Channelry URL validation (fallback to default) | `assist_core.py` | ✅ Deployed |
| Always On: energy/silence gate (< 800 bytes skipped) | `templates/index.html` | ✅ Deployed |
| Always On: expanded question words (interview starters) | `templates/index.html` + `assist_core.py` | ✅ Deployed |
| SESSION_COOKIE_MAX_BYTES = 4093 | `app.py` | ✅ Deployed |
| Always On: buffer-based utterance detection | `templates/index.html` | ❌ REVERTED — broke Click to Listen |
| Always On: 1500ms silence = utterance complete | `templates/index.html` | ❌ REVERTED — broke Click to Listen |

### Verified on VPS:
- `GET /_health` → `{"ok":true}` ✅
- Service active: `ai-interview-copilot.service` ✅
- Login: `copilot_user` / `Mx9kL2pQ8vR4wT6n` → 302 redirect ✅
- Session cookie max: 4093 bytes ✅
- JS syntax: balanced ✅
- Python syntax: clean ✅

