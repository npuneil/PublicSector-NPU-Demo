"""
Public Sector Hybrid AI Demo
=============================
A Flask application demonstrating hybrid on-device + cloud AI for
public sector use cases. Intel NPU optimized via Foundry Local,
with optional Azure OpenAI for cloud inference.

Runtime decisioning routes requests to local or cloud based on:
PII detection, content sensitivity, connectivity, cost, and module policy.

Tabs:
  1. Home                    – Overview of hybrid AI for public sector
  2. Counter Service Copilot – Citizen inquiry handling (front desk / call center)
  3. Policy & Ordinance      – Document analysis, clause extraction
  4. Disaster Response       – Offline situation briefs, incident logs
  5. Permit / Inspection     – Structured field extraction, summaries
  6. Hybrid Dashboard        – Routing decisions, cost savings, PII interceptions
"""

import os
import sys
import io
import re
import json
import time
import uuid
import sqlite3
import subprocess
import traceback
import tempfile
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify

# ---------------------------------------------------------------------------
# Optional: PDF text extraction
# ---------------------------------------------------------------------------
try:
    from PyPDF2 import PdfReader
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    print("[STARTUP] PyPDF2 not installed — PDF upload disabled (text paste still works)")

# ---------------------------------------------------------------------------
# Optional: On-device speech-to-text via faster-whisper
# ---------------------------------------------------------------------------
whisper_model = None
WHISPER_SUPPORT = False
try:
    from faster_whisper import WhisperModel
    print("[STARTUP] Loading Whisper model for on-device dictation...")
    whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
    WHISPER_SUPPORT = True
    print("[STARTUP] Whisper model loaded — on-device dictation ready")
except ImportError:
    print("[STARTUP] faster-whisper not installed — dictation disabled")
except Exception as exc:
    print(f"[STARTUP] Whisper model load failed: {exc}")

# ---------------------------------------------------------------------------
# Optional: Azure OpenAI cloud integration
# ---------------------------------------------------------------------------
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_KEY = os.environ.get("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
CLOUD_AVAILABLE = bool(AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY and AZURE_OPENAI_DEPLOYMENT)

openai_client = None
if CLOUD_AVAILABLE:
    try:
        from openai import AzureOpenAI
        openai_client = AzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_KEY,
            api_version="2024-06-01",
        )
        print(f"[STARTUP] Azure OpenAI configured: {AZURE_OPENAI_ENDPOINT}")
    except Exception as exc:
        print(f"[STARTUP] Azure OpenAI init failed: {exc}")
        CLOUD_AVAILABLE = False

# ---------------------------------------------------------------------------
# Silicon detection — Intel-aware
# ---------------------------------------------------------------------------
SILICON = "unknown"


def _detect_silicon() -> str:
    global SILICON
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Processor).Name"],
            capture_output=True, text=True, timeout=5,
        )
        cpu = result.stdout.strip().lower()
        if "intel" in cpu:
            SILICON = "intel"
        elif "qualcomm" in cpu or "snapdragon" in cpu:
            SILICON = "qualcomm"
        elif "amd" in cpu:
            SILICON = "amd"
        else:
            SILICON = "unknown"
    except Exception:
        SILICON = "unknown"
    return SILICON


_detect_silicon()
print(f"[STARTUP] Silicon detected: {SILICON}")

# ---------------------------------------------------------------------------
# Foundry Local bootstrap — Intel NPU preferred
# ---------------------------------------------------------------------------
foundry_ok = False
model_id = None
foundry_service_url = None
npu_alias = None
use_npu = False

# Intel NPU: phi-4-mini is the most powerful small model for Intel Core Ultra
NPU_ALIAS_PREFERENCE = [
    "phi-4-mini",
    "phi-3.5-mini",
    "phi-3-mini-4k",
    "qwen2.5-1.5b",
    "qwen2.5-7b",
]

CPU_MODEL_PREFERENCE = [
    "Phi-4-mini-instruct-generic-cpu",
    "Phi-3.5-mini-instruct-generic-cpu",
    "qwen2.5-0.5b-instruct-generic-cpu",
]


