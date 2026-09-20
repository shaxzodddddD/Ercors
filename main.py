"""
═══════════════════════════════════════════════════════════════════════════════
ERCORS v12 — Backend API
FastAPI + SQLite · Render.com Ready · Python 3.11.9
Fully compatible with ERCORS v12 index.html
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import re
import sys
import base64
import hashlib
import secrets
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager
from collections import Counter

from fastapi import (
    FastAPI, Request, HTTPException, Depends, Form,
    UploadFile, File, WebSocket, WebSocketDisconnect
)
from fastapi.responses import (
    HTMLResponse, JSONResponse, Response, FileResponse
)
from fastapi.middleware.cors import CORSMiddleware


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).resolve().parent

# On Render, /tmp is writable. Locally, use project dir.
_default_data = "/tmp" if os.getenv("RENDER") else str(BASE_DIR)
DATA_DIR = Path(os.getenv("DATA_DIR", _default_data))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "ercors.db"
INDEX_HTML = BASE_DIR / "index.html"

TOKEN_EXPIRY_HOURS = 168
MAX_UPLOAD_SIZE = 20 * 1024 * 1024
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("ercors")


# ═══════════════════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════════════════

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    user_type TEXT DEFAULT 'expert',
    company_name TEXT,
    industry TEXT,
    skills TEXT,
    hourly_rate TEXT,
    github TEXT,
    trust_score REAL DEFAULT 75.0,
    xp INTEGER DEFAULT 50,
    level INTEGER DEFAULT 1,
    projects INTEGER DEFAULT 0,
    earnings REAL DEFAULT 0,
    referral_code TEXT UNIQUE,
    referred_by TEXT,
    referred_count INTEGER DEFAULT 0,
    referral_earnings REAL DEFAULT 0,
    streak_days INTEGER DEFAULT 1,
    last_streak TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_login TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    title TEXT NOT NULL,
    description TEXT,
    required_skills TEXT,
    min_experience REAL,
    budget TEXT,
    deadline TEXT,
    status TEXT DEFAULT 'Open',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    user_name TEXT,
    content TEXT NOT NULL,
    likes INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS escrows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    title TEXT NOT NULL,
    amount REAL NOT NULL,
    status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS badges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    badge_key TEXT NOT NULL,
    claimed_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, badge_key)
);

CREATE TABLE IF NOT EXISTS bounties (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT,
    prize INTEGER,
    severity TEXT,
    deadline TEXT,
    claimed_by INTEGER,
    claimed_at TEXT
);

CREATE TABLE IF NOT EXISTS chat_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    role TEXT,
    message TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC);
"""


def init_db() -> None:
    """Initialize database schema and seed data."""
    conn = db()
    try:
        conn.executescript(SCHEMA)
        conn.commit()

        # Seed bounties
        if conn.execute("SELECT COUNT(*) c FROM bounties").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT INTO bounties (id,title,company,prize,severity,deadline) VALUES (?,?,?,?,?,?)",
                [
                    ("b1", "Fix RAG hallucination bug", "OpenAI", 5000, "critical", "2h"),
                    ("b2", "Optimize transformer inference", "Meta", 3500, "high", "5h"),
                    ("b3", "Design AI safety protocol", "Anthropic", 8000, "critical", "1d"),
                    ("b4", "Build vector DB benchmark", "Pinecone", 1500, "medium", "3d"),
                    ("b5", "Solve RLHF alignment task", "DeepMind", 12000, "critical", "2d"),
                    ("b6", "Create LLM eval dataset", "Hugging Face", 2000, "high", "1d"),
                ]
            )

        # Seed posts
        if conn.execute("SELECT COUNT(*) c FROM posts").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT INTO posts (user_name, content, likes) VALUES (?,?,?)",
                [
                    ("Ali Karimov", "ERCORS ishga tushdi! 🚀", 12),
                    ("Malika Yusupova", "AI match 3 sekundda ishlaydi! 💼", 34),
                    ("ERCORS Admin", "64 modul LIVE ✅", 89),
                ]
            )

        # Seed campaigns
        if conn.execute("SELECT COUNT(*) c FROM campaigns").fetchone()["c"] == 0:
            conn.executemany(
                """INSERT INTO campaigns (title,description,budget,deadline,company_name,required_skills)
                   VALUES (?,?,?,?,?,?)""",
                [
                    ("AI Chatbot Development", "Autonomous AI chatbot", "$15,000", "2026-12-01", "TechCorp", "python,llm,fastapi"),
                    ("Quantum Cryptography", "Post-Quantum security", "$25,000", "2026-11-15", "QuantumSecure", "python,quantum"),
                ]
            )

        conn.commit()
        log.info("✅ Database ready at %s", DB_PATH)
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# 64 MODULES
# ═══════════════════════════════════════════════════════════════════════════

