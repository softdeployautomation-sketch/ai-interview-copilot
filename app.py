"""
KB-first live assistant: local Whisper → retrieve → Channelry AI.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
from pathlib import Path

# Load kb-copilot/.env before any os.environ reads (optional: pip install python-dotenv).
_ROOT = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
except ImportError:
    pass

from functools import wraps
from flask import Flask, jsonify, make_response, render_template, request, session, stream_with_context, redirect, url_for, flash
from werkzeug.utils import secure_filename

import shutil
import subprocess
import time

from assist_core import (
    best_kb_snippet,
    build_profile_summary,
    build_research_system_prompt,
    build_research_user_prompt,
    build_system_prompt,
    build_user_prompt,
    channelry_chat_complete,
    channelry_chat_params,
    _channelry_default_external_user_id,
    is_interviewer_question,
    kb_fallback_reply,
    kb_is_weak,
    normalize_llm_source,
    run_assist,
    trim_hits_for_prompt,
    use_channelry_for_llm_source,
)
from kb_store import delete_file as kb_delete_file
from kb_store import list_files as kb_list_files
from kb_store import save_upload as kb_save_upload
from kb_store import safe_name as kb_safe_name
from retrieval import BM25Index, load_corpus
from transcription import transcribe_path as _local_transcribe
from transcription import warmup as whisper_warmup


def transcribe_path(audio_path, language=None):
    """
    Local speech-to-text via faster-whisper (offline mode, requires local model).
    No Groq/cloud transcription — Channelry handles AI answers only.
    """
    return _local_transcribe(audio_path, language=language)


import license as _license


def use_openai_direct() -> bool:
    """True = native OpenAI backend; False = OpenAI-compatible (e.g. Groq) backend."""
    return (os.environ.get("KB_LLM_BACKEND") or "").strip().lower() == "openai"


def openai_native_key() -> str:
    return os.environ.get("OPENAI_API_KEY") or ""


def openai_native_base() -> str:
    return os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"


def openai_compat_key() -> str:
    return os.environ.get("OPENAI_COMPAT_API_KEY") or os.environ.get("GROQ_API_KEY") or ""


def openai_compat_base() -> str:
    return os.environ.get("OPENAI_COMPAT_BASE_URL") or "https://api.openai.com/v1"


from openai_compatible_client import chat_stream as _chat_stream


def openai_chat_stream(
    base_url: str,
    api_key: str,
    model: str,
    user: str,
    system: str | None = None,
    *,
    timeout_s: float = 120.0,
    temperature: float = 0.5,
    max_tokens: int = 1024,
):
    """Streaming chat completion; yields text deltas (stdlib HTTP, works with Groq)."""
    yield from _chat_stream(
        base_url,
        api_key,
        model,
        user,
        system=system,
        timeout_s=timeout_s,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def resolve_cloud_research_model(override: str | None) -> str:
    """Resolve the cloud research model, falling back to the quick answer model."""
    o = (override or "").strip()
    if o:
        return o
    env_r = (os.environ.get("OPENAI_ANSWER_RESEARCH_MODEL") or "").strip()
    if env_r:
        return env_r
    return openai_answer_model_quick(None)


def _require_activation():
    """Block all requests until license is activated. Returns None if OK."""
    if request.path in ("/activate", "/login", "/logout", "/_health", "/static"):
        return None
    if request.path.startswith("/static/"):
        return None
    ok, info = _license.is_activated()
    if ok:
        return None
    # Redirect to activation page
    from flask import redirect
    return redirect("/activate")


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_MB", "32")) * 1024 * 1024
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me-in-production")
app.config["SESSION_COOKIE_MAX_BYTES"] = 4093

# Web authentication credentials (username/password for browser access)
USER_CREDENTIALS = {
    "copilot_user": "Mx9kL2pQ8vR4wT6n",
}


# ── Server-side user profile persistence (isolated per user_id) ──
_DB_PATH = Path(__file__).resolve().parent / "user_profiles.db"


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_user_profiles_table() -> None:
    conn = _get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL UNIQUE,
                cv_text TEXT DEFAULT '',
                role_description TEXT DEFAULT '',
                session_brief TEXT DEFAULT '',
                built_summary TEXT DEFAULT '',
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    finally:
        conn.close()


# Initialize table on import
_init_user_profiles_table()


def _get_user_profile(user_id: str) -> dict:
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT cv_text, role_description, session_brief, built_summary FROM user_profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row:
            return {
                "cv_text": row["cv_text"] or "",
                "role_description": row["role_description"] or "",
                "session_brief": row["session_brief"] or "",
                "built_summary": row["built_summary"] or "",
            }
        return {"cv_text": "", "role_description": "", "session_brief": "", "built_summary": ""}
    finally:
        conn.close()


def _save_user_profile(user_id: str, cv_text: str = "", role_description: str = "",
                       session_brief: str = "", built_summary: str = "") -> None:
    conn = _get_db()
    try:
        conn.execute("""
            INSERT INTO user_profiles (user_id, cv_text, role_description, session_brief, built_summary, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                cv_text = EXCLUDED.cv_text,
                role_description = EXCLUDED.role_description,
                session_brief = EXCLUDED.session_brief,
                built_summary = EXCLUDED.built_summary,
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, cv_text, role_description, session_brief, built_summary))
        conn.commit()
    finally:
        conn.close()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated


