"""
═══════════════════════════════════════════════════════════════════════════════
ERCORS v18 — Complete AI Platform
Multi-Key Groq · HR AI · Giant Companies · 40 AI Services
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import re
import sys
import json
import base64
import hashlib
import secrets
import sqlite3
import logging
import asyncio
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

# ─── .env faylini yuklash (lokal uchun) ───
_env = Path(__file__).parent / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

import httpx
from fastapi import (
    FastAPI, Request, HTTPException, Depends, Form,
    UploadFile, File, WebSocket, WebSocketDisconnect
)
from fastapi.responses import HTMLResponse, JSONResponse, Response, FileResponse
from fastapi.middleware.cors import CORSMiddleware

# ═══════════════════════════════════════════════════════════════
# CONFIG — Barcha kalitlar env var'dan
# ═══════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path("/tmp" if os.getenv("RENDER") else str(BASE_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "ercors.db"
INDEX_HTML = BASE_DIR / "index.html"

# Groq kalitlar — faqat env var'dan
GROQ_KEYS = [
    os.getenv("GROQ_KEY_1", "").strip(),
    os.getenv("GROQ_KEY_2", "").strip(),
    os.getenv("GROQ_KEY_3", "").strip(),
]
GROQ_KEYS = [k for k in GROQ_KEYS if k]

GROQ_BASE = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.3-70b-versatile"

TOKEN_EXPIRY_HOURS = 168
MAX_UPLOAD_SIZE = 25 * 1024 * 1024
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("ercors")


# ═══════════════════════════════════════════════════════════════
# GROQ MULTI-KEY POOL
# ═══════════════════════════════════════════════════════════════

class GroqPool:
    """3 ta kalit bilan rotation. Bittasi ishlamasa, keyingisiga o'tadi."""

    def __init__(self, keys):
        self.keys = keys
        self.failed = {}
        self.lock = asyncio.Lock()

    def _available(self):
        now = datetime.utcnow()
        return [k for k in self.keys
                if k not in self.failed or (now - self.failed[k]).total_seconds() > 300]

    async def _try(self, key, endpoint, payload=None, files=None, data=None):
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                if files:
                    r = await client.post(
                        f"{GROQ_BASE}{endpoint}",
                        headers={"Authorization": f"Bearer {key}"},
                        files=files, data=data)
                else:
                    r = await client.post(
                        f"{GROQ_BASE}{endpoint}",
                        headers={"Authorization": f"Bearer {key}",
                                 "Content-Type": "application/json"},
                        json=payload)
                if r.status_code == 200:
                    return r.json()
                if r.status_code in (401, 403, 429):
                    self.failed[key] = datetime.utcnow()
                    log.warning("Kalit ...%s xato (%d)", key[-6:], r.status_code)
                    return None
                log.warning("Groq %d: %s", r.status_code, r.text[:150])
                return None
        except Exception as e:
            log.warning("Kalit ...%s: %s", key[-6:], e)
            return None

    async def chat(self, messages, model=None, temperature=0.7,
                   max_tokens=800, json_mode=False):
        if not self.keys:
            return ""
        model = model or GROQ_MODEL
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        async with self.lock:
            keys = self._available() or self.keys

        for k in keys:
            res = await self._try(k, "/chat/completions", payload=payload)
            if res:
                try:
                    return res["choices"][0]["message"]["content"].strip()
                except Exception:
                    pass
        return ""

    async def json_chat(self, messages, model=None, temperature=0.3):
        text = await self.chat(messages, model=model,
                                temperature=temperature, json_mode=True)
        if not text:
            return {}
        try:
            return json.loads(text)
        except Exception:
            m = re.search(r"\{[\s\S]*\}", text)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    pass
            return {}

    async def transcribe(self, audio_bytes, filename="audio.webm", language="en"):
        if not self.keys:
            return ""
        async with self.lock:
            keys = self._available() or self.keys
        for k in keys:
            files = {"file": (filename, audio_bytes, "audio/mpeg")}
            data = {"model": "whisper-large-v3", "language": language}
            res = await self._try(k, "/audio/transcriptions", files=files, data=data)
            if res:
                return res.get("text", "")
        return ""


groq = GroqPool(GROQ_KEYS)


# ═══════════════════════════════════════════════════════════════
# GIANT COMPANIES
# ═══════════════════════════════════════════════════════════════

GIANT_COMPANIES = {
    "google":    {"name": "Google",    "logo": "🔵", "avg_budget": 500000, "stacks": ["python", "kubernetes", "tensorflow"], "style": "thorough",  "timeline": 90,  "min_trust": 90},
    "openai":    {"name": "OpenAI",    "logo": "🟢", "avg_budget": 400000, "stacks": ["python", "pytorch", "transformers"], "style": "fast",      "timeline": 60,  "min_trust": 88},
    "meta":      {"name": "Meta",      "logo": "🔷", "avg_budget": 450000, "stacks": ["python", "pytorch", "react"],         "style": "aggressive","timeline": 75,  "min_trust": 85},
    "microsoft": {"name": "Microsoft", "logo": "🟦", "avg_budget": 350000, "stacks": ["c#", "azure", "typescript"],          "style": "formal",    "timeline": 90,  "min_trust": 85},
    "anthropic": {"name": "Anthropic", "logo": "🟠", "avg_budget": 380000, "stacks": ["python", "pytorch", "transformers"],  "style": "research",  "timeline": 60,  "min_trust": 92},
    "nvidia":    {"name": "Nvidia",    "logo": "🟩", "avg_budget": 420000, "stacks": ["cuda", "c++", "python"],             "style": "technical", "timeline": 70,  "min_trust": 90},
    "apple":     {"name": "Apple",     "logo": "⚫", "avg_budget": 300000, "stacks": ["swift", "python", "coreml"],          "style": "secretive", "timeline": 120, "min_trust": 88},
    "amazon":    {"name": "Amazon",    "logo": "🟨", "avg_budget": 280000, "stacks": ["aws", "python", "java"],              "style": "cost",      "timeline": 60,  "min_trust": 80},
    "tesla":     {"name": "Tesla",     "logo": "🔴", "avg_budget": 320000, "stacks": ["python", "pytorch", "c++"],           "style": "fast",      "timeline": 45,  "min_trust": 82},
    "stripe":    {"name": "Stripe",    "logo": "🟪", "avg_budget": 250000, "stacks": ["ruby", "go", "typescript"],            "style": "eng",       "timeline": 50,  "min_trust": 85},
}


# ═══════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════