def _discover_foundry_port() -> str | None:
    try:
        result = subprocess.run(
            ["foundry", "service", "status"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            if "http://" in line:
                m = re.search(r"(https?://[\d.]+:\d+)", line)
                if m:
                    return m.group(1)
    except Exception as exc:
        print(f"[STARTUP] foundry CLI not available: {exc}")
    return None


def _detect_npu_alias() -> str | None:
    try:
        result = subprocess.run(
            ["foundry", "model", "list"],
            capture_output=True, text=True, timeout=15,
        )
        npu_aliases = set()
        current_alias = None
        for line in result.stdout.splitlines():
            parts = line.split()
            if not parts:
                continue
            if parts[0] in ("CPU", "NPU", "GPU", "Auto"):
                if parts[0] == "NPU" and current_alias:
                    npu_aliases.add(current_alias)
            elif not parts[0].startswith("-") and not parts[0].startswith("Alias"):
                current_alias = parts[0]
                if len(parts) > 1 and parts[1] == "NPU":
                    npu_aliases.add(current_alias)

        for pref in NPU_ALIAS_PREFERENCE:
            if pref in npu_aliases:
                return pref
        return next(iter(npu_aliases), None)
    except Exception as exc:
        print(f"[STARTUP] Could not detect NPU models: {exc}")
        return None


def _foundry_get(path: str, timeout: int = 10):
    try:
        resp = urllib.request.urlopen(f"{foundry_service_url}{path}", timeout=timeout)
        return json.loads(resp.read())
    except Exception:
        return None


def _foundry_post(path: str, body: dict, timeout: int = 120):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{foundry_service_url}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read())


def init_foundry():
    global foundry_ok, model_id, foundry_service_url, npu_alias, use_npu

    foundry_ok = False
    model_id = None
    foundry_service_url = None
    npu_alias = None
    use_npu = False

    service_url = _discover_foundry_port()
    if not service_url:
        try:
            subprocess.run(["foundry", "service", "start"],
                           capture_output=True, text=True, timeout=30)
            service_url = _discover_foundry_port()
        except Exception:
            pass

    if not service_url:
        print("[STARTUP] Foundry Local service not running. UI-preview mode.")
        return

    foundry_service_url = service_url
    print(f"[STARTUP] Foundry Local HTTP service at {service_url}")

    # Check for NPU model already loaded
    models_data = _foundry_get("/v1/models")
    if models_data and "data" in models_data:
        available_ids = [m["id"] for m in models_data["data"]]
        print(f"[STARTUP] Available HTTP models: {available_ids}")
        npu_ids = [mid for mid in available_ids
                   if "npu" in mid.lower() or "qnn" in mid.lower()
                   or "directml" in mid.lower()]

        for pref in NPU_ALIAS_PREFERENCE:
            pref_clean = pref.replace("-", "")
            for mid in npu_ids:
                if pref_clean in mid.replace("-", "").lower():
                    model_id = mid
                    npu_alias = pref
                    break
            if model_id:
                break

        if model_id:
            use_npu = True
            foundry_ok = True
            print(f"[STARTUP] NPU model already in service: {model_id}")
            return

    # Try to pre-load an NPU model
    detected = _detect_npu_alias()
    if detected:
        print(f"[STARTUP] Pre-loading NPU model '{detected}' ...")
        try:
            result = subprocess.run(
                ["foundry", "model", "load", detected, "--device", "NPU"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                time.sleep(2)
                models_data = _foundry_get("/v1/models")
                if models_data and "data" in models_data:
                    npu_ids = [m["id"] for m in models_data["data"]
                               if "npu" in m["id"].lower() or "qnn" in m["id"].lower()
                               or "directml" in m["id"].lower()]
                    best = None
                    for mid in npu_ids:
                        if detected.replace("-", "") in mid.replace("-", "").lower():
                            best = mid
                            break
                    if not best and npu_ids:
                        best = npu_ids[0]
                    if best:
                        model_id = best
                        npu_alias = detected
                        use_npu = True
                        foundry_ok = True
                        print(f"[STARTUP] NPU model ready: {model_id}")
                        return
            else:
                print(f"[STARTUP] NPU load failed: {result.stderr[:200]}")
        except subprocess.TimeoutExpired:
            print("[STARTUP] NPU load timed out (120s)")
        except Exception as exc:
            print(f"[STARTUP] NPU load error: {exc}")

    # Fall back to CPU
    models_data = _foundry_get("/v1/models")
    if not models_data or "data" not in models_data:
        print("[STARTUP] Could not list models. UI-preview mode.")
        foundry_service_url = None
        return

    available_ids = [m["id"] for m in models_data["data"]]
    for pref in CPU_MODEL_PREFERENCE:
        pref_lower = pref.lower()
        for mid in available_ids:
            if mid.lower().startswith(pref_lower):
                model_id = mid
                break
        if model_id:
            break

    if not model_id and available_ids:
        cpu_models = [m for m in available_ids if "cpu" in m.lower()]
        model_id = cpu_models[0] if cpu_models else available_ids[0]

    if not model_id:
        print("[STARTUP] No models available. UI-preview mode.")
        foundry_service_url = None
        return

    foundry_ok = True
    print(f"[STARTUP] Selected CPU model: {model_id}")


init_foundry()

# Intel: safe to warmup
if foundry_ok and SILICON != "qualcomm":
    try:
        print("[STARTUP] Warming up model ...")
        _foundry_post("/v1/chat/completions", {
            "model": model_id,
            "messages": [{"role": "user", "content": "Reply OK."}],
            "max_tokens": 8,
        }, timeout=60)
        print("[STARTUP] Warmup complete.")
    except Exception as exc:
        print(f"[STARTUP] Warmup skipped: {exc}")
elif SILICON == "qualcomm":
    print("[STARTUP] Snapdragon detected — skipping warmup")

# ---------------------------------------------------------------------------
# PII Detection Engine — regex first-pass, fail-closed
# ---------------------------------------------------------------------------
PII_PATTERNS = {
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "phone": re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "dob": re.compile(r"\b(?:0[1-9]|1[0-2])[/-](?:0[1-9]|[12]\d|3[01])[/-](?:19|20)\d{2}\b"),
    "address": re.compile(
        r"\b\d{1,5}\s+(?:[NSEW]\.?\s+)?(?:[A-Z][a-z]+\s+){1,3}"
        r"(?:St(?:reet)?|Ave(?:nue)?|Blvd|Dr(?:ive)?|Rd|Ln|Ct|Pl|Way|Cir)\b",
        re.IGNORECASE,
    ),
    "case_number": re.compile(r"\b(?:CASE|Case|case)[-#\s]?\d{4,}\b"),
    "license_plate": re.compile(r"\b[A-Z]{2,3}[-\s]?\d{3,4}[-\s]?[A-Z]{0,3}\b"),
    "dl_number": re.compile(r"\b(?:DL|D\.L\.|License)[-#:\s]?[A-Z]?\d{6,12}\b", re.IGNORECASE),
}


def detect_pii(text: str) -> dict:
    """Detect PII in text. Returns dict of {type: count} for detected PII types."""
    found = {}
    for pii_type, pattern in PII_PATTERNS.items():
        matches = pattern.findall(text)
        if matches:
            found[pii_type] = len(matches)
    return found


# ---------------------------------------------------------------------------
# Runtime Routing Decisioning
# ---------------------------------------------------------------------------
# Per-module routing policies
MODULE_POLICIES = {
    "counter_service": {
        "cloud_eligible": True,
        "sensitivity": "high",        # citizen PII likely
        "latency_priority": "medium",
        "description": "Cloud allowed only after PII-safe check",
    },
    "policy_analyzer": {
        "cloud_eligible": True,
        "sensitivity": "high",         # internal notes may be sensitive
        "latency_priority": "low",
        "description": "Local-first; cloud for cross-corpus analysis after sanitization",
    },
    "disaster_response": {
        "cloud_eligible": False,       # local-only unless explicit sync
        "sensitivity": "critical",
        "latency_priority": "high",
        "description": "Local-only; sync queue when connectivity returns",
    },
    "permit_inspection": {
        "cloud_eligible": True,
        "sensitivity": "medium",
        "latency_priority": "medium",
        "description": "Local-first for notes/extraction; cloud for analytics",
    },
}

# Routing reason codes
ROUTE_LOCAL_PII = "PII_DETECTED"
ROUTE_LOCAL_SENSITIVE = "MARKED_SENSITIVE"
ROUTE_LOCAL_POLICY = "MODULE_POLICY_LOCAL_ONLY"
ROUTE_LOCAL_OFFLINE = "CLOUD_UNAVAILABLE"
ROUTE_LOCAL_FAIL_SAFE = "FAIL_SAFE_UNCERTAIN"
ROUTE_LOCAL_LARGE_INPUT = "INPUT_TOO_LARGE_FOR_CLOUD"
ROUTE_LOCAL_USER_OVERRIDE = "USER_FORCED_LOCAL"
ROUTE_CLOUD_ELIGIBLE = "CLOUD_ELIGIBLE_NO_PII"
ROUTE_LOCAL_DEFAULT = "DEFAULT_LOCAL"


def decide_routing(
    text: str,
    module: str,
    force_local: bool = False,
    marked_sensitive: bool = False,
) -> dict:
    """
    Decide whether to route a request to local (on-device) or cloud.
    Returns: {"route": "local"|"cloud", "reason": str, "pii_detected": dict}
    All decisions are server-side. Fail-closed: if uncertain, route local.
    """
    pii = detect_pii(text)

    # User forced local
    if force_local:
        return {"route": "local", "reason": ROUTE_LOCAL_USER_OVERRIDE, "pii_detected": pii}

    # PII detected → force local
    if pii:
        return {"route": "local", "reason": ROUTE_LOCAL_PII, "pii_detected": pii}

    # Marked sensitive → force local
    if marked_sensitive:
        return {"route": "local", "reason": ROUTE_LOCAL_SENSITIVE, "pii_detected": pii}

    # Module policy: local-only
    policy = MODULE_POLICIES.get(module, {})
    if not policy.get("cloud_eligible", False):
        return {"route": "local", "reason": ROUTE_LOCAL_POLICY, "pii_detected": pii}

    # Cloud not available
    if not CLOUD_AVAILABLE or not openai_client:
        return {"route": "local", "reason": ROUTE_LOCAL_OFFLINE, "pii_detected": pii}

    # Large input: keep local (>3000 chars — avoid expensive cloud tokens)
    if len(text) > 3000:
        return {"route": "local", "reason": ROUTE_LOCAL_LARGE_INPUT, "pii_detected": pii}

    # Cloud eligible
    return {"route": "cloud", "reason": ROUTE_CLOUD_ELIGIBLE, "pii_detected": pii}


# ---------------------------------------------------------------------------
# SQLite Persistence — telemetry, routing log, sync queue
# ---------------------------------------------------------------------------
DB_PATH = Path(__file__).resolve().parent / "telemetry.db"


def _init_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS routing_log (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            module TEXT NOT NULL,
            route TEXT NOT NULL,
            reason TEXT NOT NULL,
            pii_types TEXT,
            tokens INTEGER DEFAULT 0,
            latency_ms INTEGER DEFAULT 0,
            cloud_cost_saved REAL DEFAULT 0.0,
            hardware TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sync_queue (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            module TEXT NOT NULL,
            summary TEXT NOT NULL,
            metadata TEXT,
            synced INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


_init_db()


def log_routing_decision(entry: dict):
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(
            "INSERT INTO routing_log (id, timestamp, module, route, reason, pii_types, tokens, latency_ms, cloud_cost_saved, hardware) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry.get("id", str(uuid.uuid4())[:8]),
                entry.get("timestamp", datetime.now().isoformat()),
                entry.get("module", ""),
                entry.get("route", "local"),
                entry.get("reason", ""),
                json.dumps(entry.get("pii_types", {})),
                entry.get("tokens", 0),
                entry.get("latency_ms", 0),
                entry.get("cloud_cost_saved", 0.0),
                entry.get("hardware", ""),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[DB] Log error: {exc}")


def queue_for_sync(module: str, summary: str, metadata: dict | None = None):
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(
            "INSERT INTO sync_queue (id, timestamp, module, summary, metadata) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4())[:8], datetime.now().isoformat(), module, summary, json.dumps(metadata or {})),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[DB] Sync queue error: {exc}")


def get_dashboard_metrics() -> dict:
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row

        # Totals
        row = conn.execute(
            "SELECT COUNT(*) as total, SUM(tokens) as tokens, SUM(cloud_cost_saved) as cost, "
            "AVG(latency_ms) as avg_latency FROM routing_log"
        ).fetchone()
        total = row["total"] or 0
        total_tokens = row["tokens"] or 0
        total_cost = row["cost"] or 0.0
        avg_latency = round(row["avg_latency"] or 0)

        # By route
        local_count = conn.execute("SELECT COUNT(*) FROM routing_log WHERE route='local'").fetchone()[0]
        cloud_count = conn.execute("SELECT COUNT(*) FROM routing_log WHERE route='cloud'").fetchone()[0]

        # PII interceptions
        pii_count = conn.execute(
            "SELECT COUNT(*) FROM routing_log WHERE reason=?", (ROUTE_LOCAL_PII,)
        ).fetchone()[0]

        # By module
        module_stats = {}
        for row in conn.execute(
            "SELECT module, COUNT(*) as cnt, SUM(tokens) as tok FROM routing_log GROUP BY module"
        ):
            module_stats[row["module"]] = {"count": row["cnt"], "tokens": row["tok"] or 0}

        # By reason
        reason_stats = {}
        for row in conn.execute(
            "SELECT reason, COUNT(*) as cnt FROM routing_log GROUP BY reason"
        ):
            reason_stats[row["reason"]] = row["cnt"]

        # Recent log (last 30)
        recent = []
        for row in conn.execute(
            "SELECT id, timestamp, module, route, reason, pii_types, tokens, latency_ms, "
            "cloud_cost_saved, hardware FROM routing_log ORDER BY timestamp DESC LIMIT 30"
        ):
            recent.append(dict(row))

        # Sync queue
        pending_sync = conn.execute("SELECT COUNT(*) FROM sync_queue WHERE synced=0").fetchone()[0]

        conn.close()
        return {
            "total_inferences": total,
            "total_tokens": total_tokens,
            "total_cloud_cost_saved": f"${total_cost:.4f}",
            "avg_latency_ms": avg_latency,
            "local_count": local_count,
            "cloud_count": cloud_count,
            "pii_interceptions": pii_count,
            "module_stats": module_stats,
            "reason_stats": reason_stats,
            "pending_sync": pending_sync,
            "log": list(reversed(recent)),
        }
    except Exception as exc:
        print(f"[DB] Metrics error: {exc}")
        return {
            "total_inferences": 0, "total_tokens": 0,
            "total_cloud_cost_saved": "$0.0000", "avg_latency_ms": 0,
            "local_count": 0, "cloud_count": 0, "pii_interceptions": 0,
            "module_stats": {}, "reason_stats": {}, "pending_sync": 0, "log": [],
        }


# ---------------------------------------------------------------------------
# Inference helpers
# ---------------------------------------------------------------------------
def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _run_local_inference(system_prompt: str, user_prompt: str, max_tokens: int = 1024) -> dict:
    """Run inference via Foundry Local (on-device NPU or CPU)."""
    if not foundry_ok or not foundry_service_url or not model_id:
        return {
            "text": "[Demo mode — Foundry Local not connected. Install & start Foundry Local to enable on-device AI.]",
            "tokens": 0, "latency_ms": 0, "cloud_cost_saved": 0.0, "hardware": "none",
        }

    body = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
    }

    hardware = "NPU" if use_npu else "CPU"
    t0 = time.perf_counter()
    try:
        result = _foundry_post("/v1/chat/completions", body, timeout=120)
    except Exception:
        try:
            init_foundry()
            result = _foundry_post("/v1/chat/completions", body, timeout=120)
        except Exception as exc2:
            return {
                "text": f"[Error: Could not reach Foundry Local — {exc2}]",
                "tokens": 0, "latency_ms": 0, "cloud_cost_saved": 0.0, "hardware": hardware,
            }

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    text = ""
    choices = result.get("choices", [])
    if choices:
        msg = choices[0].get("message") or choices[0].get("delta") or {}
        text = msg.get("content", "")

    usage = result.get("usage") or {}
    total_tokens = usage.get("total_tokens") or (
        _estimate_tokens(system_prompt + user_prompt) + _estimate_tokens(text)
    )
    est_cost = round(total_tokens * 0.00001, 6)

    return {
        "text": text,
        "tokens": total_tokens,
        "latency_ms": elapsed_ms,
        "cloud_cost_saved": est_cost,
        "hardware": hardware,
    }


def _run_cloud_inference(system_prompt: str, user_prompt: str, max_tokens: int = 1024) -> dict:
    """Run inference via Azure OpenAI (cloud)."""
    if not CLOUD_AVAILABLE or not openai_client:
        return _run_local_inference(system_prompt, user_prompt, max_tokens)

    t0 = time.perf_counter()
    try:
        response = openai_client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
        )
        elapsed_ms = round((time.perf_counter() - t0) * 1000)
        text = response.choices[0].message.content or ""
        total_tokens = response.usage.total_tokens if response.usage else _estimate_tokens(text)
        return {
            "text": text,
            "tokens": total_tokens,
            "latency_ms": elapsed_ms,
            "cloud_cost_saved": 0.0,
            "hardware": "Cloud (Azure OpenAI)",
        }
    except Exception as exc:
        print(f"[CLOUD] Azure OpenAI call failed: {exc} — falling back to local")
        return _run_local_inference(system_prompt, user_prompt, max_tokens)


def run_inference(
    system_prompt: str,
    user_prompt: str,
    module: str,
    max_tokens: int = 1024,
    force_local: bool = False,
    marked_sensitive: bool = False,
) -> dict:
    """Run inference with runtime routing decisioning."""
    routing = decide_routing(user_prompt, module, force_local, marked_sensitive)
    route = routing["route"]

    if route == "cloud":
        result = _run_cloud_inference(system_prompt, user_prompt, max_tokens)
    else:
        result = _run_local_inference(system_prompt, user_prompt, max_tokens)

    # Log to SQLite (metadata only — no raw prompts)
    entry_id = str(uuid.uuid4())[:8]
    log_routing_decision({
        "id": entry_id,
        "timestamp": datetime.now().isoformat(),
        "module": module,
        "route": route,
        "reason": routing["reason"],
        "pii_types": routing["pii_detected"],
        "tokens": result["tokens"],
        "latency_ms": result["latency_ms"],
        "cloud_cost_saved": result["cloud_cost_saved"],
        "hardware": result["hardware"],
    })

    return {
        "text": result["text"],
        "tokens": result["tokens"],
        "latency_ms": result["latency_ms"],
        "cloud_cost_saved": f"${result['cloud_cost_saved']:.4f}",
        "hardware": result["hardware"],
        "route": route,
        "routing_reason": routing["reason"],
        "pii_detected": bool(routing["pii_detected"]),
        "pii_types": list(routing["pii_detected"].keys()),
    }


# ---------------------------------------------------------------------------
# PDF text extraction helper
# ---------------------------------------------------------------------------
def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using PyPDF2 (local, no cloud)."""
    if not PDF_SUPPORT:
        return "[PDF support not available — install PyPDF2]"
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text.strip() or "[No extractable text found in PDF]"
    except Exception as exc:
        return f"[PDF extraction error: {exc}]"


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB


# ---------------------------------------------------------------------------
# Routes — Pages
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Routes — API: Status
# ---------------------------------------------------------------------------
@app.route("/api/status")
def api_status():
    return jsonify({
        "foundry_connected": foundry_ok,
        "model": model_id or "N/A",
        "endpoint": foundry_service_url or "N/A",
        "mode": "on-device NPU" if use_npu else ("on-device CPU" if foundry_ok else "UI preview (no AI)"),
        "hardware": "NPU" if use_npu else ("CPU" if foundry_ok else "none"),
        "silicon": SILICON,
        "cloud_available": CLOUD_AVAILABLE,
        "cloud_endpoint": AZURE_OPENAI_ENDPOINT or "Not configured",
    })


# ---------------------------------------------------------------------------
# Routes — API: Counter Service Copilot
# ---------------------------------------------------------------------------
@app.route("/api/counter-service", methods=["POST"])
def api_counter_service():
    data = request.get_json(force=True)
    user_msg = data.get("message", "").strip()
    if not user_msg:
        return jsonify({"error": "Empty message"}), 400

    system = (
        "You are a Counter Service Copilot for a public sector agency. You help front desk staff and call center "
        "agents respond to citizen inquiries quickly and accurately. Be professional, clear, and empathetic. "
        "Help with: service requests, permit questions, utility billing, license renewals, complaint intake, "
        "appointment scheduling, and general information. Summarize the citizen's request and draft a response. "
        "If the request involves sensitive information, note that it should be handled through secure channels. "
        "Always be helpful and direct — citizens are often frustrated by bureaucracy."
    )
    result = run_inference(
        system, user_msg, "counter_service",
        max_tokens=350,
        force_local=data.get("force_local", False),
        marked_sensitive=data.get("sensitive", False),
    )
    return jsonify(result)


# ---------------------------------------------------------------------------
# Routes — API: Policy & Ordinance Analyzer
# ---------------------------------------------------------------------------
@app.route("/api/policy-analyzer", methods=["POST"])
def api_policy_analyzer():
    data = request.get_json(force=True)
    doc_text = data.get("text", "").strip()
    task = data.get("task", "summarize")

    if not doc_text:
        return jsonify({"error": "No document text provided"}), 400

    task_prompts = {
        "summarize": (
            "Summarize this policy document in 3-5 bullet points. Focus on: purpose, key requirements, "
            "affected parties, compliance deadlines, and enforcement mechanisms."
        ),
        "extract": (
            "Extract key clauses from this policy/ordinance: effective date, scope, definitions, "
            "requirements, penalties, exemptions, reporting obligations, and amendment procedures. "
            "Return as a structured list."
        ),
        "compare": (
            "Analyze this policy document and identify: strengths, potential gaps, areas that may "
            "conflict with other regulations, accessibility concerns, and suggested improvements. "
            "Provide a brief assessment."
        ),
        "sensitive_review": (
            "Review this document for sensitive content: internal notes, draft language, "
            "confidential references, PII, or content that should not be made public. "
            "Flag any items that need redaction before publication."
        ),
    }

    system = "Public sector policy analyst. " + task_prompts.get(task, task_prompts["summarize"])
    doc_truncated = doc_text[:2000]
    result = run_inference(
        system, doc_truncated, "policy_analyzer",
        max_tokens=400,
        force_local=data.get("force_local", False),
        marked_sensitive=data.get("sensitive", False),
    )
    return jsonify(result)


@app.route("/api/policy-analyzer/upload-pdf", methods=["POST"])
def api_policy_upload_pdf():
    """Upload a PDF for local text extraction."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    if not f.filename or not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported"}), 400
    pdf_bytes = f.read()
    text = extract_pdf_text(pdf_bytes)
    return jsonify({"text": text, "pages": text.count("\n\n") + 1})


# ---------------------------------------------------------------------------
# Routes — API: Disaster Response Field Briefing
# ---------------------------------------------------------------------------
@app.route("/api/disaster-response", methods=["POST"])
def api_disaster_response():
    data = request.get_json(force=True)
    user_msg = data.get("message", "").strip()
    task = data.get("task", "briefing")

    if not user_msg:
        return jsonify({"error": "Empty message"}), 400

    task_prompts = {
        "briefing": (
            "Generate a concise situation briefing from the following field notes. Include: "
            "current situation summary, key developments, immediate priorities, resource status, "
            "and recommended next actions. Format for quick field reading."
        ),
        "checklist": (
            "Create an action checklist from these incident notes. Prioritize by urgency. "
            "Include: immediate safety actions, resource deployment, communication tasks, "
            "documentation requirements, and follow-up items."
        ),
        "translate": (
            "Translate and clarify the following field notes into clear, structured English. "
            "Preserve all factual details while improving readability. Flag any ambiguous items."
        ),
        "incident_log": (
            "Summarize these incident log entries into a structured timeline. Include: "
            "time, event, actions taken, and current status for each entry."
        ),
    }

    system = (
        "You are a Disaster Response AI running entirely on-device for field operations. "
        "No internet connection is required. Be concise, factual, and action-oriented. "
        + task_prompts.get(task, task_prompts["briefing"])
    )

    # Disaster response is ALWAYS local — module policy enforces this
    result = run_inference(
        system, user_msg, "disaster_response",
        max_tokens=400,
        force_local=True,
        marked_sensitive=data.get("sensitive", False),
    )

    # Queue summary for sync when connectivity returns
    if result.get("text") and not result["text"].startswith("["):
        queue_for_sync("disaster_response", f"[{task}] Briefing generated", {
            "task_type": task,
            "tokens": result["tokens"],
            "timestamp": datetime.now().isoformat(),
        })

    return jsonify(result)


# ---------------------------------------------------------------------------
# Routes — API: Permit / Inspection Assistant
# ---------------------------------------------------------------------------
@app.route("/api/permit-inspection", methods=["POST"])
def api_permit_inspection():
    data = request.get_json(force=True)
    user_msg = data.get("message", "").strip()
    task = data.get("task", "extract")

    if not user_msg:
        return jsonify({"error": "Empty message"}), 400

    task_prompts = {
        "extract": (
            "Extract structured fields from these inspection/permit notes: "
            "permit number, property address, owner/applicant, inspection type, "
            "date, inspector, findings, violations, required corrections, "
            "deadline, and status. Return as a structured list."
        ),
        "summarize": (
            "Summarize this inspection report into a brief executive summary: "
            "property, inspection type, key findings, violations (if any), "
            "overall status, and recommended next steps."
        ),
        "draft_report": (
            "Draft a formal inspection summary report from these field notes. "
            "Include: header information, inspection details, findings, "
            "compliance status, required actions, and inspector signature block."
        ),
        "flag_issues": (
            "Review these permit/inspection notes and flag: safety concerns, "
            "code violations, missing documentation, overdue items, "
            "and items requiring immediate attention. Prioritize by severity."
        ),
    }

    system = (
        "You are a Permit and Inspection Assistant for a local government agency. "
        "Be precise, factual, and use standard inspection terminology. "
        + task_prompts.get(task, task_prompts["extract"])
    )

    result = run_inference(
        system, user_msg, "permit_inspection",
        max_tokens=400,
        force_local=data.get("force_local", False),
        marked_sensitive=data.get("sensitive", False),
    )
    return jsonify(result)


# ---------------------------------------------------------------------------
# Routes — API: Dashboard Metrics
# ---------------------------------------------------------------------------
@app.route("/api/metrics")
def api_metrics():
    return jsonify(get_dashboard_metrics())


@app.route("/api/pii-check", methods=["POST"])
def api_pii_check():
    """Quick PII scan endpoint for the UI to show real-time detection."""
    data = request.get_json(force=True)
    text = data.get("text", "")
    pii = detect_pii(text)
    return jsonify({
        "pii_detected": bool(pii),
        "pii_types": list(pii.keys()),
        "pii_counts": pii,
    })


# ---------------------------------------------------------------------------
# Routes — API: On-Device Speech-to-Text (Whisper)
# ---------------------------------------------------------------------------
@app.route("/api/transcribe", methods=["POST"])
def api_transcribe():
    """Transcribe audio using on-device Whisper model. No cloud, no data leaves the PC."""
    if not WHISPER_SUPPORT or not whisper_model:
        return jsonify({"error": "On-device dictation not available (faster-whisper not loaded)"}), 503

    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    audio_file = request.files["audio"]
    tmp_path = None
    try:
        # Save to temp file (Whisper needs a file path)
        suffix = ".webm"
        if audio_file.filename:
            suffix = Path(audio_file.filename).suffix or ".webm"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp_path = tmp.name
        audio_file.save(tmp)
        tmp.close()

        t0 = time.perf_counter()
        segments, info = whisper_model.transcribe(tmp_path, language="en")
        text = " ".join(seg.text.strip() for seg in segments)
        elapsed_ms = round((time.perf_counter() - t0) * 1000)

        return jsonify({
            "text": text,
            "latency_ms": elapsed_ms,
            "language": info.language,
            "duration_s": round(info.duration, 1),
            "hardware": "On-Device (CPU/Whisper)",
        })
    except Exception as exc:
        return jsonify({"error": f"Transcription failed: {exc}"}), 500
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Public Sector Hybrid AI Demo")
    print("  On-Device + Cloud — Intel NPU Optimized")
    print("  Powered by Foundry Local + Azure OpenAI")
    print("=" * 60)
    print(f"  Silicon:  {SILICON.upper()}")
    print(f"  Local:    {'NPU' if use_npu else 'CPU'} — {model_id or 'not loaded'}")
    print(f"  Cloud:    {'Azure OpenAI connected' if CLOUD_AVAILABLE else 'Not configured (local-only mode)'}")
    print(f"  Open →    http://localhost:5000")
    print("=" * 60 + "\n")
    app.run(host="127.0.0.1", port=5000, debug=False)