_MODULE_DATA = [
    ("m1", "Enterprise AI Talent Matching", "Core"),
    ("m2", "Managed RLHF & Data Annotation", "Core"),
    ("m3", "AI Hiring SaaS & Trust Score", "Core"),
    ("m4", "Global Escrow & B2B Contracts", "Core"),
    ("m5", "Micro-Equity HFT Engine", "Core"),
    ("m6", "AI Vetted Engineers", "Talent Sourcing"),
    ("m7", "AI & ML Specialists", "Talent Sourcing"),
    ("m8", "Autonomous AI Agents & Swarm", "Talent Sourcing"),
    ("m9", "Embedded & Edge AI Hardware", "Talent Sourcing"),
    ("m10", "Quantum Computing & Security", "Talent Sourcing"),
    ("m11", "RLHF & Model Evaluation", "Data & Training"),
    ("m12", "Code Data Annotation", "Data & Training"),
    ("m13", "Multimodal Data Sourcing", "Data & Training"),
    ("m14", "Red Teaming & AI Safety", "Data & Training"),
    ("m15", "AI Voice/Video Interview Bot", "Hiring Tools"),
    ("m16", "Code Assessment Engine", "Hiring Tools"),
    ("m17", "Background & Trust Score", "Hiring Tools"),
    ("m18", "AI Skill Graph Analyzer", "Hiring Tools"),
    ("m19", "Dedicated Remote Teams", "Direct & Premium"),
    ("m20", "Express AI Consultation", "Direct & Premium"),
    ("m21", "AI Startup Builder On-Demand", "Direct & Premium"),
    ("m22", "Web3 & Spatial Computing", "Direct & Premium"),
    ("m23", "Direct Escrow & Mass Payouts", "Direct & Premium"),
    ("m24", "Enterprise SLA & Managed PM", "Direct & Premium"),
    ("m25", "Instant Talent API Access", "Direct & Premium"),
    ("m26", "Cloud GPU & TPU Server Access", "Infrastructure"),
    ("m27", "Quantum QPU Remote Access", "Infrastructure"),
    ("m28", "AI Sandbox & Code Execution Nodes", "Infrastructure"),
    ("m29", "Serverless AI Endpoint Hosting", "Infrastructure"),
    ("m30", "Autonomous Software Engineer Swarm", "Infrastructure"),
    ("m31", "AI Data Scraping & Web Extraction", "Infrastructure"),
    ("m32", "Autonomous SMM & Marketing Agents", "Infrastructure"),
    ("m33", "AI Customer Support & Voice Bot", "Infrastructure"),
    ("m34", "Zero-Knowledge Proofs Sandbox", "Infrastructure"),
    ("m35", "Automated NDA & Smart Contracts", "Infrastructure"),
    ("m36", "Deepfake & Synthetic Media Audit", "Infrastructure"),
    ("m37", "WebXR & Spatial VR Showroom", "Infrastructure"),
    ("m38", "3D Generative Asset Factory", "Infrastructure"),
    ("m39", "Digital Twin Factory Simulation", "Infrastructure"),
    ("m40", "Custom GLSL Shader & Physics", "Infrastructure"),
    ("m41", "High-Frequency Micro-Equity Exchange", "Infrastructure"),
    ("m42", "Global Crypto & Cross-Border Escrow", "Infrastructure"),
    ("m43", "Micro-Equity Flash Loans & Leverage", "Infrastructure"),
    ("m44", "AI Startup Crowdfunding Portal", "Infrastructure"),
    ("m45", "AI-Powered Code Review", "Developer Tools"),
    ("m46", "Automated Testing Suite", "Developer Tools"),
    ("m47", "CI/CD Pipeline Integration", "Developer Tools"),
    ("m48", "Docker & Kubernetes Orchestration", "Developer Tools"),
    ("m49", "AI-Driven Documentation", "Developer Tools"),
    ("m50", "Code Quality Dashboard", "Developer Tools"),
    ("m51", "Real-Time Error Tracking", "Developer Tools"),
    ("m52", "Performance Monitoring", "Developer Tools"),
    ("m53", "Security Vulnerability Scanner", "Developer Tools"),
    ("m54", "API Gateway & Management", "Developer Tools"),
    ("m55", "GraphQL Federation", "Developer Tools"),
    ("m56", "Event-Driven Architecture", "Developer Tools"),
    ("m57", "Data Lake & Analytics", "Developer Tools"),
    ("m58", "MLOps Pipeline", "Developer Tools"),
    ("m59", "Model Monitoring & Drift Detection", "Developer Tools"),
    ("m60", "Feature Store", "Developer Tools"),
    ("m61", "Explainable AI (XAI)", "Developer Tools"),
    ("m62", "Federated Learning", "Developer Tools"),
    ("m63", "Synthetic Data Generation", "Developer Tools"),
    ("m64", "AI Governance & Compliance", "Developer Tools"),
]