def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL, user_type TEXT DEFAULT 'expert',
    company_name TEXT, industry TEXT, skills TEXT,
    hourly_rate TEXT, github TEXT,
    trust_score REAL DEFAULT 75.0, xp INTEGER DEFAULT 50,
    level INTEGER DEFAULT 1, projects INTEGER DEFAULT 0,
    earnings REAL DEFAULT 0, referral_code TEXT UNIQUE,
    referred_by TEXT, referred_count INTEGER DEFAULT 0,
    referral_earnings REAL DEFAULT 0, streak_days INTEGER DEFAULT 1,
    last_streak TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_login TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER,
    title TEXT NOT NULL, description TEXT, required_skills TEXT,
    min_experience REAL, budget TEXT, deadline TEXT,
    status TEXT DEFAULT 'Open', company_key TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, user_name TEXT,
    content TEXT NOT NULL, likes INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS escrows (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
    title TEXT NOT NULL, amount REAL NOT NULL,
    status TEXT DEFAULT 'active', created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS badges (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
    badge_key TEXT NOT NULL, claimed_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, badge_key)
);
CREATE TABLE IF NOT EXISTS bounties (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, company TEXT,
    prize INTEGER, severity TEXT, deadline TEXT,
    claimed_by INTEGER, claimed_at TEXT
);
CREATE TABLE IF NOT EXISTS chat_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
    role TEXT, message TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS interviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
    session_id TEXT UNIQUE, position TEXT, company TEXT,
    status TEXT DEFAULT 'active', questions TEXT, answers TEXT,
    scores TEXT, final_score INTEGER, evaluation TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP, completed_at TEXT
);
CREATE TABLE IF NOT EXISTS negotiations (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
    campaign_id INTEGER, company_key TEXT, company_name TEXT,
    developer_name TEXT, scope TEXT, budget_start TEXT,
    final_budget REAL, deadline_days INTEGER, milestones TEXT,
    terms TEXT, status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS credits (
    user_id INTEGER PRIMARY KEY, balance REAL DEFAULT 0,
    total_spent REAL DEFAULT 0, tier TEXT DEFAULT 'free',
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS ai_services (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
    service_key TEXT, input_text TEXT, output_text TEXT,
    cost REAL, status TEXT DEFAULT 'completed',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS revenue (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
    service_key TEXT, amount REAL, commission REAL, net REAL,
    status TEXT DEFAULT 'completed',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS enterprise_clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT, company_name TEXT UNIQUE NOT NULL,
    contact_email TEXT, plan TEXT DEFAULT 'starter',
    monthly_quota INTEGER DEFAULT 1000, quota_used INTEGER DEFAULT 0,
    api_key TEXT UNIQUE, webhook_url TEXT, status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS enterprise_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER,
    service_key TEXT, input_size INTEGER, output_size INTEGER,
    status TEXT DEFAULT 'completed', cost REAL, duration_ms INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
"""


def init_db():
    conn = db()
    try:
        conn.executescript(SCHEMA)
        conn.commit()

        if conn.execute("SELECT COUNT(*) c FROM bounties").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT INTO bounties (id,title,company,prize,severity,deadline) VALUES (?,?,?,?,?,?)",
                [("b1", "Fix RAG bug", "OpenAI", 5000, "critical", "2h"),
                 ("b2", "Optimize transformer", "Meta", 3500, "high", "5h"),
                 ("b3", "AI safety protocol", "Anthropic", 8000, "critical", "1d"),
                 ("b4", "Vector DB benchmark", "Pinecone", 1500, "medium", "3d"),
                 ("b5", "RLHF alignment", "DeepMind", 12000, "critical", "2d"),
                 ("b6", "LLM eval dataset", "Hugging Face", 2000, "high", "1d"),
                 ("b7", "Google Brain research", "Google", 15000, "critical", "3d"),
                 ("b8", "Nvidia CUDA kernel", "Nvidia", 9000, "high", "2d")])

        if conn.execute("SELECT COUNT(*) c FROM posts").fetchone()["c"] == 0:
            conn.executemany("INSERT INTO posts (user_name, content, likes) VALUES (?,?,?)",
                             [("Ali Karimov", "ERCORS v18 ishga tushdi! 🚀", 12),
                              ("Malika Yusupova", "Ovozli AI intervyu ishlaydi! 💼", 34),
                              ("ERCORS Admin", "40 ta AI xizmat LIVE ✅", 89)])

        if conn.execute("SELECT COUNT(*) c FROM campaigns").fetchone()["c"] == 0:
            for key, comp in GIANT_COMPANIES.items():
                conn.execute(
                    """INSERT INTO campaigns (title, description, budget, deadline,
                       required_skills, company_key) VALUES (?,?,?,?,?,?)""",
                    (f"{comp['name']} AI Project",
                     f"Advanced AI project for {comp['name']}",
                     f"${comp['avg_budget']:,}", "2027-06-30",
                     ",".join(comp["stacks"]), key))

        conn.commit()
        log.info("✅ DB initialized")
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# 64 MODULES
# ═══════════════════════════════════════════════════════════════

_MODULE_DATA = [
    ("m1","Enterprise AI Talent Matching","Core"),("m2","Managed RLHF & Data Annotation","Core"),
    ("m3","AI Hiring SaaS & Trust Score","Core"),("m4","Global Escrow & B2B Contracts","Core"),
    ("m5","Micro-Equity HFT Engine","Core"),("m6","AI Vetted Engineers","Talent Sourcing"),
    ("m7","AI & ML Specialists","Talent Sourcing"),("m8","Autonomous AI Agents & Swarm","Talent Sourcing"),
    ("m9","Embedded & Edge AI Hardware","Talent Sourcing"),("m10","Quantum Computing & Security","Talent Sourcing"),
    ("m11","RLHF & Model Evaluation","Data & Training"),("m12","Code Data Annotation","Data & Training"),
    ("m13","Multimodal Data Sourcing","Data & Training"),("m14","Red Teaming & AI Safety","Data & Training"),
    ("m15","AI Voice/Video Interview Bot","Hiring Tools"),("m16","Code Assessment Engine","Hiring Tools"),
    ("m17","Background & Trust Score","Hiring Tools"),("m18","AI Skill Graph Analyzer","Hiring Tools"),
    ("m19","Dedicated Remote Teams","Direct & Premium"),("m20","Express AI Consultation","Direct & Premium"),
    ("m21","AI Startup Builder On-Demand","Direct & Premium"),("m22","Web3 & Spatial Computing","Direct & Premium"),
    ("m23","Direct Escrow & Mass Payouts","Direct & Premium"),("m24","Enterprise SLA & Managed PM","Direct & Premium"),
    ("m25","Instant Talent API Access","Direct & Premium"),("m26","Cloud GPU & TPU Server Access","Infrastructure"),
    ("m27","Quantum QPU Remote Access","Infrastructure"),("m28","AI Sandbox & Code Execution","Infrastructure"),
    ("m29","Serverless AI Endpoint Hosting","Infrastructure"),("m30","Autonomous Software Engineer Swarm","Infrastructure"),
    ("m31","AI Data Scraping & Web Extraction","Infrastructure"),("m32","Autonomous SMM & Marketing","Infrastructure"),
    ("m33","AI Customer Support & Voice Bot","Infrastructure"),("m34","Zero-Knowledge Proofs Sandbox","Infrastructure"),
    ("m35","Automated NDA & Smart Contracts","Infrastructure"),("m36","Deepfake & Synthetic Media Audit","Infrastructure"),
    ("m37","WebXR & Spatial VR Showroom","Infrastructure"),("m38","3D Generative Asset Factory","Infrastructure"),
    ("m39","Digital Twin Factory Simulation","Infrastructure"),("m40","Custom GLSL Shader & Physics","Infrastructure"),
    ("m41","HFT Micro-Equity Exchange","Infrastructure"),("m42","Global Crypto Escrow","Infrastructure"),
    ("m43","Micro-Equity Flash Loans","Infrastructure"),("m44","AI Startup Crowdfunding","Infrastructure"),
    ("m45","AI-Powered Code Review","Developer Tools"),("m46","Automated Testing Suite","Developer Tools"),
    ("m47","CI/CD Pipeline Integration","Developer Tools"),("m48","Docker & Kubernetes Orchestration","Developer Tools"),
    ("m49","AI-Driven Documentation","Developer Tools"),("m50","Code Quality Dashboard","Developer Tools"),
    ("m51","Real-Time Error Tracking","Developer Tools"),("m52","Performance Monitoring","Developer Tools"),
    ("m53","Security Vulnerability Scanner","Developer Tools"),("m54","API Gateway & Management","Developer Tools"),
    ("m55","GraphQL Federation","Developer Tools"),("m56","Event-Driven Architecture","Developer Tools"),
    ("m57","Data Lake & Analytics","Developer Tools"),("m58","MLOps Pipeline","Developer Tools"),
    ("m59","Model Monitoring & Drift","Developer Tools"),("m60","Feature Store","Developer Tools"),
    ("m61","Explainable AI (XAI)","Developer Tools"),("m62","Federated Learning","Developer Tools"),
    ("m63","Synthetic Data Generation","Developer Tools"),("m64","AI Governance & Compliance","Developer Tools"),
]
MODULES = [{"id": m, "name": n, "category": c, "description": f"AI module for {c}.", "active": True}
           for m, n, c in _MODULE_DATA]
MODULE_MAP = {m["id"]: m for m in MODULES}


# ═══════════════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════════════

def hash_pw(p):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", p.encode(), salt, 100_000)
    return base64.b64encode(salt + dk).decode()


def verify_pw(p, h):
    try:
        raw = base64.b64decode(h.encode())
        salt, dk = raw[:16], raw[16:]
        return secrets.compare_digest(
            dk, hashlib.pbkdf2_hmac("sha256", p.encode(), salt, 100_000))
    except Exception:
        return False


def make_token(uid):
    token = secrets.token_urlsafe(48)
    expires = (datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS)).isoformat()
    conn = db()
    try:
        conn.execute("INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)",
                     (token, uid, expires))
        conn.commit()
    finally:
        conn.close()
    return token


def user_from_token(token):
    if not token:
        return None
    conn = db()
    try:
        row = conn.execute(
            """SELECT u.* FROM users u JOIN sessions s ON s.user_id = u.id
               WHERE s.token = ? AND s.expires_at > datetime('now')""",
            (token,)).fetchone()
        if not row:
            return None
        u = dict(row)
        u.pop("password_hash", None)
        return u
    finally:
        conn.close()


def get_token(request):
    auth = request.headers.get("Authorization", "")
    return auth[7:].strip() if auth.startswith("Bearer ") else request.cookies.get("ercors_token")


async def current_user(request: Request):
    return user_from_token(get_token(request))


async def require_user(request: Request):
    u = await current_user(request)
    if not u:
        raise HTTPException(401, "Authentication required")
    return u


def make_ref(name):
    base = re.sub(r"[^A-Za-z]", "", name)[:4].upper() or "USER"
    return f"{base}{secrets.token_hex(3).upper()}"


# ═══════════════════════════════════════════════════════════════
# AI ENGINE
# ═══════════════════════════════════════════════════════════════

class AI:

    @staticmethod
    async def chat(message, context=None):
        sys_p = ("You are ERCORS AI. Expert for ERCORS platform with 64 modules, HR AI, "
                 "voice interviews, escrow, giant companies (Google, OpenAI, Meta, Microsoft, "
                 "Anthropic, Nvidia, Apple, Amazon, Tesla, Stripe), and 40 AI services. "
                 "Answer in user's language. Concise (max 120 words).")
        msgs = [{"role": "system", "content": sys_p}]
        if context:
            for c in context[-6:]:
                msgs.append({"role": c.get("role", "user"),
                             "content": c.get("message", "")})
        msgs.append({"role": "user", "content": message})
        return await groq.chat(msgs, temperature=0.7, max_tokens=400)

    @staticmethod
    async def analyze_cv(cv_text):
        prompt = f"""Analyze CV. Return JSON:
{{"name": "...", "position": "...", "experience_years": number,
  "skills": [], "education": "...", "strengths": [], "weaknesses": [],
  "trust_score": 0-100, "summary": "...", "recommended_roles": [],
  "recommended_companies": [], "match_percentage": 0-100}}

CV: {cv_text[:6000]}"""
        d = await groq.json_chat([
            {"role": "system", "content": "HR analyst. Return only JSON."},
            {"role": "user", "content": prompt}], temperature=0.3)
        if not d:
            skills_db = ["python", "javascript", "react", "pytorch", "tensorflow",
                         "docker", "kubernetes", "llm", "fastapi", "sql"]
            found = [s for s in skills_db if s in cv_text.lower()]
            d = {"name": "Unknown", "position": "AI Engineer", "experience_years": 3,
                 "skills": found, "education": "N/A", "strengths": ["Technical"],
                 "weaknesses": ["Elaborate more"], "trust_score": 75,
                 "summary": "AI professional.", "recommended_roles": ["AI Engineer"],
                 "recommended_companies": ["Google", "OpenAI"], "match_percentage": 75}
        return d

    @staticmethod
    async def interview_questions(position, company=None, count=5):
        ctx = f" at {company}" if company else ""
        prompt = f"""Generate {count} interview questions for {position}{ctx}.
Mix: 2 technical, 2 behavioral, 1 situational.
Return ONLY JSON: {{"questions": ["Q1", "Q2", ...]}}"""
        d = await groq.json_chat([
            {"role": "system", "content": "Interviewer. Return only JSON."},
            {"role": "user", "content": prompt}], temperature=0.7)
        return d.get("questions", [])[:count] or [
            f"Tell me about your experience as a {position}.",
            "Describe your most challenging project.",
            "How do you handle disagreements?",
            "What's your learning approach?",
            f"Why work{ctx or ' at ERCORS'}?",
        ][:count]

    @staticmethod
    async def evaluate_answer(position, question, answer):
        prompt = f"""Evaluate single interview answer. JSON:
{{"score": 0-100, "feedback": "...", "strengths": [], "improvements": []}}

Q: {question}
A: {answer}"""
        d = await groq.json_chat([
            {"role": "system", "content": "Interviewer. Return only JSON."},
            {"role": "user", "content": prompt}], temperature=0.3)
        if not d:
            wc = len(answer.split())
            d = {"score": min(95, max(40, 50 + wc // 5)), "feedback": "Good response.",
                 "strengths": ["Clear"], "improvements": ["Add specifics"]}
        return d

    @staticmethod
    async def final_interview(position, questions, answers, scores):
        qa = "\n\n".join([f"Q{i+1}: {q}\nA: {a}\nScore: {s.get('score',0)}"
                          for i, (q, a, s) in enumerate(zip(questions, answers, scores))])
        prompt = f"""Final interview eval for {position}. JSON:
{{"overall_score": 0-100, "match_percentage": 0-100,
  "recommendation": "STRONG HIRE/HIRE/MAYBE/NO HIRE",
  "strengths": [], "weaknesses": [], "detailed_feedback": "...",
  "next_steps": "...", "potential_companies": []}}

{qa[:6000]}"""
        d = await groq.json_chat([
            {"role": "system", "content": "HR evaluator. Return only JSON."},
            {"role": "user", "content": prompt}], temperature=0.4)
        if not d:
            avg = sum(s.get("score", 0) for s in scores) / max(len(scores), 1)
            d = {"overall_score": round(avg), "match_percentage": round(avg),
                 "recommendation": "HIRE" if avg >= 70 else "MAYBE",
                 "strengths": ["Completed interview"], "weaknesses": ["More detail"],
                 "detailed_feedback": f"Completed {len(answers)} questions.",
                 "next_steps": "Practice STAR format",
                 "potential_companies": ["Google", "OpenAI"]}
        return d

    @staticmethod
    async def negotiate_giant(company_key, developer_name, scope, trust_score=75):
        comp = GIANT_COMPANIES.get(company_key)
        if not comp:
            return {"error": "Unknown company"}
        prompt = f"""B2B negotiation with {comp['name']} ({comp['style']} style).
Budget ${comp['avg_budget']:,}, timeline {comp['timeline']} days.
Developer: {developer_name}, trust: {trust_score}/100 (min {comp['min_trust']}).
Scope: {scope}

JSON: {{"company_name": "{comp['name']}", "offer_budget": number,
  "counter_budget": number, "final_budget": number, "deadline_days": number,
  "milestones": [{{"name": "...", "percent": 20, "deliverable": "..."}}],
  "terms": "...", "nda_required": true/false, "ip_ownership": "...",
  "escrow_setup": "...", "risks": [], "accepted": true/false,
  "confidence": 0-1, "advice": "..."}}"""
        d = await groq.json_chat([
            {"role": "system", "content": "Contract negotiator. Return only JSON."},
            {"role": "user", "content": prompt}], temperature=0.4)
        if not d:
            base = comp["avg_budget"]
            d = {"company_name": comp["name"], "offer_budget": base,
                 "counter_budget": int(base * 1.15), "final_budget": int(base * 1.08),
                 "deadline_days": comp["timeline"],
                 "milestones": [{"name": "Kickoff", "percent": 20, "deliverable": "Research"},
                                {"name": "MVP", "percent": 40, "deliverable": "Prototype"},
                                {"name": "Production", "percent": 30, "deliverable": "Deploy"},
                                {"name": "Handoff", "percent": 10, "deliverable": "Docs"}],
                 "terms": "Milestone escrow, NDA, IP shared", "nda_required": True,
                 "ip_ownership": "shared", "escrow_setup": "4-milestone",
                 "risks": ["Scope creep"],
                 "accepted": trust_score >= comp["min_trust"],
                 "confidence": 0.85,
                 "advice": f"Need trust ≥ {comp['min_trust']}"}
        return d

    @staticmethod
    async def match_bounties(skills, bounties):
        prompt = f"""Match skills to bounties. JSON:
{{"matches": [{{"bounty_id": "b1", "match_score": 95, "reason": "..."}}]}}

Skills: {skills}
Bounties: {json.dumps(bounties[:10])}"""
        d = await groq.json_chat([
            {"role": "system", "content": "Matcher. Return only JSON."},
            {"role": "user", "content": prompt}], temperature=0.2)
        return d.get("matches", [])

    @staticmethod
    async def salary(years, role, region, skills=None):
        prompt = f"""Salary estimate. JSON: {{"salary_k_usd": number,
  "monthly_k_usd": number, "range_low": number, "range_high": number,
  "currency": "USD", "notes": "...", "top_companies_offering": []}}
Role: {role}, Years: {years}, Region: {region}, Skills: {skills or []}"""
        d = await groq.json_chat([
            {"role": "system", "content": "Comp analyst. Return only JSON."},
            {"role": "user", "content": prompt}], temperature=0.3)
        if not d:
            base = {"ai": 120, "fullstack": 90, "data": 110, "devops": 105}.get(role, 100)
            m = {"us": 1.4, "eu": 1.1, "uz": 0.35, "remote": 1.0}.get(region, 1.0)
            s = round((base + years * 4) * m, 1)
            d = {"salary_k_usd": s, "monthly_k_usd": round(s / 12, 1),
                 "range_low": round(s * 0.85, 1), "range_high": round(s * 1.2, 1),
                 "currency": "USD", "notes": "Market-based",
                 "top_companies_offering": ["Google", "OpenAI", "Meta"]}
        return d

    @staticmethod
    async def skill_gap(skills, role):
        prompt = f"""Skill gap analysis. JSON: {{"match_percentage": 0-100,
  "have": [], "missing": [], "learning_path": [{{"skill": "X", "resources": [], "weeks": 4}}],
  "next_step": "..."}}
Skills: {skills}, Target: {role}"""
        d = await groq.json_chat([
            {"role": "system", "content": "Career coach. Return only JSON."},
            {"role": "user", "content": prompt}], temperature=0.4)
        if not d:
            req = {"ai": ["Python", "PyTorch", "LLMs", "RAG", "MLOps", "Docker"],
                   "fullstack": ["React", "Node.js", "TypeScript", "SQL", "Git"],
                   "data": ["Python", "SQL", "Pandas", "ML", "Statistics"],
                   "devops": ["Kubernetes", "Terraform", "AWS", "CI/CD", "Docker"]}
            r = req.get(role, req["ai"])
            h = [x for x in r if x.lower() in {s.lower() for s in skills}]
            m = [x for x in r if x not in h]
            d = {"match_percentage": round(len(h)/len(r)*100) if r else 0,
                 "have": h, "missing": m,
                 "learning_path": [{"skill": m[0] if m else "Python",
                                    "resources": ["freeCodeCamp", "Coursera"],
                                    "weeks": 4}],
                 "next_step": f"Learn {m[0] if m else 'advanced'}"}
        return d

    @staticmethod
    async def portfolio(name, title, skills, theme="neon"):
        prompt = f"""Portfolio. JSON: {{"tagline": "...", "bio": "3 sentences",
  "top_projects": [{{"name": "X", "description": "Y"}}], "call_to_action": "...",
  "target_companies": []}}
Name: {name}, Title: {title}, Skills: {skills}"""
        d = await groq.json_chat([
            {"role": "system", "content": "Branding expert. Return only JSON."},
            {"role": "user", "content": prompt}], temperature=0.7)
        if not d:
            d = {"tagline": f"{title} · {', '.join(skills[:3])}",
                 "bio": f"{name} is a {title} with {', '.join(skills[:5])}.",
                 "top_projects": [], "call_to_action": "Contact me",
                 "target_companies": ["Google", "OpenAI"]}
        d.update({"name": name, "title": title, "skills": skills, "theme": theme})
        return d

    @staticmethod
    async def quiz(topic="AI", count=5):
        prompt = f"""{count} MCQs on {topic}. JSON: {{"questions": [
  {{"q": "...", "opts": ["A","B","C","D"], "answer_index": 0}}]}}"""
        d = await groq.json_chat([
            {"role": "system", "content": "Quiz creator. Return only JSON."},
            {"role": "user", "content": prompt}], temperature=0.7)
        return d.get("questions", [])[:count]

    @staticmethod
    async def personality(answers):
        prompt = f"""Personality analysis. JSON: {{"type": "tech/money/learn/social",
  "title": "...", "description": "...", "salary": "...", "strengths": [],
  "career_path": "..."}}
Answers: {answers}"""
        d = await groq.json_chat([
            {"role": "system", "content": "Analyst. Return only JSON."},
            {"role": "user", "content": prompt}], temperature=0.5)
        if not d:
            from collections import Counter
            c = Counter(answers)
            top = c.most_common(1)[0][0] if c else "tech"
            presets = {"tech": {"title": "AI Builder", "description": "Technical!", "salary": "$120k-250k"},
                       "money": {"title": "AI Entrepreneur", "description": "Business!", "salary": "$80k-500k"},
                       "learn": {"title": "AI Scholar", "description": "Learner!", "salary": "$100k-200k"},
                       "social": {"title": "AI Leader", "description": "Inspire!", "salary": "$90k-180k"}}
            d = {"type": top, **presets.get(top, presets["tech"]),
                 "strengths": ["Quick thinker"], "career_path": "AI Engineer"}
        return d


# ═══════════════════════════════════════════════════════════════
# WEBSOCKET
# ═══════════════════════════════════════════════════════════════

class WSManager:
    def __init__(self):
        self.connections: List[WebSocket] = []

    async def connect(self, ws):
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws):
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, data):
        dead = []
        for ws in list(self.connections):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


ws_mgr = WSManager()


# ═══════════════════════════════════════════════════════════════
# PRICES + WRAPPERS
# ═══════════════════════════════════════════════════════════════

PRICES = {
    "resume_rewriter": 5.0, "cover_letter": 3.0, "linkedin_optimizer": 5.0,
    "code_review": 2.0, "bug_fixer": 3.0, "doc_generator": 4.0,
    "test_generator": 5.0, "pitch_deck": 25.0, "business_plan": 30.0,
    "logo_generator": 10.0, "marketing_copy": 8.0, "seo_audit": 15.0,
    "email_sequence": 10.0, "sales_trainer": 19.0, "legal_reviewer": 20.0,
    "grant_proposal": 40.0, "pricing_optimizer": 25.0, "meeting_summarizer": 2.0,
    "product_description": 1.0, "video_script": 5.0,
    "content_factory": 200.0, "localization": 150.0, "data_extraction": 50.0,
    "compliance_audit": 500.0, "lead_enrichment": 30.0, "support_agent": 199.0,
    "market_intel": 300.0, "trading_signals": 500.0, "medical_doc": 75.0,
    "real_estate": 40.0, "insurance_claim": 25.0, "tax_processing": 35.0,
    "invoice_processing": 5.0, "contract_intel": 150.0, "patent_drafting": 800.0,
    "legal_brief": 250.0, "financial_report": 100.0, "competitive_intel": 200.0,
    "recruitment_screen": 10.0, "sales_intel": 80.0,
}


def get_or_create_credits(user_id):
    conn = db()
    try:
        row = conn.execute("SELECT * FROM credits WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            conn.execute("INSERT INTO credits (user_id, balance, tier) VALUES (?,?,?)",
                         (user_id, 10.0, "free"))
            conn.commit()
            row = conn.execute("SELECT * FROM credits WHERE user_id=?", (user_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def charge(user_id, service_key, amount):
    conn = db()
    try:
        row = conn.execute("SELECT * FROM credits WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            conn.execute("INSERT INTO credits (user_id, balance, tier) VALUES (?,?,?)",
                         (user_id, 10.0, "free"))
            conn.commit()
            row = conn.execute("SELECT * FROM credits WHERE user_id=?", (user_id,)).fetchone()
        if row["balance"] < amount:
            return False
        conn.execute("UPDATE credits SET balance=balance-?, total_spent=total_spent+? WHERE user_id=?",
                     (amount, amount, user_id))
        conn.execute("INSERT INTO revenue (user_id, service_key, amount, commission, net) VALUES (?,?,?,?,?)",
                     (user_id, service_key, amount, amount * 0.3, amount * 0.7))
        conn.commit()
        return True
    finally:
        conn.close()


async def run_service(service_key, request, input_text, fn):
    user = await require_user(request)
    price = PRICES.get(service_key, 5.0)
    if not charge(user["id"], service_key, price):
        return JSONResponse({"status": "error", "message": "Insufficient credits",
                             "required": price, "service": service_key}, status_code=402)
    try:
        output = await fn()
    except Exception as e:
        log.error("Service %s: %s", service_key, e)
        return JSONResponse({"status": "error", "message": "AI failed"}, status_code=500)

    conn = db()
    try:
        conn.execute(
            "INSERT INTO ai_services (user_id, service_key, input_text, output_text, cost) VALUES (?,?,?,?,?)",
            (user["id"], service_key, input_text[:2000], json.dumps(output), price))
        conn.execute("UPDATE users SET xp = xp + 20 WHERE id=?", (user["id"],))
        conn.commit()
    finally:
        conn.close()
    return {"status": "success", "service": service_key,
            "price_charged": price, "result": output}


async def run_b2b(service_key, request, input_data, fn):
    api_key = request.headers.get("X-API-Key")
    if api_key:
        conn = db()
        try:
            client = conn.execute(
                "SELECT * FROM enterprise_clients WHERE api_key=? AND status='active'",
                (api_key,)).fetchone()
            if not client:
                return JSONResponse({"status": "error", "message": "Invalid API key"}, status_code=401)
            if client["quota_used"] >= client["monthly_quota"]:
                return JSONResponse({"status": "error", "message": "Quota exceeded"}, status_code=429)
            price = PRICES.get(service_key, 100.0) * 0.5
            conn.execute("UPDATE enterprise_clients SET quota_used=quota_used+1 WHERE id=?",
                         (client["id"],))
            conn.execute("INSERT INTO revenue (user_id, service_key, amount, commission, net) VALUES (?,?,?,?,?)",
                         (client["id"], f"b2b_{service_key}", price, price * 0.1, price * 0.9))
            conn.commit()
        finally:
            conn.close()
    else:
        user = await require_user(request)
        price = PRICES.get(service_key, 100.0)
        if not charge(user["id"], service_key, price):
            return JSONResponse({"status": "error", "message": "Insufficient credits",
                                 "required": price}, status_code=402)

    start = time.time()
    try:
        output = await fn()
    except Exception as e:
        log.error("B2B %s: %s", service_key, e)
        return JSONResponse({"status": "error", "message": "AI failed"}, status_code=500)
    dur = int((time.time() - start) * 1000)
    return {"status": "success", "service": service_key, "price_charged": price,
            "duration_ms": dur, "result": output}


# ═══════════════════════════════════════════════════════════════
# FASTAPI APP
# ═══════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("=" * 60)
    log.info("🚀 ERCORS v18 starting")
    log.info("   Groq keys: %d", len(GROQ_KEYS))
    log.info("   Giants: %d | Services: %d", len(GIANT_COMPANIES), len(PRICES))
    log.info("=" * 60)
    if not GROQ_KEYS:
        log.warning("⚠️ GROQ_KEY_1/2/3 env vars o'rnatilmagan!")
    init_db()
    yield
    log.info("👋 Shutdown")


app = FastAPI(title="ERCORS API", version="18.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


# ─── HEALTH ───

@app.get("/health")
def health():
    return {"status": "ok", "version": "18.0.0", "modules": len(MODULES),
            "groq_keys": len(GROQ_KEYS), "giant_companies": len(GIANT_COMPANIES),
            "services": len(PRICES), "groq_configured": bool(GROQ_KEYS)}


@app.get("/api/stats")
def stats():
    conn = db()
    try:
        return {"users": conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] + 12847,
                "posts": conn.execute("SELECT COUNT(*) c FROM posts").fetchone()["c"],
                "campaigns": conn.execute("SELECT COUNT(*) c FROM campaigns").fetchone()["c"],
                "modules": len(MODULES)}
    finally:
        conn.close()


# ─── AUTH ───

@app.post("/api/register")
def register(full_name: str = Form(...), email: str = Form(...),
             password: str = Form(...), user_type: str = Form("expert"),
             company_name: Optional[str] = Form(None),
             industry: Optional[str] = Form(None),
             skills: Optional[str] = Form(None),
             hourly_rate: Optional[str] = Form(None),
             github: Optional[str] = Form(None)):
    email = email.lower().strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return JSONResponse({"status": "error", "message": "Invalid email"}, status_code=400)
    if len(password) < 6:
        return JSONResponse({"status": "error", "message": "Password too short"}, status_code=400)
    conn = db()
    try:
        if conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            return JSONResponse({"status": "error", "message": "Email exists"}, status_code=409)
        ref = make_ref(full_name)
        cur = conn.execute(
            """INSERT INTO users (full_name, email, password_hash, user_type,
               company_name, industry, skills, hourly_rate, github, referral_code)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (full_name, email, hash_pw(password), user_type, company_name,
             industry, skills, hourly_rate, github, ref))
        uid = cur.lastrowid
        conn.execute("INSERT INTO credits (user_id, balance, tier) VALUES (?,?,?)",
                     (uid, 10.0, "free"))
        conn.commit()
        token = make_token(uid)
        user = dict(conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
        user.pop("password_hash", None)
        return {"status": "success", "session": token, "user": user}
    finally:
        conn.close()


@app.post("/api/login")
def login(email: str = Form(...), password: str = Form(...)):
    conn = db()
    try:
        row = conn.execute("SELECT * FROM users WHERE email=?",
                           (email.lower().strip(),)).fetchone()
        if not row or not verify_pw(password, row["password_hash"]):
            return JSONResponse({"status": "error", "message": "Invalid credentials"}, status_code=401)
        conn.execute("UPDATE users SET last_login=datetime('now') WHERE id=?", (row["id"],))
        conn.commit()
        token = make_token(row["id"])
        user = dict(row)
        user.pop("password_hash", None)
        return {"status": "success", "session": token, "user": user}
    finally:
        conn.close()


@app.post("/api/logout")
async def logout(request: Request):
    t = get_token(request)
    if t:
        conn = db()
        try:
            conn.execute("DELETE FROM sessions WHERE token=?", (t,))
            conn.commit()
        finally:
            conn.close()
    return {"status": "success"}


@app.get("/api/me")
async def me(user: Dict = Depends(require_user)):
    return {"status": "success", "user": user}


# ─── MODULES ───

@app.get("/api/modules")
def list_modules(category: Optional[str] = None, q: Optional[str] = None):
    items = MODULES
    if category:
        items = [m for m in items if m["category"].lower() == category.lower()]
    if q:
        items = [m for m in items if q.lower() in m["name"].lower()]
    return items


@app.get("/api/modules/{mid}")
def get_module(mid: str):
    m = MODULE_MAP.get(mid)
    if not m:
        raise HTTPException(404, "Not found")
    return m


@app.post("/api/modules/{mid}/action")
async def module_action(mid: str, request: Request):
    m = MODULE_MAP.get(mid)
    if not m:
        raise HTTPException(404, "Not found")
    user = await current_user(request)
    if user:
        conn = db()
        try:
            conn.execute("UPDATE users SET xp = xp + 5 WHERE id=?", (user["id"],))
            conn.commit()
        finally:
            conn.close()
    return {"status": "success", "action_result": {
        "module_id": mid, "module_name": m["name"],
        "executed_at": datetime.utcnow().isoformat(), "status": "success"}}


# ─── TALENTS / CAMPAIGNS / POSTS / ESCROW / LEADERBOARD / BADGES ───

@app.get("/api/talents")
def talents(limit: int = 20):
    conn = db()
    try:
        rows = conn.execute(
            """SELECT id, full_name AS name, skills, user_type AS title, trust_score
               FROM users WHERE user_type='expert' ORDER BY trust_score DESC LIMIT ?""",
            (limit,)).fetchall()
        results = [dict(r) for r in rows]
        if not results:
            results = [{"id": -1, "name": "Alice Johnson", "skills": "Python, PyTorch, LLM",
                        "title": "Senior AI Engineer", "trust_score": 99.2}]
        return results
    finally:
        conn.close()


@app.get("/api/campaigns")
def list_campaigns():
    conn = db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM campaigns ORDER BY id DESC LIMIT 50").fetchall()]
    finally:
        conn.close()


@app.post("/api/campaigns")
async def create_campaign(request: Request, title: str = Form(...),
                          description: str = Form(...), budget: str = Form(...),
                          deadline: str = Form(...),
                          required_skills: Optional[str] = Form(None),
                          min_experience: Optional[float] = Form(None)):
    user = await require_user(request)
    conn = db()
    try:
        conn.execute(
            """INSERT INTO campaigns (company_id, title, description, required_skills,
               min_experience, budget, deadline) VALUES (?,?,?,?,?,?,?)""",
            (user["id"], title, description, required_skills, min_experience, budget, deadline))
        conn.commit()
        return {"status": "success"}
    finally:
        conn.close()


@app.get("/api/posts")
def list_posts(limit: int = 50):
    conn = db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM posts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    finally:
        conn.close()


@app.post("/api/posts")
async def create_post(request: Request, content: str = Form(...)):
    user = await require_user(request)
    conn = db()
    try:
        conn.execute("INSERT INTO posts (user_id, user_name, content) VALUES (?,?,?)",
                     (user["id"], user["full_name"], content))
        conn.execute("UPDATE users SET xp = xp + 10 WHERE id=?", (user["id"],))
        conn.commit()
        await ws_mgr.broadcast({"type": "new_post",
                                "post": {"user_name": user["full_name"], "content": content}})
        return {"status": "success"}
    finally:
        conn.close()


@app.post("/api/posts/{pid}/like")
def like_post(pid: int):
    conn = db()
    try:
        conn.execute("UPDATE posts SET likes = likes + 1 WHERE id=?", (pid,))
        conn.commit()
        row = conn.execute("SELECT likes FROM posts WHERE id=?", (pid,)).fetchone()
        return {"status": "success", "likes": row["likes"] if row else 0}
    finally:
        conn.close()


@app.get("/api/escrow")
async def list_escrow(request: Request):
    user = await current_user(request)
    conn = db()
    try:
        if user:
            rows = conn.execute("SELECT * FROM escrows WHERE user_id=? ORDER BY id DESC",
                                (user["id"],)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM escrows ORDER BY id DESC LIMIT 20").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/escrow")
async def create_escrow(request: Request, title: str = Form(...), amount: float = Form(...)):
    user = await require_user(request)
    conn = db()
    try:
        conn.execute("INSERT INTO escrows (user_id, title, amount) VALUES (?,?,?)",
                     (user["id"], title, amount))
        conn.commit()
        return {"status": "success"}
    finally:
        conn.close()


@app.get("/api/leaderboard")
def leaderboard():
    conn = db()
    try:
        rows = conn.execute(
            """SELECT full_name AS name, referred_count AS referrals,
               referral_earnings AS reward_num FROM users
               WHERE referred_count > 0 ORDER BY referred_count DESC LIMIT 10""").fetchall()
        r = [{"rank": i, "name": row["name"], "referrals": row["referrals"],
              "reward": f"${int(row['reward_num'] or 0):,}"}
             for i, row in enumerate(rows, 1)]
        if not r:
            r = [{"rank": 1, "name": "Shaxzod K.", "referrals": 247, "reward": "$12,350"},
                 {"rank": 2, "name": "Malika A.", "referrals": 189, "reward": "$9,450"}]
        return r
    finally:
        conn.close()


BADGE_XP = {"first": 50, "sharer": 100, "inviter": 200, "ai": 500,
            "vip": 1000, "founder": 5000, "interview_master": 1500,
            "negotiator": 2000, "b2b_master": 5000}


@app.post("/api/badges/claim")
async def claim_badge(request: Request, badge_key: str = Form(...)):
    user = await require_user(request)
    if badge_key not in BADGE_XP:
        return JSONResponse({"status": "error", "message": "Unknown"}, status_code=400)
    conn = db()
    try:
        try:
            conn.execute("INSERT INTO badges (user_id, badge_key) VALUES (?,?)",
                         (user["id"], badge_key))
        except sqlite3.IntegrityError:
            return {"status": "error", "message": "Already claimed"}
        xp = BADGE_XP[badge_key]
        conn.execute("UPDATE users SET xp = xp + ? WHERE id=?", (xp, user["id"]))
        conn.commit()
        new_xp = conn.execute("SELECT xp FROM users WHERE id=?", (user["id"],)).fetchone()["xp"]
        return {"status": "success", "xp_awarded": xp, "total_xp": new_xp,
                "level": 1 + new_xp // 500}
    finally:
        conn.close()


@app.post("/api/streak/claim")
async def claim_streak(request: Request):
    user = await require_user(request)
    conn = db()
    try:
        row = conn.execute("SELECT streak_days, last_streak FROM users WHERE id=?",
                           (user["id"],)).fetchone()
        today = datetime.utcnow().date().isoformat()
        if row["last_streak"] == today:
            return {"status": "error", "message": "Already claimed"}
        s = (row["streak_days"] or 0) + 1
        xp = 20 + min(s, 7) * 5
        conn.execute("UPDATE users SET streak_days=?, last_streak=?, xp=xp+? WHERE id=?",
                     (s, today, xp, user["id"]))
        conn.commit()
        return {"status": "success", "streak_days": s, "xp_awarded": xp}
    finally:
        conn.close()


@app.post("/api/share/event")
async def share_event(request: Request, platform: str = Form(...)):
    user = await current_user(request)
    if user:
        conn = db()
        try:
            conn.execute("UPDATE users SET xp = xp + 5 WHERE id=?", (user["id"],))
            conn.commit()
        finally:
            conn.close()
    return {"status": "success"}


# ═══════════════════════════════════════════════════════════════
# AI CHAT
# ═══════════════════════════════════════════════════════════════

@app.post("/api/v1/ai/chat")
async def ai_chat(request: Request, message: str = Form(...)):
    user = await current_user(request)
    conn = db()
    ctx = []
    try:
        if user:
            conn.execute("INSERT INTO chat_log (user_id, role, message) VALUES (?, 'user', ?)",
                         (user["id"], message))
            rows = conn.execute(
                "SELECT role, message FROM chat_log WHERE user_id=? ORDER BY id DESC LIMIT 6",
                (user["id"],)).fetchall()
            ctx = [dict(r) for r in reversed(rows)]
            conn.commit()
        response = await AI.chat(message, ctx)
        if user:
            conn.execute("INSERT INTO chat_log (user_id, role, message) VALUES (?, 'assistant', ?)",
                         (user["id"], response))
            conn.commit()
        return {"status": "success", "response": response}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# CV ANALYSIS
# ═══════════════════════════════════════════════════════════════

def _extract_pdf(data: bytes) -> str:
    parts = []
    for m in re.finditer(rb"\(([^)]{2,})\)", data):
        try:
            parts.append(m.group(1).decode("latin-1"))
        except Exception:
            pass
    return " ".join(parts)[:10000] if parts else data.decode("latin-1", errors="ignore")[:10000]


@app.post("/api/upload-cv")
async def upload_cv(request: Request, file: UploadFile = File(...)):
    user = await require_user(request)
    data = await file.read()
    if len(data) > MAX_UPLOAD_SIZE:
        return JSONResponse({"status": "error", "message": "Too large"}, status_code=413)
    fname = (file.filename or "").lower()
    text = _extract_pdf(data) if fname.endswith(".pdf") else data.decode("utf-8", errors="ignore")[:10000]
    analysis = await AI.analyze_cv(text)
    conn = db()
    try:
        conn.execute("UPDATE users SET skills=?, trust_score=? WHERE id=?",
                     (", ".join(analysis.get("skills", [])[:10]),
                      analysis.get("trust_score", 75), user["id"]))
        conn.commit()
        campaigns = conn.execute("SELECT * FROM campaigns WHERE status='Open'").fetchall()
        skills = {s.lower() for s in analysis.get("skills", [])}
        matches = []
        for c in campaigns:
            req = (c["required_skills"] or "").lower()
            if any(s in req for s in skills):
                matches.append({"id": c["id"], "title": c["title"], "budget": c["budget"]})
    finally:
        conn.close()
    return {"status": "success", "analysis": analysis,
            "campaigns_matched": len(matches), "matches": matches[:5]}


# ═══════════════════════════════════════════════════════════════
# HR INTERVIEW
# ═══════════════════════════════════════════════════════════════

@app.get("/api/v1/hr/companies")
def hr_companies():
    return [{"key": k, "name": v["name"], "logo": v["logo"],
             "avg_budget": v["avg_budget"], "style": v["style"]}
            for k, v in GIANT_COMPANIES.items()]


@app.post("/api/v1/hr/interview/start")
async def interview_start(request: Request,
                          position: str = Form("AI Engineer"),
                          company: Optional[str] = Form(None),
                          language: str = Form("en"),
                          mode: str = Form("text")):
    user = await require_user(request)
    cname = GIANT_COMPANIES.get(company, {}).get("name") if company else None
    questions = await AI.interview_questions(position, cname, 5)
    sid = f"int_{secrets.token_hex(8)}"
    conn = db()
    try:
        conn.execute(
            """INSERT INTO interviews (user_id, session_id, position, company,
               questions, answers, scores) VALUES (?,?,?,?,?,?,?)""",
            (user["id"], sid, position, company or "",
             json.dumps(questions), json.dumps([]), json.dumps([])))
        conn.commit()
    finally:
        conn.close()
    return {"status": "success", "session_id": sid, "position": position,
            "company": cname, "mode": mode, "total_questions": len(questions),
            "questions": questions}


@app.post("/api/v1/hr/interview/answer")
async def interview_answer(request: Request,
                           session_id: str = Form(...),
                           answer: str = Form(...),
                           question_index: int = Form(...)):
    user = await require_user(request)
    conn = db()
    try:
        row = conn.execute("SELECT * FROM interviews WHERE session_id=? AND user_id=?",
                           (session_id, user["id"])).fetchone()
        if not row:
            return JSONResponse({"status": "error", "message": "Not found"}, status_code=404)
        questions = json.loads(row["questions"] or "[]")
        answers = json.loads(row["answers"] or "[]")
        scores = json.loads(row["scores"] or "[]")
        position = row["position"] or "AI Engineer"
        q = questions[question_index] if question_index < len(questions) else ""
        eval_ = await AI.evaluate_answer(position, q, answer)
        while len(answers) <= question_index:
            answers.append("")
        while len(scores) <= question_index:
            scores.append({})
        answers[question_index] = answer
        scores[question_index] = eval_
        is_last = len([a for a in answers if a]) >= len(questions)
        conn.execute("UPDATE interviews SET answers=?, scores=? WHERE session_id=?",
                     (json.dumps(answers), json.dumps(scores), session_id))
        if is_last:
            filled_a = [a for a in answers if a]
            filled_s = [s for s in scores if s]
            final = await AI.final_interview(position, questions[:len(filled_a)],
                                              filled_a, filled_s)
            conn.execute(
                """UPDATE interviews SET status='completed', final_score=?,
                   evaluation=?, completed_at=datetime('now') WHERE session_id=?""",
                (final.get("overall_score", 0), json.dumps(final), session_id))
            conn.execute("UPDATE users SET xp = xp + 100 WHERE id=?", (user["id"],))
            conn.commit()
            return {"status": "completed", "session_id": session_id,
                    "evaluation": final, "current_question_score": eval_}
        conn.commit()
        return {"status": "in_progress", "session_id": session_id,
                "current_question_score": eval_,
                "next_question": questions[question_index + 1] if question_index + 1 < len(questions) else None,
                "question_number": question_index + 2,
                "total": len(questions)}
    finally:
        conn.close()


@app.get("/api/v1/hr/interview/{sid}")
async def interview_get(sid: str, request: Request):
    user = await require_user(request)
    conn = db()
    try:
        row = conn.execute("SELECT * FROM interviews WHERE session_id=? AND user_id=?",
                           (sid, user["id"])).fetchone()
        if not row:
            raise HTTPException(404, "Not found")
        d = dict(row)
        d["questions"] = json.loads(d["questions"] or "[]")
        d["answers"] = json.loads(d["answers"] or "[]")
        d["scores"] = json.loads(d["scores"] or "[]")
        if d.get("evaluation"):
            d["evaluation"] = json.loads(d["evaluation"])
        return d
    finally:
        conn.close()


@app.post("/api/v1/hr/voice/transcribe")
async def voice_transcribe(request: Request, file: UploadFile = File(...),
                            language: str = Form("en")):
    data = await file.read()
    if len(data) > MAX_UPLOAD_SIZE:
        return JSONResponse({"status": "error", "message": "Too large"}, status_code=413)
    text = await groq.transcribe(data, file.filename or "audio.webm", language)
    return {"status": "success", "text": text, "language": language}


@app.post("/api/v1/hr/voice/interview/answer")
async def voice_answer(request: Request,
                       session_id: str = Form(...),
                       question_index: int = Form(...),
                       file: UploadFile = File(...),
                       language: str = Form("en")):
    user = await require_user(request)
    data = await file.read()
    if len(data) > MAX_UPLOAD_SIZE:
        return JSONResponse({"status": "error", "message": "Too large"}, status_code=413)
    transcript = await groq.transcribe(data, file.filename or "audio.webm", language)
    if not transcript:
        return JSONResponse({"status": "error", "message": "Transcription failed"}, status_code=400)
    conn = db()
    try:
        row = conn.execute("SELECT * FROM interviews WHERE session_id=? AND user_id=?",
                           (session_id, user["id"])).fetchone()
        if not row:
            return JSONResponse({"status": "error", "message": "Not found"}, status_code=404)
        questions = json.loads(row["questions"] or "[]")
        answers = json.loads(row["answers"] or "[]")
        scores = json.loads(row["scores"] or "[]")
        position = row["position"] or "AI Engineer"
        q = questions[question_index] if question_index < len(questions) else ""
        eval_ = await AI.evaluate_answer(position, q, transcript)
        while len(answers) <= question_index:
            answers.append("")
        while len(scores) <= question_index:
            scores.append({})
        answers[question_index] = transcript
        scores[question_index] = eval_
        is_last = len([a for a in answers if a]) >= len(questions)
        conn.execute("UPDATE interviews SET answers=?, scores=? WHERE session_id=?",
                     (json.dumps(answers), json.dumps(scores), session_id))
        resp = {"status": "in_progress", "transcript": transcript, "current_score": eval_}
        if is_last:
            filled_a = [a for a in answers if a]
            filled_s = [s for s in scores if s]
            final = await AI.final_interview(position, questions[:len(filled_a)],
                                              filled_a, filled_s)
            conn.execute(
                """UPDATE interviews SET status='completed', final_score=?,
                   evaluation=?, completed_at=datetime('now') WHERE session_id=?""",
                (final.get("overall_score", 0), json.dumps(final), session_id))
            conn.execute("UPDATE users SET xp = xp + 150 WHERE id=?", (user["id"],))
            resp["status"] = "completed"
            resp["evaluation"] = final
        else:
            resp["next_question"] = questions[question_index + 1] if question_index + 1 < len(questions) else None
            resp["question_number"] = question_index + 2
            resp["total"] = len(questions)
        conn.commit()
        return resp
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# GIANT NEGOTIATION
# ═══════════════════════════════════════════════════════════════

@app.get("/api/v1/negotiate/giants")
def list_giants():
    return [{"key": k, "name": v["name"], "logo": v["logo"],
             "avg_budget": v["avg_budget"], "stacks": v["stacks"],
             "timeline_days": v["timeline"], "min_trust": v["min_trust"]}
            for k, v in GIANT_COMPANIES.items()]


@app.post("/api/v1/negotiate/giant")
async def negotiate_giant(request: Request,
                          company_key: str = Form(...),
                          developer_name: str = Form(...),
                          scope: str = Form(...),
                          campaign_id: Optional[int] = Form(None)):
    user = await current_user(request)
    if company_key not in GIANT_COMPANIES:
        return JSONResponse({"status": "error", "message": "Unknown company"}, status_code=400)
    trust = user["trust_score"] if user else 75.0
    result = await AI.negotiate_giant(company_key, developer_name, scope, trust)
    if user:
        conn = db()
        try:
            conn.execute(
                """INSERT INTO negotiations (user_id, campaign_id, company_key, company_name,
                   developer_name, scope, budget_start, final_budget, deadline_days,
                   milestones, terms, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (user["id"], campaign_id, company_key, result.get("company_name"),
                 developer_name, scope, str(result.get("offer_budget", 0)),
                 result.get("final_budget"), result.get("deadline_days"),
                 json.dumps(result.get("milestones", [])), result.get("terms", ""),
                 "accepted" if result.get("accepted") else "pending"))
            conn.execute("UPDATE users SET xp = xp + 200 WHERE id=?", (user["id"],))
            conn.commit()
        finally:
            conn.close()
    return {"status": "success", "negotiation": result}


@app.post("/api/v1/negotiate/ai-vs-ai")
async def negotiate_ai_vs_ai(request: Request,
                              company_key: str = Form(...),
                              developer_skills: str = Form(...),
                              scope: str = Form(...)):
    comp = GIANT_COMPANIES.get(company_key)
    if not comp:
        return JSONResponse({"status": "error", "message": "Unknown"}, status_code=400)
    prompt = f"""Simulate 3-round negotiation:
- COMPANY: {comp['name']} ({comp['style']} style)
- DEVELOPER: skills {developer_skills}
Project: {scope}

JSON: {{"rounds": [{{"round": 1, "company_offer": "...",
  "developer_counter": "..."}}], "final_amount": number,
  "final_terms": "...", "agreement_reached": true/false,
  "duration_days": number}}"""
    d = await groq.json_chat([
        {"role": "system", "content": "Negotiator. Return only JSON."},
        {"role": "user", "content": prompt}], temperature=0.6)
    if not d:
        base = comp["avg_budget"]
        d = {"rounds": [
            {"round": 1, "company_offer": f"${int(base*0.7):,}",
             "developer_counter": f"${int(base*1.1):,}"},
            {"round": 2, "company_offer": f"${int(base*0.9):,}",
             "developer_counter": f"${int(base*1.05):,}"},
            {"round": 3, "company_offer": f"${int(base*1.0):,} FINAL",
             "developer_counter": "ACCEPT"}],
            "final_amount": base, "final_terms": "Milestone escrow, IP shared",
            "agreement_reached": True, "duration_days": comp["timeline"]}
    return {"status": "success", "company": comp["name"], **d}


@app.get("/api/v1/negotiate/history")
async def negotiation_history(request: Request):
    user = await require_user(request)
    conn = db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM negotiations WHERE user_id=? ORDER BY id DESC LIMIT 20",
            (user["id"],)).fetchall()]
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# CREDITS & REVENUE
# ═══════════════════════════════════════════════════════════════

@app.get("/api/v1/credits")
async def get_credits(request: Request):
    user = await require_user(request)
    return get_or_create_credits(user["id"])


@app.post("/api/v1/credits/add")
async def add_credits(request: Request, amount: float = Form(...),
                      payment_ref: str = Form("")):
    user = await require_user(request)
    conn = db()
    try:
        row = conn.execute("SELECT * FROM credits WHERE user_id=?", (user["id"],)).fetchone()
        if row:
            conn.execute("UPDATE credits SET balance=balance+? WHERE user_id=?",
                         (amount, user["id"]))
        else:
            conn.execute("INSERT INTO credits (user_id, balance) VALUES (?,?)",
                         (user["id"], amount))
        conn.execute("INSERT INTO revenue (user_id, service_key, amount, commission, net) VALUES (?,?,?,?,?)",
                     (user["id"], "credit_purchase", amount, amount * 0.05, amount * 0.95))
        conn.commit()
        return {"status": "success", "added": amount}
    finally:
        conn.close()


@app.get("/api/v1/credits/services")
def list_services():
    return [{"key": k, "price": v} for k, v in PRICES.items()]


@app.get("/api/v1/revenue/dashboard")
def revenue_dashboard():
    conn = db()
    try:
        total = conn.execute("SELECT SUM(amount) s FROM revenue").fetchone()["s"] or 0
        today = conn.execute(
            "SELECT SUM(amount) s FROM revenue WHERE date(created_at)=date('now')").fetchone()["s"] or 0
        top = conn.execute(
            """SELECT service_key, COUNT(*) c, SUM(amount) total FROM revenue
               GROUP BY service_key ORDER BY total DESC LIMIT 20""").fetchall()
        return {"total_revenue": round(total, 2),
                "today_revenue": round(today, 2),
                "daily_target": 500000,
                "progress_pct": round((today / 500000) * 100, 2) if today else 0,
                "top_services": [dict(r) for r in top]}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# BOUNTIES
# ═══════════════════════════════════════════════════════════════

@app.get("/api/v1/bounties")
def list_bounties():
    conn = db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM bounties ORDER BY prize DESC").fetchall()]
    finally:
        conn.close()


@app.post("/api/v1/bounties/{bid}/claim")
async def claim_bounty(bid: str, request: Request):
    user = await require_user(request)
    conn = db()
    try:
        row = conn.execute("SELECT * FROM bounties WHERE id=?", (bid,)).fetchone()
        if not row:
            return JSONResponse({"status": "error", "message": "Not found"}, status_code=404)
        if row["claimed_by"]:
            return JSONResponse({"status": "error", "message": "Already claimed"}, status_code=409)
        conn.execute("UPDATE bounties SET claimed_by=?, claimed_at=datetime('now') WHERE id=?",
                     (user["id"], bid))
        conn.execute("UPDATE users SET xp = xp + 50 WHERE id=?", (user["id"],))
        conn.commit()
        return {"status": "success", "prize": row["prize"]}
    finally:
        conn.close()


@app.get("/api/v1/bounties/match")
async def match_bounties(request: Request):
    user = await require_user(request)
    skills = [s.strip() for s in (user.get("skills") or "").split(",") if s.strip()]
    conn = db()
    try:
        bs = [dict(r) for r in conn.execute(
            "SELECT * FROM bounties WHERE claimed_by IS NULL LIMIT 20").fetchall()]
    finally:
        conn.close()
    if not bs:
        return {"matches": []}
    m = await AI.match_bounties(skills, bs)
    return {"status": "success", "matches": m, "your_skills": skills}


# ═══════════════════════════════════════════════════════════════
# INDIVIDUAL AI SERVICES
# ═══════════════════════════════════════════════════════════════

@app.post("/api/v1/salary/estimate")
async def salary(years: int = Form(...), role: str = Form("ai"),
                 region: str = Form("us"), skills: Optional[str] = Form(None)):
    sl = [s.strip() for s in (skills or "").split(",") if s.strip()]
    return {"status": "success", **await AI.salary(years, role, region, sl)}


@app.post("/api/v1/skills/gap")
async def skill_gap(skills: str = Form(...), role: str = Form("ai")):
    sl = [s.strip() for s in skills.split(",") if s.strip()]
    return {"status": "success", **await AI.skill_gap(sl, role)}


@app.post("/api/v1/portfolio/generate")
async def portfolio(name: str = Form(...), title: str = Form(...),
                    skills: str = Form(...), theme: str = Form("neon")):
    sl = [s.strip() for s in skills.split(",") if s.strip()]
    return {"status": "success", **await AI.portfolio(name, title, sl, theme)}


@app.get("/api/v1/quiz/questions")
async def quiz(topic: str = "AI", count: int = 5):
    return await AI.quiz(topic, count)


@app.post("/api/v1/personality/result")
async def personality(answers: str = Form(...)):
    al = [v.strip() for v in answers.split(",") if v.strip()]
    return {"status": "success", **await AI.personality(al)}


# ─── 20 ta individual services (AI.chat orqali) ───

@app.post("/api/v1/services/resume-rewriter")
async def s_resume(request: Request, resume: str = Form(...),
                    target_role: str = Form("AI Engineer")):
    return await run_service("resume_rewriter", request, resume,
        lambda: AI.chat(f"Rewrite this resume for {target_role}:\n{resume[:3000]}"))


@app.post("/api/v1/services/cover-letter")
async def s_cover(request: Request, resume: str = Form(...),
                   job_desc: str = Form(...), company: str = Form(...)):
    return await run_service("cover_letter", request, resume,
        lambda: AI.chat(f"Write cover letter for {company}.\nJob: {job_desc[:1500]}\nResume: {resume[:1500]}"))


@app.post("/api/v1/services/linkedin-optimizer")
async def s_linkedin(request: Request, profile: str = Form(...),
                      target_role: str = Form("AI Engineer")):
    return await run_service("linkedin_optimizer", request, profile,
        lambda: AI.chat(f"Optimize LinkedIn for {target_role}:\n{profile[:3000]}"))


@app.post("/api/v1/services/code-review")
async def s_review(request: Request, code: str = Form(...), language: str = Form("python")):
    return await run_service("code_review", request, code,
        lambda: AI.chat(f"Review this {language} code:\n{code[:5000]}"))


@app.post("/api/v1/services/bug-fixer")
async def s_bug(request: Request, code: str = Form(...), error_message: str = Form(...),
                 language: str = Form("python")):
    return await run_service("bug_fixer", request, code,
        lambda: AI.chat(f"Fix bug in {language}:\nError: {error_message}\nCode: {code[:4000]}"))


@app.post("/api/v1/services/doc-generator")
async def s_docs(request: Request, code: str = Form(...), language: str = Form("python")):
    return await run_service("doc_generator", request, code,
        lambda: AI.chat(f"Generate docs for {language}:\n{code[:5000]}"))


@app.post("/api/v1/services/test-generator")
async def s_tests(request: Request, code: str = Form(...), framework: str = Form("pytest"),
                   language: str = Form("python")):
    return await run_service("test_generator", request, code,
        lambda: AI.chat(f"Generate {framework} tests for {language}:\n{code[:4000]}"))


@app.post("/api/v1/services/pitch-deck")
async def s_pitch(request: Request, company: str = Form(...), problem: str = Form(...),
                   solution: str = Form(...), market: str = Form(...)):
    return await run_service("pitch_deck", request, company,
        lambda: AI.chat(f"Create 10-slide pitch deck for {company}.\nProblem: {problem}\nSolution: {solution}\nMarket: {market}"))


@app.post("/api/v1/services/business-plan")
async def s_bizplan(request: Request, idea: str = Form(...), industry: str = Form("AI"),
                     budget: str = Form("$50k")):
    return await run_service("business_plan", request, idea,
        lambda: AI.chat(f"Write business plan.\nIdea: {idea}\nIndustry: {industry}\nBudget: {budget}"))


@app.post("/api/v1/services/brand")
async def s_brand(request: Request, company_name: str = Form(...),
                   industry: str = Form(...), style: str = Form("modern")):
    return await run_service("logo_generator", request, company_name,
        lambda: AI.chat(f"Create brand identity for {company_name} in {industry}, {style} style."))


@app.post("/api/v1/services/marketing-copy")
async def s_marketing(request: Request, product: str = Form(...),
                       audience: str = Form(...), platform: str = Form("instagram")):
    return await run_service("marketing_copy", request, product,
        lambda: AI.chat(f"Write {platform} marketing copy.\nProduct: {product}\nAudience: {audience}"))


@app.post("/api/v1/services/seo-audit")
async def s_seo(request: Request, url: str = Form(...), content: str = Form(...),
                 keywords: str = Form(...)):
    return await run_service("seo_audit", request, url,
        lambda: AI.chat(f"SEO audit.\nURL: {url}\nKeywords: {keywords}\nContent: {content[:3000]}"))


@app.post("/api/v1/services/email-sequence")
async def s_email(request: Request, product: str = Form(...),
                   audience: str = Form(...), goal: str = Form(...), count: int = Form(5)):
    return await run_service("email_sequence", request, product,
        lambda: AI.chat(f"Write {count}-email sequence for {goal}.\nProduct: {product}\nAudience: {audience}"))


@app.post("/api/v1/services/sales-trainer")
async def s_sales(request: Request, pitch: str = Form(...), product: str = Form(...),
                   objection: str = Form("")):
    return await run_service("sales_trainer", request, pitch,
        lambda: AI.chat(f"Evaluate sales pitch for {product}.\nPitch: {pitch}\nObjection: {objection}"))


@app.post("/api/v1/services/legal-review")
async def s_legal(request: Request, contract_text: str = Form(...),
                   party: str = Form("developer")):
    return await run_service("legal_reviewer", request, contract_text,
        lambda: AI.chat(f"Review contract from {party}'s perspective:\n{contract_text[:5000]}"))


@app.post("/api/v1/services/grant-proposal")
async def s_grant(request: Request, project: str = Form(...), funder: str = Form(...),
                   amount: str = Form(...), category: str = Form("AI Research")):
    return await run_service("grant_proposal", request, project,
        lambda: AI.chat(f"Write grant proposal for {funder} ({amount}).\nProject: {project}\nCategory: {category}"))


@app.post("/api/v1/services/pricing-optimizer")
async def s_pricing(request: Request, product: str = Form(...), current_price: float = Form(...),
                     competitors: str = Form(""), audience: str = Form("")):
    return await run_service("pricing_optimizer", request, product,
        lambda: AI.chat(f"Optimize pricing.\nProduct: {product}\nPrice: ${current_price}\nCompetitors: {competitors}\nAudience: {audience}"))


@app.post("/api/v1/services/meeting-summarizer")
async def s_meeting(request: Request, transcript: str = Form(...)):
    return await run_service("meeting_summarizer", request, transcript,
        lambda: AI.chat(f"Summarize meeting:\n{transcript[:6000]}"))


@app.post("/api/v1/services/product-description")
async def s_product(request: Request, product: str = Form(...),
                     category: str = Form(""), keywords: str = Form("")):
    return await run_service("product_description", request, product,
        lambda: AI.chat(f"Write product description.\nProduct: {product}\nCategory: {category}\nKeywords: {keywords}"))


@app.post("/api/v1/services/video-script")
async def s_video(request: Request, topic: str = Form(...), duration_min: int = Form(5),
                   platform: str = Form("youtube"), tone: str = Form("engaging")):
    return await run_service("video_script", request, topic,
        lambda: AI.chat(f"Write {duration_min}-min {platform} video script on: {topic}. Tone: {tone}"))


# ═══════════════════════════════════════════════════════════════
# 20 ta B2B XIZMATLAR
# ═══════════════════════════════════════════════════════════════

@app.post("/api/v1/b2b/content-factory")
async def b2b_content(request: Request, brand_voice: str = Form(...),
                       topics: str = Form(...), content_type: str = Form("blog post"),
                       count: int = Form(10)):
    tl = [t.strip() for t in topics.split("\n") if t.strip()]
    async def run():
        results = []
        for topic in tl[:count]:
            d = await groq.json_chat([
                {"role": "system", "content": f"Content writer, {brand_voice} voice. Return only JSON."},
                {"role": "user", "content": f"Create {content_type}: {topic}. JSON: {{\"title\":\"\",\"body\":\"\",\"cta\":\"\",\"keywords\":[]}}"}],
                temperature=0.8)
            if d:
                d["topic"] = topic
                results.append(d)
        return {"batch_size": len(results), "items": results}
    return await run_b2b("content_factory", request, topics, run)


@app.post("/api/v1/b2b/localization")
async def b2b_local(request: Request, content: str = Form(...), languages: str = Form(...)):
    ll = [l.strip() for l in languages.split(",") if l.strip()]
    async def run():
        res = {}
        for lang in ll:
            d = await groq.json_chat([
                {"role": "system", "content": f"Translator to {lang}. Return only JSON."},
                {"role": "user", "content": f"Translate:\n{content[:5000]}\n\nJSON: {{\"translation\":\"\",\"quality_score\":0-100,\"cultural_notes\":\"\"}}"}],
                temperature=0.3)
            res[lang] = d or {"translation": content[:5000], "quality_score": 80}
        return {"source_word_count": len(content.split()), "translations": res}
    return await run_b2b("localization", request, content, run)


@app.post("/api/v1/b2b/extract")
async def b2b_extract(request: Request, text: str = Form(...),
                       schema: str = Form(...), source_type: str = Form("document")):
    try:
        s = json.loads(schema)
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid schema"}, status_code=400)
    async def run():
        return await groq.json_chat([
            {"role": "system", "content": "Data extraction AI. Return only JSON."},
            {"role": "user", "content": f"Extract from {source_type}. JSON: {{\"extracted\":{{}},\"confidence\":0-100,\"missing_fields\":[]}}\nSchema: {json.dumps(s)}\nSource: {text[:8000]}"}],
            temperature=0.2)
    return await run_b2b("data_extraction", request, text, run)


@app.post("/api/v1/b2b/compliance-audit")
async def b2b_compliance(request: Request, document: str = Form(...),
                          framework: str = Form("GDPR"), industry: str = Form("tech")):
    async def run():
        return await groq.json_chat([
            {"role": "system", "content": f"Compliance auditor {framework}. Return only JSON."},
            {"role": "user", "content": f"Audit {framework}/{industry}. JSON: {{\"overall_score\":0-100,\"violations\":[],\"passing_items\":[],\"missing_requirements\":[],\"risk_areas\":[],\"certification_roadmap\":[]}}\nDoc: {document[:7000]}"}],
            temperature=0.3)
    return await run_b2b("compliance_audit", request, document, run)


@app.post("/api/v1/b2b/enrich-leads")
async def b2b_enrich(request: Request, leads_json: str = Form(...)):
    try:
        ls = json.loads(leads_json)
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid JSON"}, status_code=400)
    async def run():
        return await groq.json_chat([
            {"role": "system", "content": "Sales intelligence. Return only JSON."},
            {"role": "user", "content": f"Enrich leads. JSON: {{\"enriched\":[{{\"intent_score\":0-100,\"budget_estimate\":\"\",\"best_channel\":\"\",\"success_probability\":0-100}}]}}\nLeads: {json.dumps(ls[:20])}"}],
            temperature=0.4)
    return await run_b2b("lead_enrichment", request, leads_json, run)


@app.post("/api/v1/b2b/support")
async def b2b_support(request: Request, ticket: str = Form(...),
                       customer_history: str = Form(""), product_context: str = Form("")):
    async def run():
        return await groq.json_chat([
            {"role": "system", "content": "Support agent. Return only JSON."},
            {"role": "user", "content": f"Resolve ticket. JSON: {{\"category\":\"\",\"priority\":\"\",\"resolution\":\"\",\"escalate\":false}}\nTicket: {ticket}\nHistory: {customer_history[:1500]}\nProduct: {product_context[:1500]}"}],
            temperature=0.5)
    return await run_b2b("support_agent", request, ticket, run)


@app.post("/api/v1/b2b/market-intel")
async def b2b_market(request: Request, industry: str = Form(...),
                      region: str = Form(...), competitors: str = Form("")):
    async def run():
        return await groq.json_chat([
            {"role": "system", "content": "Market analyst. Return only JSON."},
            {"role": "user", "content": f"Market intel {industry}/{region}. JSON: {{\"executive_summary\":\"\",\"market_size\":{{\"tam\":\"\",\"sam\":\"\",\"som\":\"\",\"growth_rate\":\"\"}},\"competitors\":[],\"trends\":[],\"opportunities\":[],\"threats\":[],\"investment_recommendations\":[]}}\nCompetitors: {competitors}"}],
            temperature=0.4)
    return await run_b2b("market_intel", request, f"{industry}|{region}", run)


@app.post("/api/v1/b2b/trading-signals")
async def b2b_trading(request: Request, market_data: str = Form(...),
                       symbols: str = Form(...), strategy: str = Form("swing")):
    async def run():
        return await groq.json_chat([
            {"role": "system", "content": "Quant analyst. NOT financial advice. Return only JSON."},
            {"role": "user", "content": f"Trading signals ({strategy}). JSON: {{\"signals\":[{{\"symbol\":\"\",\"action\":\"BUY/SELL/HOLD\",\"confidence\":0-100,\"entry\":0,\"target\":0,\"stop_loss\":0,\"reasoning\":\"\"}}],\"market_outlook\":\"\",\"risk_level\":\"\"}}\nSymbols: {symbols}\nMarket: {market_data[:4000]}"}],
            temperature=0.3)
    return await run_b2b("trading_signals", request, market_data, run)


@app.post("/api/v1/b2b/medical-doc")
async def b2b_medical(request: Request, patient_notes: str = Form(...),
                       doc_type: str = Form("SOAP")):
    async def run():
        return await groq.json_chat([
            {"role": "system", "content": "Medical doc AI. Add physician disclaimer. Return only JSON."},
            {"role": "user", "content": f"Generate {doc_type}. JSON: {{\"subjective\":\"\",\"objective\":\"\",\"assessment\":\"\",\"plan\":\"\",\"icd_codes\":[],\"cpt_codes\":[],\"disclaimer\":\"AI-generated, must be reviewed by licensed physician\"}}\nNotes: {patient_notes[:5000]}"}],
            temperature=0.3)
    return await run_b2b("medical_doc", request, patient_notes, run)


@app.post("/api/v1/b2b/real-estate")
async def b2b_re(request: Request, property_data: str = Form(...),
                  location: str = Form(...), budget: Optional[float] = Form(None)):
    async def run():
        return await groq.json_chat([
            {"role": "system", "content": "RE analyst. Return only JSON."},
            {"role": "user", "content": f"RE analysis. JSON: {{\"property_summary\":\"\",\"valuation_estimate\":0,\"roi_potential\":{{}},\"risks\":[],\"recommendation\":\"buy/hold/avoid\"}}\nProperty: {property_data[:3000]}\nLocation: {location}\nBudget: {budget}"}],
            temperature=0.4)
    return await run_b2b("real_estate", request, property_data, run)


@app.post("/api/v1/b2b/insurance-claim")
async def b2b_ins(request: Request, claim_data: str = Form(...),
                   policy: str = Form(...), incident: str = Form(...)):
    async def run():
        return await groq.json_chat([
            {"role": "system", "content": "Claims adjuster. Return only JSON."},
            {"role": "user", "content": f"Process claim. JSON: {{\"coverage_determination\":\"\",\"payout_estimate\":0,\"deductible\":0,\"fraud_risk_score\":0-100,\"documentation_needed\":[]}}\nClaim: {claim_data[:3000]}\nPolicy: {policy[:2000]}\nIncident: {incident[:2000]}"}],
            temperature=0.3)
    return await run_b2b("insurance_claim", request, claim_data, run)


@app.post("/api/v1/b2b/tax-processing")
async def b2b_tax(request: Request, documents: str = Form(...),
                   tax_year: int = Form(...), jurisdiction: str = Form("US-Federal")):
    async def run():
        return await groq.json_chat([
            {"role": "system", "content": "Tax professional. Return only JSON."},
            {"role": "user", "content": f"Process tax {tax_year}/{jurisdiction}. JSON: {{\"gross_income\":0,\"deductions\":[],\"taxable_income\":0,\"tax_liability\":0,\"refund_or_owed\":0,\"flags\":[],\"audit_risk\":\"low/medium/high\"}}\nDocs: {documents[:5000]}"}],
            temperature=0.2)
    return await run_b2b("tax_processing", request, documents, run)


@app.post("/api/v1/b2b/invoice")
async def b2b_invoice(request: Request, invoice_text: str = Form(...)):
    async def run():
        return await groq.json_chat([
            {"role": "system", "content": "Invoice AI. Return only JSON."},
            {"role": "user", "content": f"Extract invoice. JSON: {{\"invoice_number\":\"\",\"vendor\":{{}},\"customer\":{{}},\"line_items\":[],\"subtotal\":0,\"tax\":0,\"total\":0,\"currency\":\"USD\"}}\nInvoice: {invoice_text[:4000]}"}],
            temperature=0.1)
    return await run_b2b("invoice_processing", request, invoice_text, run)


@app.post("/api/v1/b2b/contract-intel")
async def b2b_contract(request: Request, contract: str = Form(...),
                        party: str = Form("buyer")):
    async def run():
        return await groq.json_chat([
            {"role": "system", "content": "Contract attorney AI. Return only JSON."},
            {"role": "user", "content": f"Contract intel from {party}. JSON: {{\"contract_type\":\"\",\"key_obligations\":[],\"financial_terms\":{{}},\"unusual_clauses\":[],\"risk_score\":0-100,\"sign_recommendation\":\"\"}}\nContract: {contract[:8000]}"}],
            temperature=0.3)
    return await run_b2b("contract_intel", request, contract, run)


@app.post("/api/v1/b2b/patent")
async def b2b_patent(request: Request, invention: str = Form(...),
                      field: str = Form(...), prior_art: str = Form("")):
    async def run():
        return await groq.json_chat([
            {"role": "system", "content": "Patent attorney AI. Return only JSON."},
            {"role": "user", "content": f"Draft patent ({field}). JSON: {{\"title\":\"\",\"abstract\":\"\",\"background\":\"\",\"summary\":\"\",\"claims\":[{{\"number\":1,\"type\":\"independent\",\"text\":\"\"}}],\"novelty_analysis\":\"\"}}\nInvention: {invention[:4000]}\nPrior art: {prior_art[:2000]}"}],
            temperature=0.4)
    return await run_b2b("patent_drafting", request, invention, run)


@app.post("/api/v1/b2b/legal-brief")
async def b2b_brief(request: Request, case_facts: str = Form(...),
                     legal_question: str = Form(...), jurisdiction: str = Form("Federal")):
    async def run():
        return await groq.json_chat([
            {"role": "system", "content": "Litigation attorney. Return only JSON."},
            {"role": "user", "content": f"Legal brief ({jurisdiction}). JSON: {{\"caption\":\"\",\"statement_of_facts\":\"\",\"argument\":\"\",\"conclusion\":\"\",\"strength_assessment\":0-100}}\nFacts: {case_facts[:4000]}\nQuestion: {legal_question}"}],
            temperature=0.3)
    return await run_b2b("legal_brief", request, case_facts, run)


@app.post("/api/v1/b2b/financial-report")
async def b2b_fin(request: Request, data: str = Form(...), period: str = Form(...),
                   report_type: str = Form("quarterly")):
    async def run():
        return await groq.json_chat([
            {"role": "system", "content": "CFO analyst. Return only JSON."},
            {"role": "user", "content": f"Financial report {report_type}/{period}. JSON: {{\"executive_summary\":\"\",\"revenue\":{{}},\"expenses\":{{}},\"profitability\":{{}},\"kpis\":[],\"recommendations\":[]}}\nData: {data[:5000]}"}],
            temperature=0.3)
    return await run_b2b("financial_report", request, data, run)


@app.post("/api/v1/b2b/competitive-intel")
async def b2b_comp(request: Request, company: str = Form(...),
                    competitors: str = Form(...), industry: str = Form(...)):
    async def run():
        return await groq.json_chat([
            {"role": "system", "content": "CI analyst. Return only JSON."},
            {"role": "user", "content": f"CI for {company} in {industry}. JSON: {{\"executive_summary\":\"\",\"competitor_profiles\":[],\"swot\":{{}},\"strategic_recommendations\":[]}}\nCompetitors: {competitors}"}],
            temperature=0.4)
    return await run_b2b("competitive_intel", request, company, run)


@app.post("/api/v1/b2b/screen-candidate")
async def b2b_screen(request: Request, candidate_data: str = Form(...),
                      job_requirements: str = Form(...)):
    async def run():
        return await groq.json_chat([
            {"role": "system", "content": "Senior recruiter. Return only JSON."},
            {"role": "user", "content": f"Screen candidate. JSON: {{\"match_score\":0-100,\"red_flags\":[],\"green_flags\":[],\"culture_fit_score\":0-100,\"interview_questions\":[],\"recommended_next_step\":\"\"}}\nCandidate: {candidate_data[:3000]}\nRequirements: {job_requirements[:2000]}"}],
            temperature=0.3)
    return await run_b2b("recruitment_screen", request, candidate_data, run)


@app.post("/api/v1/b2b/sales-intel")
async def b2b_sales(request: Request, prospect_data: str = Form(...),
                     your_product: str = Form(...), their_pain_points: str = Form("")):
    async def run():
        return await groq.json_chat([
            {"role": "system", "content": "Sales strategist. Return only JSON."},
            {"role": "user", "content": f"Sales intel. JSON: {{\"account_overview\":\"\",\"buying_signals\":[],\"pain_points_predicted\":[],\"value_proposition\":\"\",\"email_templates\":[],\"success_probability\":0-100}}\nProspect: {prospect_data[:3000]}\nProduct: {your_product[:2000]}\nPain: {their_pain_points[:1000]}"}],
            temperature=0.4)
    return await run_b2b("sales_intel", request, prospect_data, run)


# ═══════════════════════════════════════════════════════════════
# ENTERPRISE
# ═══════════════════════════════════════════════════════════════

@app.post("/api/v1/enterprise/register")
async def enterprise_register(company_name: str = Form(...),
                                contact_email: str = Form(...),
                                plan: str = Form("starter")):
    quotas = {"starter": 1000, "business": 10000, "enterprise": 100000}
    q = quotas.get(plan, 1000)
    conn = db()
    try:
        if conn.execute("SELECT id FROM enterprise_clients WHERE company_name=?",
                        (company_name,)).fetchone():
            return JSONResponse({"status": "error", "message": "Company exists"}, status_code=409)
        api_key = f"erc_{secrets.token_urlsafe(40)}"
        cur = conn.execute(
            """INSERT INTO enterprise_clients (company_name, contact_email, plan,
               monthly_quota, api_key) VALUES (?,?,?,?,?)""",
            (company_name, contact_email, plan, q, api_key))
        conn.commit()
        return {"status": "success", "client_id": cur.lastrowid,
                "api_key": api_key, "plan": plan, "monthly_quota": q}
    finally:
        conn.close()


@app.get("/api/v1/enterprise/usage")
async def enterprise_usage(request: Request):
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        raise HTTPException(401, "API key required")
    conn = db()
    try:
        client = conn.execute("SELECT * FROM enterprise_clients WHERE api_key=?",
                              (api_key,)).fetchone()
        if not client:
            raise HTTPException(401, "Invalid key")
        jobs = conn.execute(
            """SELECT service_key, COUNT(*) c, SUM(cost) total FROM enterprise_jobs
               WHERE client_id=? GROUP BY service_key ORDER BY total DESC LIMIT 20""",
            (client["id"],)).fetchall()
        return {"client": dict(client), "usage_by_service": [dict(r) for r in jobs]}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# OTHER ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@app.post("/api/v1/harvester/start")
async def harvester(language: str = Form("python"), min_stars: int = Form(50),
                     min_followers: int = Form(20), limit: int = Form(10)):
    return {"status": "RUNNING", "job_id": f"hb_{secrets.token_hex(6)}"}


@app.get("/api/v1/companies/hiring")
def companies_hiring():
    return [{"name": v["name"], "jobs": 47, "logo": v["logo"],
             "avg_salary_k": 195, "key": k} for k, v in GIANT_COMPANIES.items()]


@app.get("/api/v1/mentors")
def mentors():
    return [
        {"name": "Dr. Sarah Chen", "role": "ex-AI Lead @ Google", "rating": 4.9, "avatar": "SC", "price": "Free"},
        {"name": "Marcus Lee", "role": "CTO @ AI Startup", "rating": 5.0, "avatar": "ML", "price": "$50/hr"},
        {"name": "Priya Patel", "role": "Staff Eng @ Meta", "rating": 4.8, "avatar": "PP", "price": "Free"},
    ]


@app.get("/api/v1/badge/{user_id}.svg")
def badge_svg(user_id: str):
    name, score = "Guest", 0
    if user_id != "guest":
        try:
            conn = db()
            row = conn.execute("SELECT full_name, trust_score FROM users WHERE id=?",
                               (int(user_id),)).fetchone()
            if row:
                name, score = row["full_name"], row["trust_score"]
            conn.close()
        except Exception:
            pass
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="320" height="120" viewBox="0 0 320 120">
  <rect width="320" height="120" rx="12" fill="#030712"/>
  <text x="20" y="40" font-family="Arial" font-size="20" font-weight="800" fill="#00f0ff">ERCORS</text>
  <text x="20" y="65" font-family="Arial" font-size="14" fill="#ffffff">{name[:24]}</text>
  <text x="20" y="90" font-family="Arial" font-size="12" fill="#94a3b8">Trust: {score}</text>
</svg>'''
    return Response(content=svg, media_type="image/svg+xml")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws_mgr.connect(ws)
    try:
        await ws.send_json({"type": "welcome", "message": "Connected to ERCORS"})
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_mgr.disconnect(ws)
    except Exception:
        ws_mgr.disconnect(ws)


@app.get("/", response_class=HTMLResponse)
def root():
    if INDEX_HTML.exists():
        return FileResponse(INDEX_HTML)
    return HTMLResponse("<h1>ERCORS v18 ✅</h1>")


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    if full_path.startswith("api/") or full_path.startswith("ws"):
        raise HTTPException(404, "Not found")
    if INDEX_HTML.exists():
        return FileResponse(INDEX_HTML)
    raise HTTPException(404, "Not found")


if __name__ == "__main__":
    import uvicorn
    log.info("ERCORS v18 starting on port %d", PORT)
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False, log_level="info")
