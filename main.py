"""
═══════════════════════════════════════════════════════════════════════════════
ERCORS v13 Backend — FastAPI + SQLite + WebSocket
Production-ready, zero native compilation, works on Render free tier
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
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from collections import Counter

from fastapi import (
    FastAPI, Request, HTTPException, Depends, Form,
    UploadFile, File, WebSocket, WebSocketDisconnect
)
from fastapi.responses import HTMLResponse, JSONResponse, Response, FileResponse
from fastapi.middleware.cors import CORSMiddleware

# ═══════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).resolve().parent
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
    company_name TEXT, industry TEXT, skills TEXT,
    hourly_rate TEXT, github TEXT, bio TEXT, country TEXT,
    trust_score REAL DEFAULT 75.0,
    xp INTEGER DEFAULT 50, level INTEGER DEFAULT 1,
    tier TEXT DEFAULT 'Bronze',
    projects INTEGER DEFAULT 0, earnings REAL DEFAULT 0,
    wallet_address TEXT,
    referral_code TEXT UNIQUE, referred_by TEXT,
    referred_count INTEGER DEFAULT 0,
    referral_earnings REAL DEFAULT 0,
    streak_days INTEGER DEFAULT 1, last_streak TEXT,
    last_login TEXT, is_verified INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER, title TEXT NOT NULL, description TEXT,
    required_skills TEXT, min_experience REAL, budget TEXT,
    deadline TEXT, status TEXT DEFAULT 'Open',
    applicants INTEGER DEFAULT 0, views INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, user_name TEXT, content TEXT NOT NULL,
    likes INTEGER DEFAULT 0, comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS escrows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, client_name TEXT, developer_name TEXT,
    title TEXT NOT NULL, description TEXT, amount REAL NOT NULL,
    currency TEXT DEFAULT 'USD', status TEXT DEFAULT 'active',
    milestone TEXT DEFAULT 'init',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP, released_at TEXT
);
CREATE TABLE IF NOT EXISTS badges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, badge_key TEXT NOT NULL,
    claimed_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, badge_key)
);
CREATE TABLE IF NOT EXISTS bounties (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT,
    company TEXT, prize INTEGER, severity TEXT, deadline TEXT,
    requirements TEXT, claimed_by INTEGER, claimed_at TEXT,
    status TEXT DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS chat_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, role TEXT, message TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, action TEXT, target TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS quiz_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, score INTEGER, total INTEGER,
    time_taken INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, title TEXT, body TEXT,
    type TEXT DEFAULT 'info', read INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, type TEXT, amount REAL,
    currency TEXT DEFAULT 'USD', reference TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, leader_id INTEGER, members TEXT,
    description TEXT, score INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL, description TEXT, category TEXT,
    instructor TEXT, duration_min INTEGER, level TEXT,
    price REAL DEFAULT 0, enrolled INTEGER DEFAULT 0,
    rating REAL DEFAULT 4.8,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC);
"""