@app.before_request
def _web_auth_gate():
    public_paths = ("/login", "/logout", "/_health", "/api/health", "/activate", "/static")
    if request.path in public_paths or request.path.startswith("/static/"):
        return None
    if not session.get("user"):
        return redirect(url_for("login", next=request.path))
    return None


@app.before_request
def _license_gate():
    # Web version: authenticated users skip license check (login supersedes license)
    if session.get("user"):
        return None
    # If not logged in, _web_auth_gate already redirected to /login
    return None


@app.route("/_health")
def _health():
    return jsonify({"ok": True})


@app.route("/api/health")
def api_health():
    """Health endpoint returning Channelry configuration status for the frontend."""
    base = os.environ.get("CHANNELRY_AI_BASE_URL", "").rstrip("/")
    key = os.environ.get("CHANNELRY_AI_API_KEY", "").strip()
    reachable = bool(base and key)
    model = os.environ.get("CHANNELRY_AI_MODEL", "channelry-ai")
    llm_backend = "channelry"
    llm_provider = "channelry"
    cloud_key_set = bool(os.environ.get("GROQ_API_KEY", "").strip())
    return jsonify({
        "ok": True,
        "channelry": {
            "reachable": reachable,
            "quick_model": model,
            "quick_available": reachable,
            "quick_loaded": reachable,
            "model_available": reachable,
            "research_model": model,
            "models": [model] if reachable else [],
        },
        "llm": {
            "backend": llm_backend,
            "provider": llm_provider,
            "cloud_key_set": cloud_key_set,
            "has_cloud_key": cloud_key_set,
            "note": "Channelry AI only",
        },
    })


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()
        if USER_CREDENTIALS.get(username) == password:
            session["user"] = username
            session.permanent = True
            # Fetch user's saved profile from DB for frontend
            profile = _get_user_profile(username)
            session["profile"] = profile
            nxt = request.form.get("next") or request.args.get("next") or "/"
            return redirect(nxt)
        flash("Invalid username or password", "error")
    return render_template("login.html", next=request.args.get("next", "/"))


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))


@app.route("/activate", methods=["GET", "POST"])
def activate():
    if request.method == "POST":
        key = (request.form.get("license_key") or request.json.get("license_key", "") if request.is_json else request.form.get("license_key", "")).strip()
        info = _license.validate_license(key)
        if info.valid:
            _license.save_license(key)
            return render_template("activate.html",
                                   message=f"✅ Activated for {info.licensee} — refresh the page to continue.",
                                   success=True,
                                   hwid=_license.get_machine_id())
        return render_template("activate.html",
                               message=f"❌ {info.error}",
                               success=False,
                               hwid=_license.get_machine_id())
    return render_template("activate.html", message="", success=None, hwid=_license.get_machine_id())

_index_lock = threading.Lock()
_index: BM25Index | None = None
_kb_root: Path | None = None


def kb_path() -> Path:
    raw = os.environ.get("KB_ROOT", "")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path(__file__).resolve().parent / "kb").resolve()


def openai_native_base() -> str:
    return (os.environ.get("OPENAI_API_BASE") or "https://api.openai.com/v1").rstrip("/")


def openai_answer_model_quick(override: str | None) -> str:
    o = (override or "").strip()
    if o:
        return o
    return (os.environ.get("OPENAI_ANSWER_MODEL") or "gpt-4o-mini").strip()


def openai_answer_model_research(quick_override: str | None, research_override: str | None) -> str:
    r = (research_override or "").strip()
    if r:
        return r
    env_r = (os.environ.get("OPENAI_ANSWER_RESEARCH_MODEL") or "").strip()
    if env_r:
        return env_r
    return openai_answer_model_quick(quick_override)