MODULES = [
    {
        "id": mid,
        "name": name,
        "category": cat,
        "description": f"Advanced AI module for {cat}.",
        "active": True,
    }
    for mid, name, cat in _MODULE_DATA
]
MODULE_MAP = {m["id"]: m for m in MODULES}


# ═══════════════════════════════════════════════════════════════════════════
# AUTH HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def hash_pw(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return base64.b64encode(salt + dk).decode()


def verify_pw(password: str, hashed: str) -> bool:
    try:
        raw = base64.b64decode(hashed.encode())
        salt, dk = raw[:16], raw[16:]
        test = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
        return secrets.compare_digest(dk, test)
    except Exception:
        return False


def make_token(user_id: int) -> str:
    token = secrets.token_urlsafe(48)
    expires = (datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS)).isoformat()
    conn = db()
    try:
        conn.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)",
            (token, user_id, expires),
        )
        conn.commit()
    finally:
        conn.close()
    return token


def user_from_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    conn = db()
    try:
        row = conn.execute(
            """SELECT u.* FROM users u
               JOIN sessions s ON s.user_id = u.id
               WHERE s.token = ? AND s.expires_at > datetime('now')""",
            (token,),
        ).fetchone()
        if not row:
            return None
        user = dict(row)
        user.pop("password_hash", None)
        return user
    finally:
        conn.close()