def init_db() -> None:
    conn = db()
    try:
        conn.executescript(SCHEMA)
        conn.commit()

        # Seed bounties
        if conn.execute("SELECT COUNT(*) c FROM bounties").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT INTO bounties (id,title,description,company,prize,severity,deadline,requirements) VALUES (?,?,?,?,?,?,?,?)",
                [
                    ("b1", "Fix RAG hallucination bug", "Debug RAG pipeline issues", "OpenAI", 5000, "critical", "2h", "Python, LangChain, RAG"),
                    ("b2", "Optimize transformer inference", "Improve speed by 3x on LLaMA-7B", "Meta", 3500, "high", "5h", "PyTorch, CUDA"),
                    ("b3", "Design AI safety protocol", "Create comprehensive safety protocol", "Anthropic", 8000, "critical", "1d", "AI Safety, RLHF"),
                    ("b4", "Build vector DB benchmark", "Benchmark 3 vector DBs at 10M vectors", "Pinecone", 1500, "medium", "3d", "Python, benchmarking"),
                    ("b5", "Solve RLHF alignment task", "Align model 99.5% accuracy", "DeepMind", 12000, "critical", "2d", "RLHF, PyTorch"),
                    ("b6", "Create LLM eval dataset", "Generate 10k eval examples", "Hugging Face", 2000, "high", "1d", "Python, dataset"),
                    ("b7", "Build RAG chatbot legal", "RAG on 500+ legal documents", "Stripe", 4500, "high", "4d", "LangChain, FastAPI"),
                    ("b8", "Fine-tune model for code", "Fine-tune CodeLlama", "GitHub", 6000, "critical", "5d", "LoRA, PyTorch"),
                ]
            )

        # Seed posts
        if conn.execute("SELECT COUNT(*) c FROM posts").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT INTO posts (user_name, content, likes) VALUES (?,?,?)",
                [
                    ("Ali Karimov", "ERCORS yangi loyiha boshlandi! 🚀", 12),
                    ("Malika Yusupova", "AI job match 3 sekundda ishlaydi! 💼", 34),
                    ("Bobur Rakhimov", "64 modul yangilandi! ✅", 89),
                    ("Zilola Ahmedova", "$15,000 bonus topdim bu haftada!", 67),
                ]
            )

        # Seed campaigns
        if conn.execute("SELECT COUNT(*) c FROM campaigns").fetchone()["c"] == 0:
            conn.executemany(
                """INSERT INTO campaigns (title,description,budget,deadline,required_skills)
                   VALUES (?,?,?,?,?)""",
                [
                    ("AI Chatbot Development", "Autonomous AI chatbot for enterprise", "$15,000", "2026-12-01", "python,llm,fastapi"),
                    ("Quantum Cryptography", "Post-Quantum security protocol", "$25,000", "2026-11-15", "python,quantum"),
                    ("RAG Pipeline", "Build RAG for legal documents", "$8,000", "2026-10-30", "python,rag,langchain"),
                ]
            )

        # Seed courses
        if conn.execute("SELECT COUNT(*) c FROM courses").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT INTO courses (title,description,category,instructor,duration_min,level) VALUES (?,?,?,?,?,?)",
                [
                    ("Python for AI", "Master Python for AI dev", "Programming", "Dr. Sarah Chen", 180, "beginner"),
                    ("Deep Learning with PyTorch", "Build neural networks", "AI/ML", "Prof. Marcus Lee", 360, "intermediate"),
                    ("LLM Engineering", "Build production LLM apps", "AI/ML", "Priya Patel", 240, "advanced"),
                    ("MLOps Complete", "Deploy ML to production", "DevOps", "John Smith", 300, "intermediate"),
                ]
            )

        conn.commit()
        log.info("✅ Database ready: %s", DB_PATH)
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
    ("m28", "AI Sandbox & Code Execution", "Infrastructure"),
    ("m29", "Serverless AI Endpoint Hosting", "Infrastructure"),
    ("m30", "Autonomous Software Engineer Swarm", "Infrastructure"),
    ("m31", "AI Data Scraping & Web Extraction", "Infrastructure"),
    ("m32", "Autonomous SMM & Marketing", "Infrastructure"),
    ("m33", "AI Customer Support & Voice Bot", "Infrastructure"),
    ("m34", "Zero-Knowledge Proofs Sandbox", "Infrastructure"),
    ("m35", "Automated NDA & Smart Contracts", "Infrastructure"),
    ("m36", "Deepfake & Synthetic Media Audit", "Infrastructure"),
    ("m37", "WebXR & Spatial VR Showroom", "Infrastructure"),
    ("m38", "3D Generative Asset Factory", "Infrastructure"),
    ("m39", "Digital Twin Factory Simulation", "Infrastructure"),
    ("m40", "Custom GLSL Shader & Physics", "Infrastructure"),
    ("m41", "HFT Micro-Equity Exchange", "Infrastructure"),
    ("m42", "Global Crypto Escrow", "Infrastructure"),
    ("m43", "Micro-Equity Flash Loans", "Infrastructure"),
    ("m44", "AI Startup Crowdfunding", "Infrastructure"),
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
    ("m59", "Model Monitoring & Drift", "Developer Tools"),
    ("m60", "Feature Store", "Developer Tools"),
    ("m61", "Explainable AI (XAI)", "Developer Tools"),
    ("m62", "Federated Learning", "Developer Tools"),
    ("m63", "Synthetic Data Generation", "Developer Tools"),
    ("m64", "AI Governance & Compliance", "Developer Tools"),
]