def transcript_looks_like_question(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 12:
        return False
    if "?" in t:
        return True
    low = t.lower()
    needles = (
        "why ",
        "why?",
        "how ",
        "what ",
        "when ",
        "where ",
        "who ",
        "tell me",
        "describe ",
        "explain ",
        "walk me",
        "could you",
        "can you",
        "would you",
        "hire you",
        "choose you",
        "your experience",
    )
    if any(n in low for n in needles):
        return True
    return len(t) >= 96




def ensure_index() -> BM25Index:
    global _index, _kb_root
    root = kb_path()
    with _index_lock:
        if _index is not None and _kb_root == root:
            return _index
        corpus = load_corpus(root)
        if not corpus:
            corpus = [
                (
                    "(empty knowledge base)",
                    "Add .md or .txt files under your KB folder, then click Reindex.",
                )
            ]
        _index = BM25Index.build(corpus)
        _kb_root = root
        return _index


def upload_suffix(file_storage) -> str:
    fn = (secure_filename(file_storage.filename or "") or "").lower()
    for ext in (".webm", ".mp4", ".m4a", ".wav", ".ogg", ".oga"):
        if fn.endswith(ext):
            return ext
    ct = (file_storage.mimetype or "").lower()
    if "webm" in ct:
        return ".webm"
    if "mp4" in ct or "m4a" in ct or "mp4a" in ct:
        return ".mp4"
    if "wav" in ct:
        return ".wav"
    return ".webm"


@app.route("/")
def home():
    html = render_template(
        "index.html",
        kb_root=str(kb_path()),
        whisper_model=os.environ.get("WHISPER_MODEL", "base"),
        llm_uses_cloud=False,
        llm_backend="channelry",
        quick_llm_label="Channelry AI",
        research_llm_label="Channelry AI",
    )
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


def _invalidate_index() -> None:
    global _index, _kb_root
    with _index_lock:
        _index = None
        _kb_root = None


@app.post("/api/reindex")
def api_reindex():
    _invalidate_index()
    idx = ensure_index()
    return jsonify({"ok": True, "chunks": len(idx.chunks), "kb_root": str(kb_path())})


@app.get("/api/kb/files")
def api_kb_files():
    files = kb_list_files(kb_path())
    return jsonify({"kb_root": str(kb_path()), "files": files})


@app.post("/api/kb/upload")
def api_kb_upload():
    if "files" not in request.files:
        return jsonify({"error": "files field required"}), 400
    items = request.files.getlist("files")
    if not items:
        return jsonify({"error": "no files in upload"}), 400

    saved: list[dict] = []
    errors: list[dict] = []
    for f in items:
        if not f or f.filename == "":
            continue
        try:
            info = kb_save_upload(kb_path(), f)
            saved.append(info)
        except RuntimeError as e:
            errors.append({"name": f.filename, "error": str(e)})
        except OSError as e:
            errors.append({"name": f.filename, "error": str(e)})

    if saved:
        _invalidate_index()
        idx = ensure_index()
        chunks = len(idx.chunks)
    else:
        chunks = None

    status = 200 if saved else 400
    return jsonify(
        {
            "ok": bool(saved),
            "saved": saved,
            "errors": errors,
            "chunks": chunks,
        }
    ), status


def _run_open(args: list[str], timeout: float = 20.0) -> bool:
    try:
        r = subprocess.run(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False



@app.get("/api/kb/content")
def api_kb_content():
    """Return the extracted text content of a KB file (companion .txt for PDF/DOCX, or the file itself for txt/md)."""
    name = (request.args.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    kb_root = kb_path()
    # Prevent path traversal
    safe = kb_safe_name(name)
    target = (kb_root / safe).resolve()
    if not str(target).startswith(str(kb_root.resolve())):
        return jsonify({"error": "file not found"}), 404

    # For PDF/DOCX, prefer the companion extracted .txt file
    ext = target.suffix.lower()
    if ext in (".pdf", ".docx"):
        companion = target.with_suffix(target.suffix + ".txt")
        if companion.is_file():
            target = companion
            safe = companion.name

    if not target.is_file():
        return jsonify({"error": "file not found"}), 404
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"name": safe, "text": text, "chars": len(text)})


@app.post("/api/kb/delete")
def api_kb_delete():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    ok = kb_delete_file(kb_path(), name)
    if not ok:
        return jsonify({"error": "file not found"}), 404
    _invalidate_index()
    idx = ensure_index()
    return jsonify({"ok": True, "chunks": len(idx.chunks)})


@app.post("/api/assist")
def api_assist():
    data = request.get_json(force=True, silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question is required"}), 400

    idx = ensure_index()
    out = run_assist(
        idx,
        question=question,
        mode=str(data.get("mode") or "interview"),
        session_brief=str(data.get("session_brief") or ""),
        top_k=int(data.get("top_k") or 6),
        want_spoken=bool(data.get("spoken", True)),
        allow_general_knowledge=bool(data.get("allow_general", True)),
        prev_question=str(data.get("prev_question") or "").strip() or None,
        prev_reply=str(data.get("prev_reply") or "").strip() or None,
        llm_source=normalize_llm_source(data.get("llm_source")),
        channelry_base_url=str(data.get("channelry_base_url") or "").strip() or None,
        channelry_api_key=str(data.get("channelry_api_key") or "").strip() or None,
        channelry_external_user_id=str(data.get("channelry_external_user_id") or "").strip() or None,
        strict_kb=bool(data.get("strict_kb", True)),
    )
    if out.get("error"):
        return jsonify({"error": out["error"]}), int(out.get("http_status") or 400)
    out["best"] = best_kb_snippet(question, out.get("hits") or [])
    return jsonify(out)


@app.post("/api/channelry/test")
def api_channelry_test():
    """Test Channelry AI connectivity via the external AI chat relay."""
    data = request.get_json(force=True, silent=True) or {}
    base = (data.get("base_url") or os.environ.get("CHANNELRY_AI_BASE_URL") or "https://channelry-admin.olowolabiakinwale.workers.dev").rstrip("/")
    key = (data.get("api_key") or os.environ.get("CHANNELRY_AI_API_KEY") or "").strip()
    ext_user = (data.get("external_user_id") or os.environ.get("CHANNELRY_AI_EXTERNAL_USER_ID") or "interview-copilot-user").strip()
    if not key:
        return jsonify({"ok": False, "error": "CHANNELRY_AI_API_KEY is not set (in .env or request)."}), 400
    try:
        from assist_core import channelry_chat_complete
        text = channelry_chat_complete(
            base,
            key,
            "You are a connectivity test. Reply only with the requested token.",
            "Ping. Reply with exactly: CHANNELRY_OK",
            external_user_id=ext_user,
            timeout_s=20.0,
            temperature=0.0,
            max_tokens=16,
        )
        ok = "CHANNELRY_OK" in (text or "")
        return jsonify({"ok": ok, "base": base, "external_user_id": ext_user, "reply": text[:200] if text else ""})
    except Exception as e:
        return jsonify({"ok": False, "base": base, "external_user_id": ext_user, "error": str(e)}), 502


@app.post("/api/build_profile")
def api_build_profile():
    """Build a concise profile summary from CV + role description + KB hits using Channelry AI."""
    data = request.get_json(silent=True) or {}
    cv_text = str(data.get("cv_text") or "").strip()
    role_description = str(data.get("role_description") or "").strip()
    kb_name = str(data.get("kb_name") or "").strip()
    channelry_base_url = str(data.get("channelry_base_url") or "").strip() or None
    channelry_api_key = str(data.get("channelry_api_key") or "").strip() or None
    channelry_external_user_id = str(data.get("channelry_external_user_id") or "").strip() or None

    if not cv_text:
        return jsonify({"error": "cv_text is required", "http_status": 400}), 400

    # Search KB for relevant context if kb_name provided
    kb_hits = []
    if kb_name:
        try:
            idx = ensure_index()
            query = role_description or cv_text[:500]
            hits = idx.search(query, top_k=5)
            kb_hits = hits
        except Exception:
            kb_hits = []

    try:
        summary = build_profile_summary(
            cv_text=cv_text,
            role_description=role_description or None,
            kb_hits=kb_hits,
            base_url=channelry_base_url,
            api_key=channelry_api_key,
            external_user_id=channelry_external_user_id or None,
        )
        return jsonify({
            "summary": summary,
            "summary_len": len(summary),
            "kb_hits_used": len(kb_hits),
        })
    except Exception as e:
        return jsonify({"error": str(e), "http_status": 500}), 500


@app.get("/api/user/profile")
@login_required
def api_user_profile():
    """Fetch the logged-in user's saved profile from the database."""
    user_id = session.get("user")
    profile = _get_user_profile(user_id)
    return jsonify({"ok": True, "profile": profile})


@app.post("/api/user/profile")
@login_required
def api_user_profile_save():
    """Save the logged-in user's profile (CV text, role description, session brief, built summary) to the database."""
    user_id = session.get("user")
    data = request.get_json(silent=True) or {}
    cv_text = str(data.get("cv_text") or "").strip()
    role_description = str(data.get("role_description") or "").strip()
    session_brief = str(data.get("session_brief") or "").strip()
    built_summary = str(data.get("built_summary") or "").strip()
    _save_user_profile(user_id, cv_text=cv_text, role_description=role_description,
                       session_brief=session_brief, built_summary=built_summary)
    return jsonify({"ok": True, "message": "Profile saved"})


@app.post("/api/transcribe")
def api_transcribe():
    if "audio" not in request.files:
        return jsonify({"error": "audio file field required (multipart form key: audio)"}), 400
    up = request.files["audio"]
    if not up or up.filename == "":
        return jsonify({"error": "empty upload"}), 400
    lang = (request.form.get("language") or request.args.get("language") or "").strip() or None
    if lang == "auto":
        lang = None
    suf = upload_suffix(up)
    path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suf, delete=False) as tmp:
            up.save(tmp.name)
            path = tmp.name
        text, meta = transcribe_path(path, language=lang)
    except (RuntimeError, OSError, FileNotFoundError) as e:
        return jsonify({"error": str(e)}), 503
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass
    return jsonify({"text": text, "meta": meta})


@app.post("/api/listen_assist")
def api_listen_assist():
    if "audio" not in request.files:
        return jsonify({"error": "audio file required"}), 400
    up = request.files["audio"]
    if not up or up.filename == "":
        return jsonify({"error": "empty upload"}), 400

    lang = (request.form.get("language") or "").strip() or None
    if lang == "auto":
        lang = None
    mode = request.form.get("mode") or "interview"
    session_brief = request.form.get("session_brief") or ""
    top_k = int(request.form.get("top_k") or 6)
    spoken = request.form.get("spoken", "1") not in ("0", "false", "no")
    allow_general = request.form.get("allow_general", "1") not in ("0", "false", "no")
    strict_kb = request.form.get("strict_kb", "1") not in ("0", "false", "no")

    suf = upload_suffix(up)
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suf, delete=False) as tmp:
            up.save(tmp.name)
            path = tmp.name
        try:
            transcript, meta = transcribe_path(path, language=lang)
        except (RuntimeError, OSError, FileNotFoundError) as e:
            return jsonify({"error": str(e), "transcript": ""}), 503
    finally:
        if path:
            try:
                os.unlink(path)
            except Exception:
                pass

    if not (transcript or "").strip():
        return jsonify(
            {
                "error": "Transcription was empty — speak closer to the mic or check levels.",
                "transcript": "",
                "meta": meta,
            }
        ), 400

    idx = ensure_index()
    prev_q = (request.form.get("prev_question") or "").strip() or None
    prev_a = (request.form.get("prev_reply") or "").strip() or None
    out = run_assist(
        idx,
        question=transcript,
        mode=str(mode),
        session_brief=str(session_brief),
        top_k=top_k,
        want_spoken=spoken,
        allow_general_knowledge=allow_general,
        prev_question=prev_q,
        prev_reply=prev_a,
        llm_source=normalize_llm_source(request.form.get("llm_source")),
        cloud_quick_model=(request.form.get("cloud_quick_model") or "").strip() or None,
        strict_kb=strict_kb,
    )
    out["transcript"] = transcript
    out["meta"] = meta
    out["best"] = best_kb_snippet(transcript, out.get("hits") or [])
    return jsonify(out)