def get_token(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return request.cookies.get("ercors_token")


async def current_user(request: Request) -> Optional[Dict[str, Any]]:
    return user_from_token(get_token(request))


async def require_user(request: Request) -> Dict[str, Any]:
    u = await current_user(request)
    if not u:
        raise HTTPException(401, "Authentication required")
    return u


def make_ref_code(name: str) -> str:
    base = re.sub(r"[^A-Za-z]", "", name)[:4].upper() or "USER"
    return f"{base}{secrets.token_hex(3).upper()}"


# ═══════════════════════════════════════════════════════════════════════════
# AI ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class AIEngine:
    KB = {
        "trust": "Trust Score = skills (30%) + projects (25%) + reviews (20%) + code (15%) + interview (10%). Range: 0-100.",
        "modules": "ERCORS has 64 modules: Core (5), Talent Sourcing (5), Data & Training (4), Hiring Tools (4), Direct & Premium (7), Infrastructure (19), Developer Tools (20).",
        "earn": "Earn via: bounty board ($1.5k-$12k), referrals ($50/signup), jobs ($100k-$500k), contests.",
        "hire": "Hire via: AI Matching (1-sec), Video Bot, Code Assessment, Skill Graph. Avg: 48 hours.",
        "escrow": "Escrow locks funds until milestone. USD/BTC/ETH/USDC. 0.5% fee.",
        "price": "ERCORS is FREE forever. Premium: $19/mo. Enterprise: custom.",
        "job": "Top hiring: Google (47), OpenAI (23), Meta (31), Microsoft (38), Anthropic (18). Avg $185k.",
        "learn": "Free courses: Python for AI, Deep Learning, LLM Engineering. Blockchain certs.",
        "security": "SOC2, E2E encryption, zero-trust, PBKDF2 100k iterations.",
        "bounty": "Bounty Board: OpenAI, Meta, Anthropic. $1,500-$12,000 per task.",
    }

    SKILLS_DB = [
        "python", "javascript", "typescript", "react", "vue", "angular",
        "node.js", "node", "pytorch", "tensorflow", "keras", "scikit-learn",
        "pandas", "numpy", "fastapi", "flask", "django", "express",
        "graphql", "rest", "docker", "kubernetes", "terraform", "aws",
        "gcp", "azure", "postgresql", "mysql", "mongodb", "redis",
        "rust", "go", "golang", "java", "c++", "swift", "kotlin",
        "llm", "gpt", "transformers", "rag", "langchain", "huggingface",
        "sql", "git", "machine learning", "deep learning", "nlp",
        "computer vision", "data science", "analytics", "tableau",
    ]

    @classmethod
    def chat(cls, msg: str) -> str:
        m = msg.lower().strip()
        if len(m) < 25 and any(g in m for g in ["hi", "hello", "hey", "salom"]):
            return "Hey! 👋 I'm the ERCORS AI. Ask about trust scores, jobs, modules, or earning."
        for key, ans in cls.KB.items():
            if key in m:
                return ans
        if any(w in m for w in ["job", "hire", "salary", "career"]):
            return cls.KB["job"]
        if any(w in m for w in ["money", "earn", "referral", "income"]):
            return cls.KB["earn"]
        if any(w in m for w in ["learn", "course", "cert"]):
            return cls.KB["learn"]
        if any(w in m for w in ["security", "audit", "safe"]):
            return cls.KB["security"]
        if any(w in m for w in ["price", "cost", "fee"]):
            return cls.KB["price"]
        return f"Interesting! Tell me more about '{msg[:60]}'. I can help with hiring, learning, or earning."

    @classmethod
    def analyze_cv(cls, text: str) -> Dict[str, Any]:
        tl = text.lower()
        found = sorted({s for s in cls.SKILLS_DB if s in tl})
        exp = 0
        for m in re.finditer(r"(\d+)\s*(?:\+)?\s*(?:years?|yrs?)", tl):
            exp = max(exp, int(m.group(1)))

        role = "AI Engineer"
        if "data scientist" in tl: role = "Data Scientist"
        elif "full stack" in tl or "fullstack" in tl: role = "Full-Stack Engineer"
        elif "devops" in tl: role = "DevOps Engineer"
        elif "ml engineer" in tl: role = "ML Engineer"

        score = round(min(95.0, 45 + len(found) * 3 + exp * 4), 1)
        return {
            "skills": found[:25],
            "experience_years": exp,
            "current_position": role,
            "trust_score": score,
            "summary": f"{role} with {exp}y experience, {len(found)} skills.",
        }

    @classmethod
    def analyze_interview(cls, transcript: str, position: str = "AI Engineer") -> Dict[str, Any]:
        wc = len(transcript.split())
        score = min(98, max(45, 60 + wc // 20 + secrets.randbelow(15)))
        return {
            "summary": f"{wc}-word response analyzed for {position}.",
            "strengths": ["Strong technical background", "Clear communication", "Problem-solving"],
            "weaknesses": ["Could elaborate on system design", "Add metrics"],
            "match_score": score,
            "recommendation": "STRONG HIRE" if score >= 85 else "HIRE" if score >= 70 else "MAYBE",
        }


ai = AIEngine()


# ═══════════════════════════════════════════════════════════════════════════
# WEBSOCKET MANAGER
# ═══════════════════════════════════════════════════════════════════════════

class WSManager:
    def __init__(self):
        self.connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, payload: dict):
        dead = []
        for ws in list(self.connections):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


ws_mgr = WSManager()


# ═══════════════════════════════════════════════════════════════════════════
# FASTAPI APP
# ═══════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("🚀 ERCORS starting...")
    init_db()
    log.info("✅ %d modules loaded", len(MODULES))
    yield
    log.info("👋 Shutdown")


app = FastAPI(title="ERCORS API", version="12.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════════════════
# HEALTH & STATS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": "12.0.0",
        "modules": len(MODULES),
        "env": "render" if os.getenv("RENDER") else "local",
        "time": datetime.utcnow().isoformat(),
    }


@app.get("/api/stats")
def stats():
    conn = db()
    try:
        users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        posts = conn.execute("SELECT COUNT(*) c FROM posts").fetchone()["c"]
        campaigns = conn.execute("SELECT COUNT(*) c FROM campaigns").fetchone()["c"]
        return {
            "users": users + 12847,
            "posts": posts,
            "campaigns": campaigns,
            "modules": len(MODULES),
            "bounties_paid": 47830,
            "bounty_hunters": 1247,
        }
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# AUTH ROUTES
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/register")
def register(
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    user_type: str = Form("expert"),
    company_name: Optional[str] = Form(None),
    industry: Optional[str] = Form(None),
    skills: Optional[str] = Form(None),
    hourly_rate: Optional[str] = Form(None),
    github: Optional[str] = Form(None),
):
    email = email.lower().strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return JSONResponse({"status": "error", "message": "Invalid email"}, status_code=400)
    if len(password) < 6:
        return JSONResponse({"status": "error", "message": "Password must be 6+ chars"}, status_code=400)

    conn = db()
    try:
        if conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            return JSONResponse({"status": "error", "message": "Email exists"}, status_code=409)

        ref = make_ref_code(full_name)
        cur = conn.execute(
            """INSERT INTO users
               (full_name, email, password_hash, user_type, company_name,
                industry, skills, hourly_rate, github, referral_code)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (full_name, email, hash_pw(password), user_type, company_name,
             industry, skills, hourly_rate, github, ref),
        )
        uid = cur.lastrowid
        conn.commit()

        token = make_token(uid)
        user = dict(conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
        user.pop("password_hash", None)
        log.info("New user: %s", email)
        return {"status": "success", "session": token, "user": user}
    finally:
        conn.close()


@app.post("/api/login")
def login(email: str = Form(...), password: str = Form(...)):
    conn = db()
    try:
        row = conn.execute("SELECT * FROM users WHERE email=?", (email.lower().strip(),)).fetchone()
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
    token = get_token(request)
    if token:
        conn = db()
        try:
            conn.execute("DELETE FROM sessions WHERE token=?", (token,))
            conn.commit()
        finally:
            conn.close()
    return {"status": "success"}


@app.get("/api/me")
async def me(user: Dict = Depends(require_user)):
    return {"status": "success", "user": user}


# ═══════════════════════════════════════════════════════════════════════════
# MODULES
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/modules")
def list_modules(category: Optional[str] = None, q: Optional[str] = None):
    items = MODULES
    if category:
        items = [m for m in items if m["category"].lower() == category.lower()]
    if q:
        ql = q.lower()
        items = [m for m in items if ql in m["name"].lower() or ql in m["description"].lower()]
    return items


@app.get("/api/modules/categories")
def module_categories():
    cats = Counter(m["category"] for m in MODULES)
    return [{"name": k, "count": v} for k, v in cats.items()]


@app.get("/api/modules/{mid}")
def get_module(mid: str):
    m = MODULE_MAP.get(mid)
    if not m:
        raise HTTPException(404, "Module not found")
    return m


@app.post("/api/modules/{mid}/action")
async def module_action(mid: str, request: Request):
    m = MODULE_MAP.get(mid)
    if not m:
        raise HTTPException(404, "Module not found")

    user = await current_user(request)
    result = {
        "module_id": mid,
        "module_name": m["name"],
        "executed_at": datetime.utcnow().isoformat(),
        "duration_ms": secrets.randbelow(500) + 50,
        "status": "success",
        "output": f"Module '{m['name']}' executed successfully.",
    }

    if user:
        conn = db()
        try:
            conn.execute("UPDATE users SET xp = xp + 5 WHERE id=?", (user["id"],))
            conn.commit()
        finally:
            conn.close()

    return {"status": "success", "action_result": result}


# ═══════════════════════════════════════════════════════════════════════════
# TALENTS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/talents")
def talents(limit: int = 20):
    conn = db()
    try:
        rows = conn.execute(
            """SELECT id, full_name AS name, skills, user_type AS title, trust_score
               FROM users WHERE user_type='expert'
               ORDER BY trust_score DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        results = [dict(r) for r in rows]
        if not results:
            results = [
                {"id": -1, "name": "Alice Johnson", "skills": "Python, PyTorch, LLM", "title": "Senior AI Engineer", "trust_score": 99.2},
                {"id": -2, "name": "Bob Smith", "skills": "Rust, C++, Quantum", "title": "Systems Architect", "trust_score": 98.7},
                {"id": -3, "name": "Carol White", "skills": "React, Node, TS", "title": "Full-Stack Lead", "trust_score": 97.9},
                {"id": -4, "name": "David Chen", "skills": "Go, K8s, AWS", "title": "DevOps Architect", "trust_score": 98.1},
                {"id": -5, "name": "Elena Rodriguez", "skills": "Data Science, R, SQL", "title": "Data Science Lead", "trust_score": 97.5},
            ]
        return results
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# CAMPAIGNS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/campaigns")
def list_campaigns():
    conn = db()
    try:
        rows = conn.execute("SELECT * FROM campaigns ORDER BY id DESC LIMIT 50").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/campaigns")
async def create_campaign(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    budget: str = Form(...),
    deadline: str = Form(...),
    required_skills: Optional[str] = Form(None),
    min_experience: Optional[float] = Form(None),
):
    user = await require_user(request)
    conn = db()
    try:
        cur = conn.execute(
            """INSERT INTO campaigns
               (company_id, title, description, required_skills, min_experience, budget, deadline)
               VALUES (?,?,?,?,?,?,?)""",
            (user["id"], title, description, required_skills, min_experience, budget, deadline),
        )
        conn.commit()
        return {"status": "success", "id": cur.lastrowid}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# POSTS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/posts")
def list_posts(limit: int = 50):
    conn = db()
    try:
        rows = conn.execute("SELECT * FROM posts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/posts")
async def create_post(request: Request, content: str = Form(...)):
    user = await require_user(request)
    if len(content) > 2000:
        return JSONResponse({"status": "error", "message": "Too long"}, status_code=400)

    conn = db()
    try:
        cur = conn.execute(
            "INSERT INTO posts (user_id, user_name, content) VALUES (?,?,?)",
            (user["id"], user["full_name"], content),
        )
        conn.execute("UPDATE users SET xp = xp + 10 WHERE id=?", (user["id"],))
        conn.commit()
        pid = cur.lastrowid
        await ws_mgr.broadcast({
            "type": "new_post",
            "post": {"id": pid, "user_name": user["full_name"], "content": content},
        })
        return {"status": "success", "id": pid}
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


# ═══════════════════════════════════════════════════════════════════════════
# ESCROW
# ═══════════════════════════════════════════════════════════════════════════

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
        cur = conn.execute(
            "INSERT INTO escrows (user_id, title, amount) VALUES (?,?,?)",
            (user["id"], title, amount),
        )
        conn.commit()
        return {"status": "success", "id": cur.lastrowid}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# LEADERBOARD
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/leaderboard")
def leaderboard():
    conn = db()
    try:
        rows = conn.execute(
            """SELECT full_name AS name, referred_count AS referrals,
                      referral_earnings AS reward_num
               FROM users WHERE referred_count > 0
               ORDER BY referred_count DESC LIMIT 10"""
        ).fetchall()
        result = [
            {"rank": i, "name": r["name"], "referrals": r["referrals"],
             "reward": f"${int(r['reward_num'] or 0):,}"}
            for i, r in enumerate(rows, 1)
        ]
        if not result:
            result = [
                {"rank": 1, "name": "Shaxzod K.", "referrals": 247, "reward": "$12,350"},
                {"rank": 2, "name": "Malika A.", "referrals": 189, "reward": "$9,450"},
                {"rank": 3, "name": "Bobur R.", "referrals": 156, "reward": "$7,800"},
                {"rank": 4, "name": "Dilnoza M.", "referrals": 134, "reward": "$6,700"},
                {"rank": 5, "name": "Aziz T.", "referrals": 112, "reward": "$5,600"},
            ]
        return result
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# BADGES & STREAK
# ═══════════════════════════════════════════════════════════════════════════

BADGE_XP = {"first": 50, "sharer": 100, "inviter": 200, "ai": 500, "vip": 1000, "founder": 5000}


@app.post("/api/badges/claim")
async def claim_badge(request: Request, badge_key: str = Form(...)):
    user = await require_user(request)
    if badge_key not in BADGE_XP:
        return JSONResponse({"status": "error", "message": "Unknown badge"}, status_code=400)

    conn = db()
    try:
        try:
            conn.execute("INSERT INTO badges (user_id, badge_key) VALUES (?,?)", (user["id"], badge_key))
        except sqlite3.IntegrityError:
            return {"status": "error", "message": "Already claimed"}

        xp_add = BADGE_XP[badge_key]
        conn.execute("UPDATE users SET xp = xp + ? WHERE id=?", (xp_add, user["id"]))
        row = conn.execute("SELECT xp FROM users WHERE id=?", (user["id"],)).fetchone()
        new_xp = row["xp"]
        new_level = 1 + new_xp // 500
        conn.execute("UPDATE users SET level=? WHERE id=?", (new_level, user["id"]))
        conn.commit()

        return {"status": "success", "xp_awarded": xp_add, "total_xp": new_xp, "level": new_level}
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
            return {"status": "error", "message": "Already claimed today"}

        streak = (row["streak_days"] or 0) + 1
        xp_add = 20 + min(streak, 7) * 5
        conn.execute(
            "UPDATE users SET streak_days=?, last_streak=?, xp = xp + ? WHERE id=?",
            (streak, today, xp_add, user["id"]),
        )
        conn.commit()
        return {"status": "success", "streak_days": streak, "xp_awarded": xp_add}
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


# ═══════════════════════════════════════════════════════════════════════════
# AI CHAT
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/ai/chat")
async def ai_chat(request: Request, message: str = Form(...)):
    user = await current_user(request)
    conn = db()
    try:
        if user:
            conn.execute("INSERT INTO chat_log (user_id, role, message) VALUES (?, 'user', ?)",
                         (user["id"], message))
        response = ai.chat(message)
        if user:
            conn.execute("INSERT INTO chat_log (user_id, role, message) VALUES (?, 'assistant', ?)",
                         (user["id"], response))
        conn.commit()
        return {"status": "success", "response": response}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# BADGE SVG
# ═══════════════════════════════════════════════════════════════════════════

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
  <defs><linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="#00f0ff"/><stop offset="100%" stop-color="#7000ff"/>
  </linearGradient></defs>
  <rect width="320" height="120" rx="12" fill="#030712"/>
  <rect x="2" y="2" width="316" height="116" rx="11" fill="none" stroke="url(#g)" stroke-width="2"/>
  <text x="20" y="40" font-family="Arial" font-size="20" font-weight="800" fill="#00f0ff">ERCORS</text>
  <text x="20" y="65" font-family="Arial" font-size="14" fill="#ffffff">{name[:24]}</text>
  <text x="20" y="90" font-family="Arial" font-size="12" fill="#94a3b8">Trust Score: {score}</text>
  <text x="260" y="40" font-family="Arial" font-size="24">🤖</text>
</svg>'''
    return Response(content=svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=3600"})


# ═══════════════════════════════════════════════════════════════════════════
# HR — CV UPLOAD
# ═══════════════════════════════════════════════════════════════════════════

def _extract_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".txt"):
        return data.decode("utf-8", errors="ignore")
    if name.endswith(".pdf"):
        parts = []
        for m in re.finditer(rb"\(([^)]{2,})\)", data):
            try:
                parts.append(m.group(1).decode("latin-1"))
            except Exception:
                pass
        return " ".join(parts)[:10000] if parts else data.decode("latin-1", errors="ignore")[:10000]
    return data.decode("utf-8", errors="ignore")[:10000]


@app.post("/api/upload-cv")
async def upload_cv(request: Request, file: UploadFile = File(...)):
    user = await require_user(request)
    data = await file.read()
    if len(data) > MAX_UPLOAD_SIZE:
        return JSONResponse({"status": "error", "message": "File too large"}, status_code=413)

    text = _extract_text(file.filename or "", data)
    analysis = ai.analyze_cv(text)

    conn = db()
    try:
        campaigns = conn.execute("SELECT * FROM campaigns").fetchall()
        matches = []
        skills_set = {s.lower() for s in analysis["skills"]}
        for c in campaigns:
            req = (c["required_skills"] or "").lower()
            if any(s in req for s in skills_set):
                matches.append({"id": c["id"], "title": c["title"], "budget": c["budget"]})

        conn.execute(
            "UPDATE users SET skills=?, trust_score=? WHERE id=?",
            (", ".join(analysis["skills"][:10]), analysis["trust_score"], user["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "status": "success",
        "analysis": analysis,
        "campaigns_matched": len(matches),
        "matches": matches[:5],
    }


# ═══════════════════════════════════════════════════════════════════════════
# HR — AUDIO INTERVIEW
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/hr/audio/analyze-interview")
async def analyze_interview(
    request: Request,
    file: UploadFile = File(...),
    position: Optional[str] = Form(None),
    language: str = Form("en"),
):
    data = await file.read()
    if len(data) > MAX_UPLOAD_SIZE:
        return JSONResponse({"status": "error", "message": "File too large"}, status_code=413)

    transcript = (
        f"Simulated {language} interview transcript. "
        "Candidate shows strong technical expertise, clear communication, "
        "and problem-solving. 5+ years AI/ML with Python, PyTorch, Kubernetes."
    )
    analysis = ai.analyze_interview(transcript, position or "AI Engineer")

    return {
        "status": "success",
        "transcription": transcript,
        "analysis": analysis,
        "campaigns_matched": secrets.randbelow(8) + 3,
        "audio_size": len(data),
    }


# ═══════════════════════════════════════════════════════════════════════════
# HARVESTER & NEGOTIATOR
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/harvester/start")
async def start_harvester(
    language: str = Form("python"),
    min_stars: int = Form(50),
    min_followers: int = Form(20),
    limit: int = Form(10),
):
    return {
        "status": "RUNNING",
        "job_id": f"hb_{secrets.token_hex(6)}",
        "message": f"Harvesting {limit} {language} devs...",
    }


@app.post("/api/v1/negotiate/contract")
async def negotiate(
    company_name: str = Form(...),
    developer_name: str = Form(...),
    project_scope: str = Form(""),
    budget_range: str = Form("$10k-$25k"),
):
    m = re.search(r"(\d+)", budget_range)
    base = int(m.group(1)) * 1000 if m else 15000
    final = base + secrets.randbelow(max(base // 3, 1))

    return {
        "status": "success",
        "negotiation": {
            "company": company_name,
            "developer": developer_name,
            "budget": final,
            "deadline": f"{secrets.choice([14, 21, 30, 45])} days",
            "terms": "Milestone escrow, NDA, 10% upfront, 90% on delivery",
            "accepted": True,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# BOUNTIES
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/bounties")
def list_bounties():
    conn = db()
    try:
        rows = conn.execute("SELECT * FROM bounties ORDER BY prize DESC").fetchall()
        return [dict(r) for r in rows]
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

        await ws_mgr.broadcast({
            "type": "bounty_claimed",
            "bounty_id": bid,
            "user_name": user["full_name"],
            "prize": row["prize"],
        })
        return {"status": "success", "prize": row["prize"], "message": f"Claimed: {row['title']}"}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# PORTFOLIO / SALARY / SKILL GAP / QUIZ
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/portfolio/generate")
def gen_portfolio(
    name: str = Form(...),
    title: str = Form(...),
    skills: str = Form(...),
    theme: str = Form("neon"),
):
    return {
        "status": "success",
        "theme": theme,
        "name": name,
        "title": title,
        "skills": [s.strip() for s in skills.split(",") if s.strip()],
    }


@app.post("/api/v1/salary/estimate")
def salary(years: int = Form(...), role: str = Form("ai"), region: str = Form("us")):
    base = {"ai": 120, "fullstack": 90, "data": 110, "devops": 105}.get(role, 100)
    mult = {"us": 1.4, "eu": 1.1, "uz": 0.35, "remote": 1.0}.get(region, 1.0)
    s = round((base + years * 4) * mult, 1)
    return {"status": "success", "salary_k_usd": s, "monthly_k_usd": round(s / 12, 1)}


@app.post("/api/v1/skills/gap")
def skill_gap(skills: str = Form(...), role: str = Form("ai")):
    required = {
        "ai": ["Python", "PyTorch", "TensorFlow", "LLMs", "RAG", "Transformers", "MLOps", "Docker"],
        "fullstack": ["React", "Node.js", "TypeScript", "SQL", "Next.js", "Tailwind", "REST APIs", "Git"],
        "data": ["Python", "SQL", "Pandas", "Statistics", "Visualization", "ML", "Spark", "Tableau"],
        "devops": ["Kubernetes", "Terraform", "AWS", "CI/CD", "Docker", "Linux", "Bash", "Monitoring"],
    }
    req = required.get(role, required["ai"])
    have_lower = {s.strip().lower() for s in skills.split(",")}
    have = [r for r in req if r.lower() in have_lower]
    missing = [r for r in req if r not in have]
    pct = round(len(have) / len(req) * 100) if req else 0
    return {"status": "success", "match_percentage": pct, "have": have, "missing": missing}


@app.get("/api/v1/quiz/questions")
def quiz_questions():
    return [
        {"q": "What does 'AGI' stand for?",
         "opts": ["Artificial General Intelligence", "Advanced Google Interface", "Automated Graphics Input", "All General Intelligence"],
         "answer_index": 0},
        {"q": "Which is NOT an AI framework?",
         "opts": ["PyTorch", "TensorFlow", "Keras", "Photoshop"], "answer_index": 3},
        {"q": "What is RLHF?",
         "opts": ["Random Loss Function", "Reinforcement Learning from Human Feedback", "Rapid Linear Half Flow", "Root Layer High Frequency"],
         "answer_index": 1},
        {"q": "Best language for AI?",
         "opts": ["PHP", "Python", "Cobol", "Perl"], "answer_index": 1},
    ]


@app.get("/api/v1/companies/hiring")
def companies_hiring():
    return [
        {"name": "Google", "jobs": 47, "logo": "🔵", "avg_salary_k": 195},
        {"name": "OpenAI", "jobs": 23, "logo": "🟢", "avg_salary_k": 220},
        {"name": "Meta", "jobs": 31, "logo": "🔷", "avg_salary_k": 200},
        {"name": "Microsoft", "jobs": 38, "logo": "🟦", "avg_salary_k": 185},
        {"name": "Anthropic", "jobs": 18, "logo": "🟠", "avg_salary_k": 210},
        {"name": "Nvidia", "jobs": 29, "logo": "🟩", "avg_salary_k": 205},
    ]


@app.get("/api/v1/mentors")
def mentors():
    return [
        {"name": "Dr. Sarah Chen", "role": "ex-AI Lead @ Google", "rating": 4.9, "avatar": "SC", "price": "Free"},
        {"name": "Marcus Lee", "role": "CTO @ AI Startup", "rating": 5.0, "avatar": "ML", "price": "$50/hr"},
        {"name": "Priya Patel", "role": "Staff Eng @ Meta", "rating": 4.8, "avatar": "PP", "price": "Free"},
    ]


# ═══════════════════════════════════════════════════════════════════════════
# WEBSOCKET
# ═══════════════════════════════════════════════════════════════════════════

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_mgr.connect(ws)
    try:
        await ws.send_json({"type": "welcome", "message": "Connected to ERCORS live feed"})
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_json({"type": "pong", "time": datetime.utcnow().isoformat()})
    except WebSocketDisconnect:
        ws_mgr.disconnect(ws)
    except Exception as e:
        log.warning("WS error: %s", e)
        ws_mgr.disconnect(ws)


# ═══════════════════════════════════════════════════════════════════════════
# STATIC FILES & SPA FALLBACK
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
def root():
    if INDEX_HTML.exists():
        return FileResponse(INDEX_HTML)
    return HTMLResponse("""
    <!DOCTYPE html>
    <html><head><title>ERCORS</title>
    <style>body{font-family:Arial;background:#030712;color:#e5e7eb;padding:3rem;text-align:center}
    h1{font-size:2.5rem;color:#00f0ff;margin-bottom:1rem}a{color:#00f0ff;margin:0 1rem;text-decoration:none}
    .c{background:rgba(0,240,255,0.05);border:1px solid rgba(0,240,255,0.2);
    border-radius:16px;padding:2rem;max-width:600px;margin:2rem auto}</style>
    </head><body>
    <h1>🚀 ERCORS Backend is Running</h1>
    <div class="c"><p>Add <code>index.html</code> to serve the frontend.</p>
    <p style="margin-top:1.5rem"><a href="/docs">📚 API Docs</a><a href="/health">💚 Health</a></p></div>
    </body></html>
    """)


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    if full_path.startswith("api/") or full_path.startswith("ws"):
        raise HTTPException(404, "Not found")
    if INDEX_HTML.exists():
        return FileResponse(INDEX_HTML)
    raise HTTPException(404, "Not found")


# ═══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    log.info("=" * 60)
    log.info("ERCORS v12 Backend")
    log.info("Port: %d", PORT)
    log.info("DB: %s", DB_PATH)
    log.info("Modules: %d", len(MODULES))
    log.info("Env: %s", "RENDER" if os.getenv("RENDER") else "LOCAL")
    log.info("=" * 60)

    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="info",
    )