MODULES = [
    {"id": mid, "name": name, "category": cat,
     "description": f"Advanced AI module for {cat}.", "active": True}
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


def user_from_token(token: Optional[str]):
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


def get_token(request: Request):
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return request.cookies.get("ercors_token")


async def current_user(request: Request):
    return user_from_token(get_token(request))


async def require_user(request: Request):
    u = await current_user(request)
    if not u:
        raise HTTPException(401, "Authentication required")
    return u


def make_ref_code(name: str) -> str:
    base = re.sub(r"[^A-Za-z]", "", name)[:4].upper() or "USER"
    return f"{base}{secrets.token_hex(3).upper()}"


def compute_tier(xp: int) -> str:
    if xp >= 100000: return "Legend"
    if xp >= 50000: return "Diamond"
    if xp >= 15000: return "Platinum"
    if xp >= 5000: return "Gold"
    if xp >= 1000: return "Silver"
    return "Bronze"

# ═══════════════════════════════════════════════════════════════════════════
# AI ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class AIEngine:
    KB = {
        "trust": "Trust Score = skills (30%) + projects (25%) + reviews (20%) + code quality (15%) + interview (10%). Range: 0-100.",
        "modules": "ERCORS has 64 modules across 7 categories: Core, Talent Sourcing, Data & Training, Hiring Tools, Direct & Premium, Infrastructure, Developer Tools.",
        "earn": "Earn via: bounty board ($1.5k-$12k), referrals ($50/signup), job matching ($100k-$500k), contests, hackathons.",
        "hire": "Hire via: AI Matching (1-sec), Video Interview Bot, Code Assessment, Skill Graph. Avg 48 hours.",
        "escrow": "Escrow locks funds until milestone. Supports USD/BTC/ETH/USDC. Platform fee: 0.5%.",
        "price": "ERCORS FREE forever. Premium: $19/month. Enterprise: custom.",
        "job": "Top hiring: Google (47), OpenAI (23), Meta (31), Microsoft (38), Anthropic (18), Nvidia (29). Avg $185k.",
        "learn": "Free courses: Python for AI, Deep Learning, LLM Engineering. Blockchain certificates.",
        "security": "SOC2, E2E encryption, zero-trust, PBKDF2 (100k iterations).",
        "bounty": "Bounty Board: OpenAI, Meta, Anthropic, DeepMind. $1,500-$12,000 per task.",
        "wallet": "Connect MetaMask, WalletConnect, or Coinbase for crypto payments and NFT minting.",
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
        if any(w in m for w in ["security", "audit", "safe", "password"]):
            return cls.KB["security"]
        if any(w in m for w in ["price", "cost", "fee"]):
            return cls.KB["price"]
        return f"Interesting! Tell me more about '{msg[:60]}'. I can help with hiring, learning, or earning."

    @classmethod
    def analyze_cv(cls, text: str):
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
            "summary": f"{role} with {exp}y experience, {len(found)} verified skills.",
        }

    @classmethod
    def analyze_interview(cls, transcript: str, position: str = "AI Engineer"):
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
# WEBSOCKET
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

    def count(self):
        return len(self.connections)


ws_mgr = WSManager()

# ═══════════════════════════════════════════════════════════════════════════
# FASTAPI APP
# ═══════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("🚀 ERCORS v13 starting...")
    init_db()
    log.info("✅ %d modules loaded", len(MODULES))
    yield
    log.info("👋 Shutdown")


app = FastAPI(title="ERCORS API", version="13.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════════════════════
# HEALTH & STATS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    return {
        "status": "ok", "version": "13.0.0",
        "modules": len(MODULES),
        "env": "render" if os.getenv("RENDER") else "local",
        "time": datetime.utcnow().isoformat(),
    }


@app.get("/api/stats")
def stats():
    conn = db()
    try:
        return {
            "users": conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] + 12847,
            "posts": conn.execute("SELECT COUNT(*) c FROM posts").fetchone()["c"],
            "campaigns": conn.execute("SELECT COUNT(*) c FROM campaigns").fetchone()["c"],
            "modules": len(MODULES),
            "ws_clients": ws_mgr.count(),
            "bounties_paid": 47830,
            "bounty_hunters": 1247,
        }
    finally:
        conn.close()


@app.get("/api/v1/live/stats")
def live_stats():
    return {
        "online_users": 12847 + secrets.randbelow(100),
        "earned_today": 4200000 + secrets.randbelow(100000),
        "joined_last_hour": 347 + secrets.randbelow(20),
        "modules": len(MODULES),
    }