def _sse(name: str, payload) -> bytes:
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


@app.post("/api/listen_assist_stream")
def api_listen_assist_stream():
    if "audio" not in request.files:
        return jsonify({"error": "audio file required"}), 400
    up = request.files["audio"]
    if not up or up.filename == "":
        return jsonify({"error": "empty upload"}), 400

    lang = (request.form.get("language") or "").strip() or None
    if lang == "auto":
        lang = None
    mode = request.form.get("mode") or "interview"
    session_brief = request.form.get("session_brief") or ""
    top_k = int(request.form.get("top_k") or 6)
    spoken = request.form.get("spoken", "1") not in ("0", "false", "no")
    allow_general = request.form.get("allow_general", "1") not in ("0", "false", "no")
    strict_kb = request.form.get("strict_kb", "1") not in ("0", "false", "no")
    prev_q = (request.form.get("prev_question") or "").strip() or None
    prev_a = (request.form.get("prev_reply") or "").strip() or None
    llm_src = normalize_llm_source(request.form.get("llm_source"))
    cloud_quick_override = (request.form.get("cloud_quick_model") or "").strip() or None
    channelry_external_user_id = (request.form.get("channelry_external_user_id") or "").strip() or None
    question_gate_flag = request.form.get("question_gate") == "1"
    research_first_flag = request.form.get("research_first") == "1"
    force_openai_flag = request.form.get("use_openai_answers") == "1"
    cloud_research_override = (request.form.get("cloud_research_model") or "").strip() or None

    suf = upload_suffix(up)
    with tempfile.NamedTemporaryFile(suffix=suf, delete=False) as tmp:
        up.save(tmp.name)
        audio_path = tmp.name

    def stream():
        try:
            yield _sse("stage", {"name": "transcribing"})
            try:
                transcript, meta = transcribe_path(audio_path, language=lang)
            except Exception as e:
                yield _sse("warning", {"message": str(e)})
                yield _sse("transcript", {"text": "", "meta": {}})
                yield _sse("done", {})
                return

            transcript_text = (transcript or "").strip()
            idx = ensure_index()
            hits = idx.search(transcript_text, top_k=top_k) if transcript_text else []
            weak, top_score = kb_is_weak(hits)
            allow_general_eff = allow_general

            best = best_kb_snippet(transcript_text, hits)

            yield _sse("transcript", {"text": transcript_text, "meta": meta})
            yield _sse(
                "context",
                {
                    "hits": hits,
                    "kb_weak": weak,
                    "top_kb_score": top_score,
                    "allow_general_effective": allow_general_eff,
                },
            )
            if best:
                yield _sse("best", best)
            if not transcript_text:
                yield _sse("warning", {"message": "Transcription was empty — try again, closer to the mic."})
                yield _sse("done", {})
                return

            if question_gate_flag and not is_interviewer_question(transcript_text):
                yield _sse(
                    "info",
                    {"message": "Clip does not look like a question — skipped LLM (token saved)."},
                )
                yield _sse("done", {})
                return

            # ── Delegate to run_assist() — identical logic to /api/assist text path ──
            result = run_assist(
                idx,
                question=transcript_text,
                mode=str(mode),
                session_brief=str(session_brief),
                top_k=top_k,
                want_spoken=spoken,
                allow_general_knowledge=allow_general_eff,
                kb_weak_threshold=None,
                prev_question=prev_q,
                prev_reply=prev_a,
                llm_source=llm_src,
                strict_kb=strict_kb,
                force_openai_answers=force_openai_flag,
                channelry_base_url=(request.form.get("channelry_base_url") or "").strip() or None,
                channelry_api_key=(request.form.get("channelry_api_key") or "").strip() or None,
                channelry_external_user_id=channelry_external_user_id,
                temperature=0.6,
                max_tokens=1000,
            )

            suggestion = result.get("suggestion", "") or ""
            warn = result.get("warning", "") or ""

            yield _sse("stage", {"name": "llm", "provider": "channelry"})

            # Stream the suggestion as tokens via SSE
            emitted_any = False
            if suggestion:
                chunk_size = 40
                for i in range(0, len(suggestion), chunk_size):
                    chunk = suggestion[i : i + chunk_size]
                    emitted_any = True
                    yield _sse("token", {"text": chunk})
            else:
                fb = kb_fallback_reply(
                    hits,
                    best,
                    want_spoken=spoken,
                    question=transcript_text,
                    use_cloud_llm=False,
                    emit_verbatim_kb_excerpt=(best is None),
                )
                yield _sse("token", {"text": fb})
                emitted_any = True

            if warn:
                yield _sse("warning", {"message": warn})

            if not emitted_any:
                fb = kb_fallback_reply(
                    hits,
                    best,
                    want_spoken=spoken,
                    question=transcript_text,
                    use_cloud_llm=False,
                    emit_verbatim_kb_excerpt=(best is None),
                )
                yield _sse("token", {"text": fb})
                yield _sse(
                    "warning",
                    {
                        "message": "No LLM answer received. A KB-only draft is shown above.",
                    },
                )
            return

            if research_first_flag:
                hits_prompt = trim_hits_for_prompt(
                    hits,
                    total_budget=int(os.environ.get("RESEARCH_CONTEXT_CHARS", "12000")),
                    per_hit_max=int(os.environ.get("RESEARCH_CONTEXT_PER_HIT", "4000")),
                )
                system = build_research_system_prompt(mode, allow_general_knowledge=allow_general_eff, strict_kb=strict_kb)
                # ── Truncate session_brief for Channelry's tight TPM limit ──
                brief_research = (session_brief or "").strip()
                if len(brief_research) > 2000:
                    brief_research = brief_research[:2000].rstrip() + " …"
                user_prompt = build_research_user_prompt(
                    mode,
                    transcript_text,
                    brief_research,
                    hits_prompt,
                    kb_weak=weak,
                    top_kb_score=top_score,
                    quick_reply=None,
                    strict_kb=strict_kb,
                )
            else:
                # ── Truncate session_brief for Channelry's tight TPM limit ──
                brief = (session_brief or "").strip()
                if len(brief) > 700:
                    brief = brief[:700].rstrip() + " …"
                system = build_system_prompt(mode, allow_general_knowledge=allow_general_eff, strict_kb=strict_kb)
                hits_prompt = trim_hits_for_prompt(
                    hits,
                    total_budget=int(os.environ.get("QUICK_CONTEXT_CHARS", "700")),
                    per_hit_max=int(os.environ.get("QUICK_CONTEXT_PER_HIT", "350")),
                )
                user_prompt = build_user_prompt(
                    mode,
                    transcript_text,
                    brief,
                    hits_prompt,
                    spoken,
                    kb_weak=weak,
                    top_kb_score=top_score,
                    prev_question=prev_q,
                    prev_reply=prev_a,
                    strict_kb=strict_kb,
                )

            channelry_llm = use_channelry_for_llm_source(llm_src)
            cloud_llm = (not channelry_llm) and use_openai_direct
            print(f"[DEBUG listen] llm_src={llm_src!r} channelry_llm={channelry_llm} cloud_llm={cloud_llm}", flush=True)
            print(f"[DEBUG listen] session_brief len={len(session_brief or '')}", flush=True)
            yield _sse(
                "stage",
                {"name": "llm", "provider": "channelry" if channelry_llm else ("cloud" if cloud_llm else "channelry")},
            )

            emitted_any = False
            text_emitted = False
            if channelry_llm:
                cbase, ckey = channelry_chat_params(
                    override_base=(request.form.get("channelry_base_url") or "").strip() or None,
                    override_key=(request.form.get("channelry_api_key") or "").strip() or None,
                )
                if not ckey:
                    fb = kb_fallback_reply(
                        hits,
                        best,
                        want_spoken=spoken,
                        question=transcript_text,
                        use_cloud_llm=True,
                        emit_verbatim_kb_excerpt=(best is None),
                    )
                    yield _sse(
                        "warning",
                        {
                            "message": "Channelry AI selected but CHANNELRY_AI_API_KEY is not set in .env.",
                        },
                    )
                    yield _sse("token", {"text": fb})
                    emitted_any = True
                else:
                    try:
                        content = channelry_chat_complete(
                            cbase,
                            ckey,
                            system,
                            user_prompt,
                            external_user_id=channelry_external_user_id or _channelry_default_external_user_id(),
                            timeout_s=120.0,
                            temperature=0.6,
                            max_tokens=1000,
                        )
                        print(f"[DEBUG listen] channelry_chat_complete returned len={len(content or '')} content_preview={str(content or '')[:100]!r}", flush=True)
                        if content and "## Lines to say" in content:
                            idx = content.index("## Lines to say")
                            tail = content[idx:]
                            for marker in ["## Gaps", "## Deep angles", "## Verify"]:
                                cut = tail.find(marker, len("## Lines to say"))
                                if cut != -1:
                                    tail = tail[:cut]
                            content = tail.strip()
                        emitted_any = True
                        text_emitted = bool(content)
                        if content:
                            yield _sse("token", {"text": content})
                    except Exception as e:
                        yield _sse("warning", {"message": str(e)})
            elif cloud_llm:
                api_key = openai_native_key() if use_openai_direct else openai_compat_key()
                api_base = openai_native_base() if use_openai_direct else openai_compat_base()
                if not api_key:
                    fb = kb_fallback_reply(
                        hits,
                        best,
                        want_spoken=spoken,
                        question=transcript_text,
                        use_cloud_llm=True,
                        emit_verbatim_kb_excerpt=(best is None),
                    )
                    yield _sse(
                        "warning",
                        {
                            "message": (
                                "Cloud / OpenAI LLM selected but no API key is set in .env "
                                "(OPENAI_API_KEY for OpenAI answers, or OPENAI_COMPAT_API_KEY / GROQ_API_KEY for Groq)."
                            ),
                        },
                    )
                    yield _sse("token", {"text": fb})
                    emitted_any = True
                else:
                    if research_first_flag:
                        mid = (
                            openai_answer_model_research(cloud_quick_override, cloud_research_override)
                            if use_openai_direct
                            else resolve_cloud_research_model(cloud_research_override)
                        )
                        max_tok = 1000
                        temp = rtemp
                        to = 180.0
                    else:
                        mid = (
                            openai_answer_model_quick(cloud_quick_override)
                            if use_openai_direct
                            else resolve_cloud_quick_model(cloud_quick_override)
                        )
                        max_tok = 1000
                        temp = 0.6
                        to = 120.0
                    try:
                        for chunk in openai_chat_stream(
                            api_base,
                            api_key,
                            mid,
                            user_prompt,
                            system=system,
                            timeout_s=to,
                            temperature=temp,
                            max_tokens=max_tok,
                        ):
                            emitted_any = True
                            yield _sse("token", {"text": chunk})
                    except Exception as e:
                        yield _sse("warning", {"message": str(e)})
            if not emitted_any or not text_emitted:
                fb = kb_fallback_reply(
                    hits,
                    best,
                    want_spoken=spoken,
                    question=transcript_text,
                    use_cloud_llm=cloud_llm,
                    emit_verbatim_kb_excerpt=(best is None),
                )
                yield _sse("token", {"text": fb})
                if cloud_llm:
                    if use_openai_direct and not openai_native_key():
                        msg = (
                            "OpenAI answers need OPENAI_API_KEY in .env — a KB-only draft is shown above."
                        )
                    elif not openai_compat_key() and not use_openai_direct:
                        msg = (
                            "Cloud LLM is configured but no API key is set — a KB-only draft is shown above. "
                            "Add OPENAI_COMPAT_API_KEY (or GROQ_API_KEY) to .env and restart."
                        )
                    else:
                        msg = (
                            "The cloud LLM returned no text (empty stream or error). "
                            "Check base URL, model name, quota, and network. "
                            "A KB-only draft is shown above."
                        )
                else:
                    msg = (
                        "No LLM answer received. A KB-only draft is shown above."
                    )
                yield _sse("warning", {"message": msg})
            yield _sse("done", {})
        except Exception as e:
            yield _sse(
                "warning",
                {"message": f"{type(e).__name__}: {e}. If this repeats, check the terminal where Flask runs."},
            )
            yield _sse("done", {})
        finally:
            try:
                os.unlink(audio_path)
            except OSError:
                pass

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return app.response_class(stream_with_context(stream()), headers=headers)