# ═══════════════════════════════════════════════════════════════════════════
# AUTH ENDPOINTS
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
            return JSONResponse({"status": "error", "message": "Email already registered"}, status_code=409)

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
        conn.execute(
            "INSERT INTO notifications (user_id, title, body, type) VALUES (?,?,?,?)",
            (uid, "Welcome to ERCORS! 🎉", "Your 30-day free trial started. Enjoy $50 bonus!", "success"),
        )
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


@app.post("/api/me/update")
async def update_me(
    request: Request,
    full_name: Optional[str] = Form(None),
    company_name: Optional[str] = Form(None),
    skills: Optional[str] = Form(None),
    bio: Optional[str] = Form(None),
):
    user = await require_user(request)
    fields, values = [], []
    for k, v in [("full_name", full_name), ("company_name", company_name),
                 ("skills", skills), ("bio", bio)]:
        if v is not None:
            fields.append(f"{k}=?")
            values.append(v)
    if not fields:
        return {"status": "error", "message": "Nothing to update"}
    conn = db()
    try:
        values.append(user["id"])
        conn.execute(f"UPDATE users SET {','.join(fields)} WHERE id=?", values)
        conn.commit()
        updated = dict(conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone())
        updated.pop("password_hash", None)
        return {"status": "success", "user": updated}
    finally:
        conn.close()

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
        "module_id": mid, "module_name": m["name"], "category": m["category"],
        "executed_at": datetime.utcnow().isoformat(),
        "duration_ms": secrets.randbelow(500) + 50,
        "status": "success",
        "output": f"Module '{m['name']}' executed.",
    }
    if user:
        conn = db()
        try:
            conn.execute("UPDATE users SET xp = xp + 5 WHERE id=?", (user["id"],))
            conn.execute("INSERT INTO activity_log (user_id, action, target) VALUES (?,?,?)",
                         (user["id"], "module_run", mid))
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
            """SELECT id, full_name AS name, skills, user_type AS title,
                      trust_score, tier, xp, level
               FROM users WHERE user_type='expert'
               ORDER BY trust_score DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        results = [dict(r) for r in rows]
        if not results:
            results = [
                {"id": -1, "name": "Alice Johnson", "skills": "Python, PyTorch, LLM, FastAPI", "title": "Senior AI Engineer", "trust_score": 99.2, "tier": "Legend", "xp": 125000, "level": 250},
                {"id": -2, "name": "Bob Smith", "skills": "Rust, C++, Quantum, ZK Proofs", "title": "Systems Architect", "trust_score": 98.7, "tier": "Legend", "xp": 112000, "level": 224},
                {"id": -3, "name": "Carol White", "skills": "React, Node, TypeScript, GraphQL", "title": "Full-Stack Lead", "trust_score": 97.9, "tier": "Diamond", "xp": 89000, "level": 178},
                {"id": -4, "name": "David Chen", "skills": "Go, Kubernetes, Terraform, AWS", "title": "DevOps Architect", "trust_score": 98.1, "tier": "Diamond", "xp": 95000, "level": 190},
                {"id": -5, "name": "Elena Rodriguez", "skills": "Data Science, R, SQL, Tableau", "title": "Data Science Lead", "trust_score": 97.5, "tier": "Platinum", "xp": 42000, "level": 84},
            ]
        return results
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════════════
# CAMPAIGNS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/campaigns")
def list_campaigns(status: Optional[str] = None, limit: int = 50):
    conn = db()
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM campaigns WHERE status=? ORDER BY id DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM campaigns ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
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
        await ws_mgr.broadcast({
            "type": "new_campaign",
            "campaign": {"id": cur.lastrowid, "title": title, "budget": budget},
        })
        return {"status": "success", "id": cur.lastrowid}
    finally:
        conn.close()


@app.get("/api/campaigns/{cid}")
def get_campaign(cid: int):
    conn = db()
    try:
        row = conn.execute("SELECT * FROM campaigns WHERE id=?", (cid,)).fetchone()
        if not row:
            raise HTTPException(404, "Campaign not found")
        conn.execute("UPDATE campaigns SET views = views + 1 WHERE id=?", (cid,))
        conn.commit()
        return dict(row)
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════════════
# POSTS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/posts")
def list_posts(limit: int = 50, offset: int = 0):
    conn = db()
    try:
        rows = conn.execute(
            "SELECT * FROM posts ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/posts")
async def create_post(request: Request, content: str = Form(...)):
    user = await require_user(request)
    if len(content) > 2000:
        return JSONResponse({"status": "error", "message": "Content too long"}, status_code=400)
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
async def create_escrow(
    request: Request,
    title: str = Form(...),
    amount: float = Form(...),
    developer_name: Optional[str] = Form(None),
):
    user = await require_user(request)
    conn = db()
    try:
        cur = conn.execute(
            "INSERT INTO escrows (user_id, title, amount, developer_name) VALUES (?,?,?,?)",
            (user["id"], title, amount, developer_name),
        )
        conn.execute(
            "INSERT INTO transactions (user_id, type, amount, reference) VALUES (?,?,?,?)",
            (user["id"], "escrow_lock", amount, f"ESC-{cur.lastrowid}"),
        )
        conn.commit()
        return {"status": "success", "id": cur.lastrowid}
    finally:
        conn.close()


@app.post("/api/escrow/{eid}/release")
async def release_escrow(eid: int, request: Request):
    user = await require_user(request)
    conn = db()
    try:
        row = conn.execute("SELECT * FROM escrows WHERE id=? AND user_id=?", (eid, user["id"])).fetchone()
        if not row:
            raise HTTPException(404, "Escrow not found")
        if row["status"] != "active":
            return {"status": "error", "message": "Escrow not active"}
        conn.execute("UPDATE escrows SET status='released', released_at=datetime('now') WHERE id=?", (eid,))
        conn.execute(
            "INSERT INTO transactions (user_id, type, amount, reference) VALUES (?,?,?,?)",
            (user["id"], "escrow_release", row["amount"], f"ESC-{eid}-RELEASE"),
        )
        conn.commit()
        await ws_mgr.broadcast({"type": "escrow_released", "id": eid, "amount": row["amount"]})
        return {"status": "success"}
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════════════
# LEADERBOARD
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/leaderboard")
def leaderboard(type: str = "referrals", limit: int = 10):
    conn = db()
    try:
        if type == "xp":
            rows = conn.execute(
                "SELECT full_name AS name, xp, tier, level FROM users WHERE xp > 50 ORDER BY xp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [{"rank": i, "name": r["name"], "xp": r["xp"], "tier": r["tier"], "level": r["level"]}
                    for i, r in enumerate(rows, 1)]

        rows = conn.execute(
            """SELECT full_name AS name, referred_count AS referrals,
                      referral_earnings AS reward_num
               FROM users WHERE referred_count > 0
               ORDER BY referred_count DESC LIMIT ?""",
            (limit,),
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
            ]
        return result
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════════════
# BADGES & STREAK
# ═══════════════════════════════════════════════════════════════════════════

BADGE_XP = {"first": 50, "sharer": 100, "inviter": 200, "ai": 500,
            "vip": 1000, "founder": 5000, "bounty_hunter": 1500,
            "quiz_master": 800, "top_referrer": 2000, "legend": 10000}


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
            return {"status": "error", "message": "Badge already claimed"}
        xp_add = BADGE_XP[badge_key]
        conn.execute("UPDATE users SET xp = xp + ? WHERE id=?", (xp_add, user["id"]))
        row = conn.execute("SELECT xp FROM users WHERE id=?", (user["id"],)).fetchone()
        new_xp = row["xp"]
        new_level = 1 + new_xp // 500
        new_tier = compute_tier(new_xp)
        conn.execute("UPDATE users SET level=?, tier=? WHERE id=?", (new_level, new_tier, user["id"]))
        conn.commit()
        return {"status": "success", "xp_awarded": xp_add, "total_xp": new_xp,
                "level": new_level, "tier": new_tier}
    finally:
        conn.close()


@app.get("/api/badges")
async def list_badges(request: Request):
    user = await current_user(request)
    if not user:
        return []
    conn = db()
    try:
        rows = conn.execute("SELECT badge_key, claimed_at FROM badges WHERE user_id=?",
                            (user["id"],)).fetchall()
        return [dict(r) for r in rows]
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
            conn.execute("INSERT INTO activity_log (user_id, action, target) VALUES (?,?,?)",
                         (user["id"], "share", platform))
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


@app.get("/api/v1/ai/history")
async def chat_history(request: Request, limit: int = 50):
    user = await current_user(request)
    if not user:
        return []
    conn = db()
    try:
        rows = conn.execute(
            "SELECT role, message, created_at FROM chat_log WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user["id"], limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════════════
# BADGE SVG
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/badge/{user_id}.svg")
def badge_svg(user_id: str):
    name, score, tier = "Guest", 0, "Bronze"
    if user_id != "guest":
        try:
            conn = db()
            row = conn.execute("SELECT full_name, trust_score, tier FROM users WHERE id=?",
                               (int(user_id),)).fetchone()
            if row:
                name, score, tier = row["full_name"], row["trust_score"], row["tier"] or "Bronze"
            conn.close()
        except Exception:
            pass

    colors = {"Bronze": "#cd7f32", "Silver": "#c0c0c0", "Gold": "#fbbf24",
              "Platinum": "#a78bfa", "Diamond": "#22d3ee", "Legend": "#ef4444"}
    tc = colors.get(tier, "#00f0ff")

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="320" height="120" viewBox="0 0 320 120">
  <defs><linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="#00f0ff"/><stop offset="100%" stop-color="#7000ff"/>
  </linearGradient></defs>
  <rect width="320" height="120" rx="12" fill="#030712"/>
  <rect x="2" y="2" width="316" height="116" rx="11" fill="none" stroke="url(#g)" stroke-width="2"/>
  <text x="20" y="40" font-family="Arial" font-size="20" font-weight="800" fill="#00f0ff">ERCORS</text>
  <text x="20" y="65" font-family="Arial" font-size="14" fill="#ffffff">{name[:24]}</text>
  <text x="20" y="90" font-family="Arial" font-size="12" fill="#94a3b8">Trust: {score} · {tier}</text>
  <circle cx="285" cy="90" r="8" fill="{tc}"/>
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
    if name.endswith(".docx"):
        try:
            import zipfile
            from io import BytesIO
            with zipfile.ZipFile(BytesIO(data)) as z:
                if "word/document.xml" in z.namelist():
                    xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
                    text = re.sub(r"<[^>]+>", " ", xml)
                    return re.sub(r"\s+", " ", text)[:10000]
        except Exception:
            pass
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
        campaigns = conn.execute("SELECT * FROM campaigns WHERE status='Open'").fetchall()
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
# HR — AUDIO
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
        f"Simulated {language} interview transcript. Candidate shows strong technical "
        "expertise, clear communication, problem-solving. 5+ years AI/ML."
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
# HARVESTER / NEGOTIATOR
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
            "company": company_name, "developer": developer_name,
            "budget": final, "deadline": f"{secrets.choice([14, 21, 30, 45])} days",
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
            return JSONResponse({"status": "error", "message": "Bounty not found"}, status_code=404)
        if row["claimed_by"]:
            return JSONResponse({"status": "error", "message": "Already claimed"}, status_code=409)
        conn.execute("UPDATE bounties SET claimed_by=?, claimed_at=datetime('now'), status='claimed' WHERE id=?",
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
# QUIZ / PERSONALITY
# ═══════════════════════════════════════════════════════════════════════════

QUIZ_QUESTIONS = [
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
    {"q": "What is RAG?",
     "opts": ["Rapid AI Generation", "Retrieval Augmented Generation", "Random Access Gateway", "Real-time Analytics"],
     "answer_index": 1},
]


@app.get("/api/v1/quiz/questions")
def quiz_questions(limit: int = 5):
    return [{"q": q["q"], "opts": q["opts"], "answer_index": q["answer_index"]} for q in QUIZ_QUESTIONS[:limit]]


@app.post("/api/v1/quiz/submit")
async def quiz_submit(
    request: Request,
    answers: str = Form(...),
    time_taken: int = Form(0),
):
    user = await current_user(request)
    try:
        answer_list = [int(a) for a in answers.split(",")]
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid format"}, status_code=400)

    total = len(answer_list)
    correct = sum(1 for i, a in enumerate(answer_list)
                  if i < len(QUIZ_QUESTIONS) and a == QUIZ_QUESTIONS[i]["answer_index"])
    score_pct = round((correct / total) * 100) if total else 0

    if user:
        conn = db()
        try:
            conn.execute("INSERT INTO quiz_results (user_id, score, total, time_taken) VALUES (?,?,?,?)",
                         (user["id"], correct, total, time_taken))
            conn.execute("UPDATE users SET xp = xp + ? WHERE id=?", (correct * 20, user["id"]))
            conn.commit()
        finally:
            conn.close()

    return {"status": "success", "correct": correct, "total": total,
            "score_pct": score_pct, "passed": score_pct >= 60}


@app.get("/api/v1/personality/questions")
def personality_questions():
    return [
        {"q": "What excites you most?", "opts": [
            {"text": "Building AI systems", "value": "tech"},
            {"text": "Earning money", "value": "money"},
            {"text": "Learning new skills", "value": "learn"},
            {"text": "Meeting people", "value": "social"}]},
        {"q": "How do you handle challenges?", "opts": [
            {"text": "Code a solution", "value": "tech"},
            {"text": "Outsource it", "value": "money"},
            {"text": "Research deeply", "value": "learn"},
            {"text": "Ask the community", "value": "social"}]},
        {"q": "Your dream job is:", "opts": [
            {"text": "AI Engineer at Big Tech", "value": "tech"},
            {"text": "AI startup founder", "value": "money"},
            {"text": "Senior Data Scientist", "value": "learn"},
            {"text": "AI community leader", "value": "social"}]},
    ]


@app.post("/api/v1/personality/result")
async def personality_result(answers: str = Form(...)):
    values = [v.strip() for v in answers.split(",") if v.strip()]
    counts = Counter(values)
    top = counts.most_common(1)[0][0] if counts else "tech"
    results = {
        "tech": {"icon": "🤖", "title": "AI Builder", "desc": "Technical mastermind!", "salary": "$120k-250k"},
        "money": {"icon": "💰", "title": "AI Entrepreneur", "desc": "Business instincts!", "salary": "$80k-500k"},
        "learn": {"icon": "📚", "title": "AI Scholar", "desc": "Love deep learning!", "salary": "$100k-200k"},
        "social": {"icon": "🌟", "title": "AI Community Leader", "desc": "Inspire others!", "salary": "$90k-180k"},
    }
    return {"status": "success", "type": top, "result": results[top]}

# ═══════════════════════════════════════════════════════════════════════════
# COMPANIES / MENTORS / COURSES
# ═══════════════════════════════════════════════════════════════════════════

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


@app.get("/api/v1/courses")
def list_courses():
    conn = db()
    try:
        rows = conn.execute("SELECT * FROM courses").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════════════
# PORTFOLIO / SALARY / SKILLS
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/portfolio/generate")
def gen_portfolio(name: str = Form(...), title: str = Form(...),
                  skills: str = Form(...), theme: str = Form("neon")):
    return {"status": "success", "theme": theme, "name": name, "title": title,
            "skills": [s.strip() for s in skills.split(",") if s.strip()]}


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

# ═══════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS / TRANSACTIONS / TEAMS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/notifications")
async def list_notifications(request: Request, limit: int = 20):
    user = await current_user(request)
    if not user:
        return []
    conn = db()
    try:
        rows = conn.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT ?",
                            (user["id"], limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/transactions")
async def list_transactions(request: Request, limit: int = 20):
    user = await require_user(request)
    conn = db()
    try:
        rows = conn.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT ?",
                            (user["id"], limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/teams/leaderboard")
def teams_leaderboard():
    return [
        {"name": "🚀 Rockets", "members": 1247, "score": 98765},
        {"name": "🔥 Phoenixes", "members": 1189, "score": 95432},
        {"name": "💎 Diamonds", "members": 1054, "score": 89123},
    ]

# ═══════════════════════════════════════════════════════════════════════════
# WEBSOCKET
# ═══════════════════════════════════════════════════════════════════════════

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
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

# ═══════════════════════════════════════════════════════════════════════════
# STATIC FILES
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
def root():
    if INDEX_HTML.exists():
        return FileResponse(INDEX_HTML)
    return HTMLResponse("<h1>ERCORS Backend Running ✅</h1><p>Add index.html</p>")


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
    log.info("ERCORS v13 Backend")
    log.info("Port: %d", PORT)
    log.info("DB: %s", DB_PATH)
    log.info("Modules: %d", len(MODULES))
    log.info("=" * 60)
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False, log_level="info")