@app.post("/api/research_stream")
def api_research_stream():
    data = request.get_json(force=True, silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question is required"}), 400
    llm_src = normalize_llm_source(data.get("llm_source"))
    cq = (data.get("cloud_quick_model") or "").strip() or None
    cr = (data.get("cloud_research_model") or "").strip() or None

    mode = str(data.get("mode") or "interview")
    session_brief = str(data.get("session_brief") or "")
    allow_general = bool(data.get("allow_general", True))
    strict_kb = bool(data.get("strict_kb", True))
    quick_reply = (data.get("quick_reply") or "").strip() or None
    force_openai = bool(data.get("use_openai_answers"))
    use_openai_direct = bool(force_openai and openai_native_key())
    try:
        top_k = int(data.get("top_k") or os.environ.get("RESEARCH_TOP_K", "10"))
    except ValueError:
        top_k = 10

    idx = ensure_index()
    hits = idx.search(question, top_k=max(4, top_k))
    weak, top_score = kb_is_weak(hits)
    hits_prompt = trim_hits_for_prompt(
        hits,
        total_budget=int(os.environ.get("RESEARCH_CONTEXT_CHARS", "12000")),
        per_hit_max=int(os.environ.get("RESEARCH_CONTEXT_PER_HIT", "4000")),
    )
    system = build_research_system_prompt(mode, allow_general_knowledge=allow_general, strict_kb=strict_kb)
    user = build_research_user_prompt(
        mode,
        question,
        session_brief,
        hits_prompt,
        kb_weak=weak,
        top_kb_score=top_score,
        quick_reply=quick_reply,
        strict_kb=strict_kb,
    )

    try:
        rtemp = float(os.environ.get("OPENAI_COMPAT_RESEARCH_TEMP", "0.42"))
    except ValueError:
        rtemp = 0.42

    def gen():
        try:
            if force_openai and not use_openai_direct:
                yield _sse(
                    "warning",
                    {"message": "OpenAI answers requested but OPENAI_API_KEY is missing in .env — using your normal LLM path."},
                )
            if use_channelry_for_llm_source(llm_src) or use_openai_direct:
                key = openai_native_key() if use_openai_direct else openai_compat_key()
                base_u = openai_native_base() if use_openai_direct else openai_compat_base()
                if not key:
                    yield _sse("warning", {"message": "Cloud LLM enabled but API key missing (set OPENAI_API_KEY or OPENAI_COMPAT_API_KEY)."})
                else:
                    rm = (
                        openai_answer_model_research(cq, cr)
                        if use_openai_direct
                        else resolve_cloud_research_model(cr or cq)
                    )
                    for chunk in openai_chat_stream(
                        base_u,
                        key,
                        rm,
                        user,
                        system=system,
                        timeout_s=180.0,
                        temperature=rtemp,
                        max_tokens=1000,
                    ):
                        yield _sse("token", {"text": chunk})
        except Exception as e:
            yield _sse("warning", {"message": str(e)})
        yield _sse("done", {})

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return app.response_class(gen(), headers=headers)


def main():
    ensure_index()
    port = int(os.environ.get("PORT", "5055"))

    if os.environ.get("WARMUP", "1") not in ("0", "false", "no"):
        threading.Thread(target=whisper_warmup, daemon=True).start()

    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
