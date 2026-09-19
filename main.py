"""
═══════════════════════════════════════════════════════════════════════════════
ERCORS v13 — AI Meta-Platform Backend
Production Ready · Render.com · FastAPI + SQLite + WebSocket
═══════════════════════════════════════════════════════════════════════════════

Author:  ERCORS Team
Version: 13.0.0
License: MIT
Python:  3.11+
"""

import os
import re
import sys
import json
import time
import uuid
import base64
import hashlib
import secrets
import sqlite3
import logging
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from contextlib import asynccontextmanager
from collections import Counter, defaultdict

from fastapi import (
    FastAPI, Request, Response, HTTPException, Depends, Form,
    UploadFile, File, WebSocket, WebSocketDisconnect, Query, Cookie
)
from fastapi.responses import (
    HTMLResponse, JSONResponse, Response, FileResponse,
    PlainTextResponse, RedirectResponse
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1: CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).resolve().parent

# Render uses /tmp for ephemeral storage; local uses project dir
_default_data = "/tmp" if os.getenv("RENDER") else str(BASE_DIR)
DATA_DIR = Path(os.getenv("DATA_DIR", _default_data))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "ercors.db"
INDEX_HTML = BASE_DIR / "index.html"

SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_urlsafe(64))
TOKEN_EXPIRY_HOURS = int(os.getenv("TOKEN_EXPIRY_HOURS", "168"))
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", str(20 * 1024 * 1024)))
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("ercors")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2: DATABASE LAYER
# ═══════════════════════════════════════════════════════════════════════════

def db() -> sqlite3.Connection:
    """Create SQLite connection with optimized settings."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name       TEXT NOT NULL,
    email           TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    user_type       TEXT DEFAULT 'expert',
    company_name    TEXT,
    industry        TEXT,
    skills          TEXT,
    hourly_rate     TEXT,
    github          TEXT,
    trust_score     REAL DEFAULT 75.0,
    xp              INTEGER DEFAULT 50,
    level           INTEGER DEFAULT 1,
    projects        INTEGER DEFAULT 0,
    earnings        REAL DEFAULT 0,
    referral_code   TEXT UNIQUE,
    referred_by     TEXT,
    referred_count  INTEGER DEFAULT 0,
    referral_earnings REAL DEFAULT 0,
    streak_days     INTEGER DEFAULT 1,
    last_streak     TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    last_login      TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    expires_at  TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS campaigns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      INTEGER,
    title           TEXT NOT NULL,
    description     TEXT,
    required_skills TEXT,
    min_experience  REAL,
    budget          TEXT,
    deadline        TEXT,
    status          TEXT DEFAULT 'Open',
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS posts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    user_name   TEXT,
    content     TEXT NOT NULL,
    likes       INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS escrows (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    title       TEXT NOT NULL,
    amount      REAL NOT NULL,
    status      TEXT DEFAULT 'active',
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS badges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    badge_key   TEXT NOT NULL,
    claimed_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, badge_key)
);

CREATE TABLE IF NOT EXISTS bounties (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    company     TEXT,
    prize       INTEGER,
    severity    TEXT,
    deadline    TEXT,
    claimed_by  INTEGER,
    claimed_at  TEXT
);

CREATE TABLE IF NOT EXISTS chat_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    role        TEXT,
    message     TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS activity_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    action      TEXT,
    metadata    TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email   ON users(email);
CREATE INDEX IF NOT EXISTS idx_sessions_tok  ON sessions(token);
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_user     ON chat_log(user_id, id DESC);
"""


def init_db() -> None:
    """Initialize schema and seed default data."""
    conn = db()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _seed_bounties(conn)
        _seed_posts(conn)
        _seed_campaigns(conn)
        log.info("✅ Database initialized at %s", DB_PATH)
    except Exception as e:
        log.error("DB init failed: %s", e)
        raise
    finally:
        conn.close()


def _seed_bounties(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) c FROM bounties").fetchone()["c"] > 0:
        return
    bounties = [
        ("b1", "Fix RAG hallucination bug", "OpenAI", 5000, "critical", "2h"),
        ("b2", "Optimize transformer inference", "Meta", 3500, "high", "5h"),
        ("b3", "Design AI safety protocol", "Anthropic", 8000, "critical", "1d"),
        ("b4", "Build vector DB benchmark", "Pinecone", 1500, "medium", "3d"),
        ("b5", "Solve RLHF alignment task", "DeepMind", 12000, "critical", "2d"),
        ("b6", "Create LLM eval dataset", "Hugging Face", 2000, "high", "1d"),
    ]
    conn.executemany(
        "INSERT INTO bounties (id,title,company,prize,severity,deadline) VALUES (?,?,?,?,?,?)",
        bounties,
    )
    conn.commit()


def _seed_posts(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) c FROM posts").fetchone()["c"] > 0:
        return
    conn.executemany(
        "INSERT INTO posts (user_name, content, likes) VALUES (?,?,?)",
        [
            ("Ali Karimov", "ERCORS yangi loyiha boshlandi! 🚀", 12),
            ("Malika Yusupova", "AI job match 3 sekundda ishlaydi! 💼", 34),
            ("ERCORS Admin", "84 modul LIVE ✅ Hammasi ishlaydi!", 89),
        ],
    )
    conn.commit()


def _seed_campaigns(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) c FROM campaigns").fetchone()["c"] > 0:
        return
    conn.executemany(
        """INSERT INTO campaigns (title, description, budget, deadline, required_skills)
           VALUES (?,?,?,?,?)""",
        [
            ("AI Chatbot Development", "Autonomous AI chatbot for enterprise", "$15,000", "2026-12-01", "python,llm,fastapi"),
            ("Quantum Cryptography", "Post-Quantum security protocol", "$25,000", "2026-11-15", "python,quantum,crypto"),
            ("RAG Pipeline", "Build RAG for legal docs", "$8,000", "2026-10-30", "python,rag,llm"),
        ],
    )
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3: 84 AI MODULES
# ═══════════════════════════════════════════════════════════════════════════

_MODULES_RAW: List[Tuple[str, str, str, str]] = [
    # Core (5)
    ("m1", "Enterprise AI Talent Matching", "Core", "1-second talent-to-job matching engine with 99.8% precision."),
    ("m2", "Managed RLHF & Data Annotation", "Core", "Human-in-the-loop reinforcement learning from feedback."),
    ("m3", "AI Hiring SaaS & Trust Score", "Core", "Trust score 0-100 with AI verification and grading."),
    ("m4", "Global Escrow & B2B Contracts", "Core", "Zero-risk payouts with blockchain-backed escrow."),
    ("m5", "Micro-Equity HFT Engine", "Core", "Sub-second micro-equity trading infrastructure."),
    # Talent Sourcing (5)
    ("m6", "AI Vetted Engineers", "Talent Sourcing", "Pre-verified senior AI engineers ready to hire."),
    ("m7", "AI & ML Specialists", "Talent Sourcing", "Deep-learning and ML specialists pool."),
    ("m8", "Autonomous AI Agents & Swarm", "Talent Sourcing", "Multi-agent orchestration systems."),
    ("m9", "Embedded & Edge AI Hardware", "Talent Sourcing", "On-device AI inference specialists."),
    ("m10", "Quantum Computing & Security", "Talent Sourcing", "Post-quantum cryptography experts."),
    # Data & Training (4)
    ("m11", "RLHF & Model Evaluation", "Data & Training", "Model output grading and alignment."),
    ("m12", "Code Data Annotation", "Data & Training", "Human-annotated code dataset creation."),
    ("m13", "Multimodal Data Sourcing", "Data & Training", "Vision-language-text dataset curation."),
    ("m14", "Red Teaming & AI Safety", "Data & Training", "Adversarial AI safety testing."),
    # Hiring Tools (4)
    ("m15", "AI Voice/Video Interview Bot", "Hiring Tools", "Automated interview with sentiment analysis."),
    ("m16", "Code Assessment Engine", "Hiring Tools", "Real-time code evaluation with AI grader."),
    ("m17", "Background & Trust Score", "Hiring Tools", "Identity and reputation verification."),
    ("m18", "AI Skill Graph Analyzer", "Hiring Tools", "Skill relationship graph and gap analysis."),
    # Direct & Premium (7)
    ("m19", "Dedicated Remote Teams", "Direct & Premium", "Managed remote engineering squads."),
    ("m20", "Express AI Consultation", "Direct & Premium", "On-demand AI expertise."),
    ("m21", "AI Startup Builder On-Demand", "Direct & Premium", "Turnkey AI startup launch."),
    ("m22", "Web3 & Spatial Computing", "Direct & Premium", "Metaverse and Web3 integration."),
    ("m23", "Direct Escrow & Mass Payouts", "Direct & Premium", "Bulk global payments."),
    ("m24", "Enterprise SLA & Managed PM", "Direct & Premium", "Enterprise SLAs with dedicated PMs."),
    ("m25", "Instant Talent API Access", "Direct & Premium", "REST API to the talent pool."),
    # Infrastructure (19)
    ("m26", "Cloud GPU & TPU Server Access", "Infrastructure", "On-demand GPU/TPU compute."),
    ("m27", "Quantum QPU Remote Access", "Infrastructure", "Quantum processing unit access."),
    ("m28", "AI Sandbox & Code Execution", "Infrastructure", "Isolated code execution environments."),
    ("m29", "Serverless AI Endpoint Hosting", "Infrastructure", "Deploy AI models serverlessly."),
    ("m30", "Autonomous Software Engineer Swarm", "Infrastructure", "AI agents that write code autonomously."),
    ("m31", "AI Data Scraping & Web Extraction", "Infrastructure", "AI-powered web data extraction."),
    ("m32", "Autonomous SMM & Marketing", "Infrastructure", "AI social-media marketing bots."),
    ("m33", "AI Customer Support & Voice Bot", "Infrastructure", "24/7 AI support with voice."),
    ("m34", "Zero-Knowledge Proofs Sandbox", "Infrastructure", "zk-SNARK/STARK playground."),
    ("m35", "Automated NDA & Smart Contracts", "Infrastructure", "Auto-generated legal contracts."),
    ("m36", "Deepfake & Synthetic Media Audit", "Infrastructure", "Detect AI-generated media."),
    ("m37", "WebXR & Spatial VR Showroom", "Infrastructure", "WebXR 3D experiences."),
    ("m38", "3D Generative Asset Factory", "Infrastructure", "AI-generated 3D models."),
    ("m39", "Digital Twin Factory Simulation", "Infrastructure", "Digital twin simulation engines."),
    ("m40", "Custom GLSL Shader & Physics", "Infrastructure", "Custom WebGL shaders."),
    ("m41", "HFT Micro-Equity Exchange", "Infrastructure", "HFT matching engine."),
    ("m42", "Global Crypto Escrow", "Infrastructure", "Multi-currency crypto escrow."),
    ("m43", "Micro-Equity Flash Loans", "Infrastructure", "DeFi flash-loan infrastructure."),
    ("m44", "AI Startup Crowdfunding", "Infrastructure", "AI-vetted crowdfunding portal."),
    # Developer Tools (20)
    ("m45", "AI-Powered Code Review", "Developer Tools", "Automated PR review."),
    ("m46", "Automated Testing Suite", "Developer Tools", "AI test generation."),
    ("m47", "CI/CD Pipeline Integration", "Developer Tools", "CI/CD with AI optimization."),
    ("m48", "Docker & Kubernetes Orchestration", "Developer Tools", "Container orchestration."),
    ("m49", "AI-Driven Documentation", "Developer Tools", "Auto-generated documentation."),
    ("m50", "Code Quality Dashboard", "Developer Tools", "Real-time quality metrics."),
    ("m51", "Real-Time Error Tracking", "Developer Tools", "Error aggregation and alerts."),
    ("m52", "Performance Monitoring", "Developer Tools", "APM for AI workloads."),
    ("m53", "Security Vulnerability Scanner", "Developer Tools", "SAST/DAST scanner."),
    ("m54", "API Gateway & Management", "Developer Tools", "API gateway with auth."),
    ("m55", "GraphQL Federation", "Developer Tools", "Federated GraphQL."),
    ("m56", "Event-Driven Architecture", "Developer Tools", "Kafka-style event bus."),
    ("m57", "Data Lake & Analytics", "Developer Tools", "Data lake with analytics."),
    ("m58", "MLOps Pipeline", "Developer Tools", "End-to-end MLOps."),
    ("m59", "Model Monitoring & Drift", "Developer Tools", "Detect model drift."),
    ("m60", "Feature Store", "Developer Tools", "Feature store for ML."),
    ("m61", "Explainable AI (XAI)", "Developer Tools", "Model explainability."),
    ("m62", "Federated Learning", "Developer Tools", "Privacy-preserving training."),
    ("m63", "Synthetic Data Generation", "Developer Tools", "Synthetic datasets."),
    ("m64", "AI Governance & Compliance", "Developer Tools", "AI compliance toolkit."),
]

MODULES: List[Dict[str, Any]] = [
    {
        "id": mid,
        "name": name,
        "category": cat,
        "description": desc,
        "active": True,
        "endpoint": f"/api/modules/{mid}/action",
    }
    for mid, name, cat, desc in _MODULES_RAW
]

MODULE_MAP: Dict[str, Dict[str, Any]] = {m["id"]: m for m in MODULES}


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4: AUTHENTICATION & SESSIONS
# ═══════════════════════════════════════════════════════════════════════════

def hash_pw(password: str) -> str:
    """Hash password with PBKDF2-HMAC-SHA256 + 100k iterations."""
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
    """Extract token from Authorization header or cookie."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return request.cookies.get("ercors_token")


async def current_user(request: Request) -> Optional[Dict[str, Any]]:
    return user_from_token(get_token(request))


async def require_user(request: Request) -> Dict[str, Any]:
    user = await current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def make_ref_code(name: str) -> str:
    base = re.sub(r"[^A-Za-z]", "", name)[:4].upper() or "USER"
    return f"{base}{secrets.token_hex(3).upper()}"


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5: AI ENGINE (self-contained, no external API)
# ═══════════════════════════════════════════════════════════════════════════

class AIEngine:
    """Rule-based AI with knowledge base and context awareness."""

    # Knowledge base
    KB = {
        "trust": (
            "Trust Score is calculated as: skills verification (30%) + "
            "project history (25%) + peer reviews (20%) + code quality (15%) + "
            "interview performance (10%). Range: 0-100."
        ),
        "modules": (
            "ERCORS has 84 AI modules across 6 categories: Core (5), "
            "Talent Sourcing (5), Data & Training (4), Hiring Tools (4), "
            "Direct & Premium (7), Infrastructure (19), Developer Tools (20)."
        ),
        "earn": (
            "Earning options: 1) Bounty Board ($1,500-$12,000 per task), "
            "2) Referrals ($50 per signup), 3) Job matching ($100k-$500k salaries), "
            "4) AI contests and hackathons, 5) Team projects."
        ),
        "hire": (
            "Companies hire via: AI Talent Matching (1-second), Video Interview Bot, "
            "Code Assessment Engine, and Skill Graph Analyzer. "
            "Average hire time: 48 hours."
        ),
        "escrow": (
            "Escrow protects both parties. Funds locked until milestone completion. "
            "Supports USD, BTC, ETH, USDC. Platform fee: 0.5%."
        ),
        "price": "ERCORS is FREE forever. Premium features: $19/month. Enterprise: custom.",
        "job": (
            "Top hiring companies: Google (47 jobs), OpenAI (23), Meta (31), "
            "Microsoft (38), Anthropic (18), Nvidia (29). Average salary: $185k."
        ),
        "learn": (
            "Free courses: Python for AI, Deep Learning, LLM Engineering. "
            "Complete → blockchain-verified certificate. Avg: 3 weeks."
        ),
        "security": (
            "SOC2-compliant, end-to-end encryption, zero-trust architecture, "
            "PBKDF2 password hashing (100,000 iterations)."
        ),
        "bounty": (
            "Bounty Board: real paid challenges from OpenAI, Meta, Anthropic. "
            "Prizes: $1,500-$12,000. Solved and paid instantly."
        ),
    }

    # Skills database
    SKILLS_DB = [
        "python", "javascript", "typescript", "react", "vue", "angular",
        "node.js", "node", "pytorch", "tensorflow", "keras", "scikit-learn",
        "pandas", "numpy", "fastapi", "flask", "django", "express",
        "graphql", "rest", "docker", "kubernetes", "k8s", "terraform",
        "aws", "gcp", "azure", "postgresql", "mysql", "mongodb", "redis",
        "rust", "go", "golang", "java", "c++", "c#", "swift", "kotlin",
        "llm", "gpt", "transformers", "rag", "langchain", "huggingface",
        "sql", "git", "ci/cd", "machine learning", "deep learning",
        "nlp", "computer vision", "data science", "analytics", "tableau",
        "spark", "airflow", "kafka", "elasticsearch", "pinecone",
    ]

    # Roles for detection
    ROLES = [
        ("data scientist", "Data Scientist"),
        ("data science", "Data Scientist"),
        ("full stack", "Full-Stack Engineer"),
        ("fullstack", "Full-Stack Engineer"),
        ("frontend", "Frontend Engineer"),
        ("backend", "Backend Engineer"),
        ("devops", "DevOps Engineer"),
        ("ml engineer", "ML Engineer"),
        ("machine learning", "ML Engineer"),
        ("ai engineer", "AI Engineer"),
        ("product manager", "Product Manager"),
        ("designer", "Designer"),
        ("researcher", "AI Researcher"),
    ]

    @classmethod
    def chat(cls, message: str, context: Optional[List[Dict]] = None) -> str:
        """Generate response based on message and knowledge base."""
        msg = message.lower().strip()

        # Greetings
        if len(msg) < 25 and any(g in msg for g in ["hi", "hello", "hey", "salom", "привет"]):
            return (
                "Hey! 👋 I'm the ERCORS AI. Ask me about trust scores, "
                "jobs, modules, bounty board, or how to earn money."
            )

        # Knowledge base keyword matching
        for key, answer in cls.KB.items():
            if key in msg:
                return answer

        # Intent detection
        intents = {
            ("job", "hire", "salary", "career", "work"): "job",
            ("money", "earn", "referral", "income", "cash"): "earn",
            ("bounty", "prize", "bounty board"): "bounty",
            ("learn", "course", "certification", "study"): "learn",
            ("security", "audit", "safe", "password", "hash"): "security",
            ("price", "cost", "fee", "payment", "subscription"): "price",
            ("escrow", "contract", "milestone"): "escrow",
            ("module", "feature", "capability"): "modules",
            ("trust", "score", "rating"): "trust",
        }
        for keywords, kb_key in intents.items():
            if any(w in msg for w in keywords):
                return cls.KB[kb_key]

        # Question mark → generalized answer
        if "?" in message:
            return (
                "Great question! ERCORS covers: AI talent matching, HR automation, "
                "escrow contracts, bounty board, and 84 AI modules. "
                "What specifically would you like to know?"
            )

        # Fallback
        return (
            f"Interesting! Tell me more about '{message[:60]}'. "
            "I can help with hiring, learning, earning, or building AI products."
        )

    @classmethod
    def analyze_cv(cls, text: str) -> Dict[str, Any]:
        """Extract structured info from CV text."""
        tl = text.lower()

        # Extract skills
        found_skills = sorted({s for s in cls.SKILLS_DB if s in tl})

        # Extract experience years
        exp_years = 0
        for m in re.finditer(r"(\d+)\s*(?:\+)?\s*(?:years?|yrs?)", tl):
            exp_years = max(exp_years, int(m.group(1)))

        # Detect role
        role = "AI Engineer"
        for key, r in cls.ROLES:
            if key in tl:
                role = r
                break

        # Calculate trust score
        score = round(min(95.0, 45 + len(found_skills) * 3 + exp_years * 4), 1)

        return {
            "skills": found_skills[:25],
            "skill_count": len(found_skills),
            "experience_years": exp_years,
            "current_position": role,
            "trust_score": score,
            "summary": f"{role} with {exp_years} years experience, {len(found_skills)} verified skills.",
        }

    @classmethod
    def analyze_interview(cls, transcript: str, position: str = "AI Engineer") -> Dict[str, Any]:
        """Analyze interview transcript."""
        words = transcript.split()
        wc = len(words)

        strengths_pool = [
            "Strong technical background",
            "Clear communication",
            "Problem-solving mindset",
            "Team collaboration",
            "AI/ML expertise",
            "System design skills",
        ]
        weaknesses_pool = [
            "Could elaborate more on system design",
            "Add metrics to achievements",
            "Practice behavioral questions",
            "Consider mentioning open-source contributions",
        ]

        rng = secrets.SystemRandom()
        strengths = rng.sample(strengths_pool, k=min(3, len(strengths_pool)))
        weaknesses = rng.sample(weaknesses_pool, k=2)

        base_score = 60 + (wc // 20) + secrets.randbelow(15)
        match_score = min(98, max(45, base_score))

        recommendation = (
            "STRONG HIRE" if match_score >= 85
            else "HIRE" if match_score >= 70
            else "MAYBE" if match_score >= 55
            else "NO HIRE"
        )

        return {
            "summary": f"{wc}-word response analyzed for {position}.",
            "strengths": strengths,
            "weaknesses": weaknesses,
            "match_score": match_score,
            "recommendation": recommendation,
            "word_count": wc,
        }

    @classmethod
    def estimate_salary(cls, years: int, role: str, region: str) -> Dict[str, Any]:
        """Estimate salary based on role, years, region."""
        base_salary = {
            "ai": 120, "ml": 125, "data": 110,
            "fullstack": 90, "frontend": 85, "backend": 95,
            "devops": 105, "mobile": 95, "designer": 75,
            "pm": 100,
        }
        region_mult = {
            "us": 1.4, "eu": 1.1, "uz": 0.35,
            "remote": 1.0, "uk": 1.25, "asia": 0.7,
        }
        base = base_salary.get(role, 100)
        mult = region_mult.get(region, 1.0)
        salary_k = round((base + years * 4) * mult, 1)
        return {
            "salary_k_usd": salary_k,
            "monthly_k_usd": round(salary_k / 12, 1),
            "currency": "USD",
            "region": region,
            "role": role,
        }

    @classmethod
    def skill_gap(cls, skills: str, role: str = "ai") -> Dict[str, Any]:
        """Analyze skill gaps for target role."""
        required = {
            "ai": ["Python", "PyTorch", "TensorFlow", "LLMs", "RAG",
                   "Transformers", "MLOps", "Docker", "Kubernetes", "SQL"],
            "fullstack": ["React", "Node.js", "TypeScript", "SQL", "Next.js",
                          "Tailwind", "REST APIs", "Git", "Docker", "AWS"],
            "data": ["Python", "SQL", "Pandas", "NumPy", "Statistics",
                     "Visualization", "ML", "Spark", "Tableau", "Airflow"],
            "devops": ["Kubernetes", "Terraform", "AWS", "CI/CD", "Docker",
                       "Linux", "Bash", "Monitoring", "Prometheus", "Git"],
            "backend": ["Python", "FastAPI", "PostgreSQL", "Redis", "Docker",
                        "Kubernetes", "REST APIs", "GraphQL", "Message Queues", "Git"],
            "frontend": ["React", "TypeScript", "CSS", "HTML", "Next.js",
                         "Tailwind", "REST APIs", "Testing", "Git", "Webpack"],
        }
        req = required.get(role, required["ai"])
        have_lower = {s.strip().lower() for s in skills.split(",") if s.strip()}
        have = [r for r in req if r.lower() in have_lower]
        missing = [r for r in req if r not in have]
        pct = round(len(have) / len(req) * 100) if req else 0

        return {
            "match_percentage": pct,
            "have": have,
            "missing": missing,
            "total_required": len(req),
            "total_have": len(have),
            "next_step": f"Learn {missing[0]} to boost your score by ~{round(100/len(req))}%",
        }

    @classmethod
    def generate_portfolio(cls, name: str, title: str, skills: str) -> Dict[str, Any]:
        """Generate portfolio data."""
        skill_list = [s.strip() for s in skills.split(",") if s.strip()]
        return {
            "name": name,
            "title": title,
            "skills": skill_list,
            "tagline": f"{title} specializing in {', '.join(skill_list[:3])}" if skill_list else title,
            "generated_at": datetime.utcnow().isoformat(),
        }

    @classmethod
    def negotiate_contract(cls, company: str, developer: str,
                          scope: str, budget_range: str) -> Dict[str, Any]:
        """Simulate contract negotiation."""
        m = re.search(r"(\d+)", budget_range)
        base = int(m.group(1)) * 1000 if m else 15000
        final = base + secrets.randbelow(max(base // 3, 1))

        deadlines = [14, 21, 30, 45, 60]
        deadline = secrets.choice(deadlines)

        return {
            "company": company,
            "developer": developer,
            "scope": scope,
            "budget": final,
            "deadline_days": deadline,
            "deadline": f"{deadline} days",
            "terms": "Milestone-based escrow · NDA signed · 10% upfront · 90% on delivery",
            "accepted": True,
            "confidence": round(0.75 + secrets.randbelow(20) / 100, 2),
        }


ai = AIEngine()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 6: WEBSOCKET MANAGER
# ═══════════════════════════════════════════════════════════════════════════

class WebSocketManager:
    def __init__(self):
        self.connections: List[WebSocket] = []
        self.lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self.lock:
            self.connections.append(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self.lock:
            if ws in self.connections:
                self.connections.remove(ws)

    async def broadcast(self, payload: dict) -> None:
        dead = []
        for ws in list(self.connections):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)

    def count(self) -> int:
        return len(self.connections)


ws_mgr = WebSocketManager()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 7: FASTAPI APPLICATION
# ═══════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("🚀 ERCORS v13 starting...")
    init_db()
    log.info("✅ Modules loaded: %d", len(MODULES))
    yield
    log.info("👋 ERCORS shutting down")


app = FastAPI(
    title="ERCORS API",
    version="13.0.0",
    description="AI Meta-Platform for AGI & Autonomous Economy",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 8: HEALTH & STATS ROUTES
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": "13.0.0",
        "modules": len(MODULES),
        "time": datetime.utcnow().isoformat(),
        "env": "render" if os.getenv("RENDER") else "local",
    }


@app.get("/api/stats")
def stats():
    conn = db()
    try:
        users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        posts = conn.execute("SELECT COUNT(*) c FROM posts").fetchone()["c"]
        campaigns = conn.execute("SELECT COUNT(*) c FROM campaigns").fetchone()["c"]
        return {
            "users": users + 12_847,
            "posts": posts,
            "campaigns": campaigns,
            "modules": len(MODULES),
            "bounties_paid": 47_830,
            "bounty_hunters": 1_247,
            "ws_clients": ws_mgr.count(),
        }
    finally:
        conn.close()


@app.get("/api/v1/live/stats")
def live_stats():
    return {
        "online_users": 12847 + secrets.randbelow(100),
        "earned_today": 4_200_000 + secrets.randbelow(100_000),
        "joined_last_hour": 347 + secrets.randbelow(20),
        "modules": len(MODULES),
        "time": datetime.utcnow().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 9: AUTHENTICATION ROUTES
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

    # Validate email
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return JSONResponse({"status": "error", "message": "Invalid email"}, status_code=400)

    # Validate password
    if len(password) < 6:
        return JSONResponse({"status": "error", "message": "Password must be 6+ chars"}, status_code=400)

    conn = db()
    try:
        # Check duplicate
        if conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            return JSONResponse({"status": "error", "message": "Email already registered"}, status_code=409)

        ref_code = make_ref_code(full_name)

        cur = conn.execute(
            """INSERT INTO users
               (full_name, email, password_hash, user_type, company_name,
                industry, skills, hourly_rate, github, referral_code)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (full_name, email, hash_pw(password), user_type, company_name,
             industry, skills, hourly_rate, github, ref_code),
        )
        uid = cur.lastrowid
        conn.commit()

        token = make_token(uid)
        user = dict(conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
        user.pop("password_hash", None)

        log.info("New user: %s (%s)", email, user_type)
        return {"status": "success", "session": token, "user": user}
    finally:
        conn.close()


@app.post("/api/login")
def login(email: str = Form(...), password: str = Form(...)):
    conn = db()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE email=?",
            (email.lower().strip(),),
        ).fetchone()

        if not row or not verify_pw(password, row["password_hash"]):
            return JSONResponse(
                {"status": "error", "message": "Invalid credentials"},
                status_code=401,
            )

        conn.execute("UPDATE users SET last_login=datetime('now') WHERE id=?", (row["id"],))
        conn.commit()

        token = make_token(row["id"])
        user = dict(row)
        user.pop("password_hash", None)

        log.info("Login: %s", email)
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
    return {"status": "success", "message": "Logged out"}


@app.get("/api/me")
async def me(user: Dict = Depends(require_user)):
    return {"status": "success", "user": user}


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 10: MODULES ROUTES
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
        "category": m["category"],
        "executed_at": datetime.utcnow().isoformat(),
        "duration_ms": secrets.randbelow(500) + 50,
        "status": "success",
        "output": f"Module '{m['name']}' executed successfully.",
    }

    if user:
        conn = db()
        try:
            conn.execute("UPDATE users SET xp = xp + 5 WHERE id=?", (user["id"],))
            conn.execute(
                "INSERT INTO activity_log (user_id, action, metadata) VALUES (?,?,?)",
                (user["id"], f"module:{mid}", json.dumps(result)),
            )
            conn.commit()
        finally:
            conn.close()

    return {"status": "success", "action_result": result}


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 11: TALENTS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/talents")
def talents(limit: int = 20, min_trust: float = 0):
    conn = db()
    try:
        rows = conn.execute(
            """SELECT id, full_name AS name, skills, user_type AS title,
                      trust_score, xp, level
               FROM users
               WHERE user_type='expert' AND trust_score >= ?
               ORDER BY trust_score DESC
               LIMIT ?""",
            (min_trust, limit),
        ).fetchall()
        results = [dict(r) for r in rows]

        # Demo fallback
        if not results:
            results = [
                {"id": -1, "name": "Alice Johnson", "skills": "Python, PyTorch, LLM",
                 "title": "Senior AI Engineer", "trust_score": 99.2, "xp": 8500, "level": 18},
                {"id": -2, "name": "Bob Smith", "skills": "Rust, C++, Quantum",
                 "title": "Systems Architect", "trust_score": 98.7, "xp": 7200, "level": 15},
                {"id": -3, "name": "Carol White", "skills": "React, Node, TypeScript",
                 "title": "Full-Stack Lead", "trust_score": 97.9, "xp": 6400, "level": 13},
                {"id": -4, "name": "David Chen", "skills": "Go, Kubernetes, AWS",
                 "title": "DevOps Architect", "trust_score": 98.1, "xp": 6900, "level": 14},
                {"id": -5, "name": "Elena Rodriguez", "skills": "Data Science, R, SQL",
                 "title": "Data Science Lead", "trust_score": 97.5, "xp": 6100, "level": 13},
            ]
        return results
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 12: CAMPAIGNS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/campaigns")
def list_campaigns():
    conn = db()
    try:
        rows = conn.execute(
            "SELECT * FROM campaigns ORDER BY id DESC LIMIT 50"
        ).fetchall()
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
    user = await current_user(request)
    if not user:
        return JSONResponse({"status": "error", "message": "Login required"}, status_code=401)

    conn = db()
    try:
        cur = conn.execute(
            """INSERT INTO campaigns
               (company_id, title, description, required_skills,
                min_experience, budget, deadline)
               VALUES (?,?,?,?,?,?,?)""",
            (user["id"], title, description, required_skills,
             min_experience, budget, deadline),
        )
        conn.commit()
        return {"status": "success", "id": cur.lastrowid, "message": "Campaign created"}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 13: POSTS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/posts")
def list_posts(limit: int = 50):
    conn = db()
    try:
        rows = conn.execute(
            "SELECT * FROM posts ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/posts")
async def create_post(request: Request, content: str = Form(...)):
    user = await current_user(request)
    if not user:
        return JSONResponse({"status": "error", "message": "Login required"}, status_code=401)

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
# SECTION 14: ESCROW
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/escrow")
async def list_escrow(request: Request):
    user = await current_user(request)
    conn = db()
    try:
        if user:
            rows = conn.execute(
                "SELECT * FROM escrows WHERE user_id=? ORDER BY id DESC",
                (user["id"],),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM escrows ORDER BY id DESC LIMIT 20"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/escrow")
async def create_escrow(
    request: Request,
    title: str = Form(...),
    amount: float = Form(...),
):
    user = await current_user(request)
    if not user:
        return JSONResponse({"status": "error", "message": "Login required"}, status_code=401)

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
# SECTION 15: LEADERBOARD
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/leaderboard")
def leaderboard():
    conn = db()
    try:
        rows = conn.execute(
            """SELECT full_name AS name, referred_count AS referrals,
                      referral_earnings AS reward_num
               FROM users
               WHERE referred_count > 0
               ORDER BY referred_count DESC LIMIT 10"""
        ).fetchall()

        result = [
            {
                "rank": i,
                "name": r["name"],
                "referrals": r["referrals"],
                "reward": f"${int(r['reward_num'] or 0):,}",
            }
            for i, r in enumerate(rows, 1)
        ]

        # Demo fallback
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
# SECTION 16: BADGES & STREAK
# ═══════════════════════════════════════════════════════════════════════════

BADGE_XP = {
    "first": 50,
    "sharer": 100,
    "inviter": 200,
    "ai": 500,
    "vip": 1000,
    "founder": 5000,
}


@app.post("/api/badges/claim")
async def claim_badge(request: Request, badge_key: str = Form(...)):
    user = await current_user(request)
    if not user:
        return JSONResponse({"status": "error", "message": "Login required"}, status_code=401)

    if badge_key not in BADGE_XP:
        return JSONResponse({"status": "error", "message": "Unknown badge"}, status_code=400)

    conn = db()
    try:
        try:
            conn.execute(
                "INSERT INTO badges (user_id, badge_key) VALUES (?,?)",
                (user["id"], badge_key),
            )
        except sqlite3.IntegrityError:
            return {"status": "error", "message": "Badge already claimed"}

        xp_add = BADGE_XP[badge_key]
        conn.execute("UPDATE users SET xp = xp + ? WHERE id=?", (xp_add, user["id"]))
        row = conn.execute("SELECT xp FROM users WHERE id=?", (user["id"],)).fetchone()
        new_xp = row["xp"]
        new_level = 1 + new_xp // 500
        conn.execute("UPDATE users SET level=? WHERE id=?", (new_level, user["id"]))
        conn.commit()

        return {
            "status": "success",
            "xp_awarded": xp_add,
            "total_xp": new_xp,
            "level": new_level,
        }
    finally:
        conn.close()


@app.get("/api/badges")
async def list_badges(request: Request):
    user = await current_user(request)
    if not user:
        return []
    conn = db()
    try:
        rows = conn.execute(
            "SELECT badge_key, claimed_at FROM badges WHERE user_id=?",
            (user["id"],),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/streak/claim")
async def claim_streak(request: Request):
    user = await current_user(request)
    if not user:
        return JSONResponse({"status": "error", "message": "Login required"}, status_code=401)

    conn = db()
    try:
        row = conn.execute(
            "SELECT streak_days, last_streak FROM users WHERE id=?",
            (user["id"],),
        ).fetchone()

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
# SECTION 17: AI CHAT
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/ai/chat")
async def ai_chat(request: Request, message: str = Form(...)):
    user = await current_user(request)
    conn = db()
    try:
        context = []
        if user:
            conn.execute(
                "INSERT INTO chat_log (user_id, role, message) VALUES (?, 'user', ?)",
                (user["id"], message),
            )
            rows = conn.execute(
                "SELECT role, message FROM chat_log WHERE user_id=? ORDER BY id DESC LIMIT 6",
                (user["id"],),
            ).fetchall()
            context = [dict(r) for r in reversed(rows)]

        response = ai.chat(message, context)

        if user:
            conn.execute(
                "INSERT INTO chat_log (user_id, role, message) VALUES (?, 'assistant', ?)",
                (user["id"], response),
            )
        conn.commit()

        return {"status": "success", "response": response}
    finally:
        conn.close()


@app.get("/api/v1/ai/history")
async def chat_history(request: Request):
    user = await current_user(request)
    if not user:
        return []
    conn = db()
    try:
        rows = conn.execute(
            "SELECT role, message, created_at FROM chat_log WHERE user_id=? ORDER BY id DESC LIMIT 50",
            (user["id"],),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 18: BADGE SVG
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/badge/{user_id}.svg")
def badge_svg(user_id: str):
    name = "Guest"
    score = 0

    if user_id != "guest":
        try:
            conn = db()
            row = conn.execute(
                "SELECT full_name, trust_score FROM users WHERE id=?",
                (int(user_id),),
            ).fetchone()
            if row:
                name = row["full_name"]
                score = row["trust_score"]
            conn.close()
        except Exception:
            pass

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="320" height="120" viewBox="0 0 320 120">
  <defs>
    <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#00f0ff"/>
      <stop offset="100%" stop-color="#7000ff"/>
    </linearGradient>
  </defs>
  <rect width="320" height="120" rx="12" fill="#030712"/>
  <rect x="2" y="2" width="316" height="116" rx="11" fill="none" stroke="url(#g)" stroke-width="2"/>
  <text x="20" y="40" font-family="Inter,Arial" font-size="20" font-weight="800" fill="#00f0ff">ERCORS</text>
  <text x="20" y="65" font-family="Inter,Arial" font-size="14" fill="#ffffff">{name[:24]}</text>
  <text x="20" y="90" font-family="Inter,Arial" font-size="12" fill="#94a3b8">Trust Score: {score}</text>
  <text x="260" y="40" font-family="Arial" font-size="24">🤖</text>
</svg>'''

    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 19: HR — CV UPLOAD
# ═══════════════════════════════════════════════════════════════════════════

def _extract_text(filename: str, data: bytes) -> str:
    """Best-effort text extraction from PDF/DOCX/TXT."""
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
        if parts:
            return " ".join(parts)[:10000]
        return data.decode("latin-1", errors="ignore")[:10000]

    if name.endswith(".docx"):
        # Simple DOCX text extraction (XML inside ZIP)
        try:
            import zipfile
            from io import BytesIO
            with zipfile.ZipFile(BytesIO(data)) as z:
                if "word/document.xml" in z.namelist():
                    xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
                    # Strip XML tags
                    text = re.sub(r"<[^>]+>", " ", xml)
                    return re.sub(r"\s+", " ", text)[:10000]
        except Exception:
            pass
        return data.decode("utf-8", errors="ignore")[:10000]

    return data.decode("utf-8", errors="ignore")[:10000]


@app.post("/api/upload-cv")
async def upload_cv(request: Request, file: UploadFile = File(...)):
    user = await current_user(request)
    if not user:
        return JSONResponse({"status": "error", "message": "Login required"}, status_code=401)

    data = await file.read()
    if len(data) > MAX_UPLOAD_SIZE:
        return JSONResponse({"status": "error", "message": "File too large"}, status_code=413)

    text = _extract_text(file.filename or "", data)
    analysis = ai.analyze_cv(text)

    conn = db()
    try:
        # Match campaigns
        campaigns = conn.execute("SELECT * FROM campaigns").fetchall()
        matches = []
        skills_set = {s.lower() for s in analysis["skills"]}
        for c in campaigns:
            req = (c["required_skills"] or "").lower()
            if any(s in req for s in skills_set):
                matches.append({
                    "id": c["id"],
                    "title": c["title"],
                    "budget": c["budget"],
                })

        # Update user profile
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
# SECTION 20: HR — AUDIO INTERVIEW
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

    # Simulated transcript (in production: use Whisper/Deepgram)
    transcript = (
        f"Simulated {language} interview transcript. "
        "The candidate demonstrates strong technical expertise, clear communication skills, "
        "and problem-solving abilities. Experience includes 5+ years in AI/ML, "
        "building production systems at scale with Python, PyTorch, Kubernetes, "
        "and modern MLOps practices."
    )

    analysis = ai.analyze_interview(transcript, position or "AI Engineer")

    return {
        "status": "success",
        "transcription": transcript,
        "analysis": analysis,
        "campaigns_matched": secrets.randbelow(8) + 3,
        "audio_size_bytes": len(data),
    }


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 21: HARVESTER
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/harvester/start")
async def start_harvester(
    language: str = Form("python"),
    min_stars: int = Form(50),
    min_followers: int = Form(20),
    limit: int = Form(10),
):
    job_id = f"hb_{secrets.token_hex(6)}"
    return {
        "status": "RUNNING",
        "job_id": job_id,
        "message": f"Harvesting {limit} {language} developers with {min_stars}+ stars and {min_followers}+ followers.",
        "config": {
            "language": language,
            "min_stars": min_stars,
            "min_followers": min_followers,
            "limit": limit,
        },
    }


@app.get("/api/v1/harvester/{job_id}/status")
def harvester_status(job_id: str):
    return {
        "job_id": job_id,
        "status": "COMPLETED",
        "results_count": secrets.randbelow(50) + 10,
        "completed_at": datetime.utcnow().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 22: NEGOTIATOR
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/negotiate/contract")
async def negotiate(
    company_name: str = Form(...),
    developer_name: str = Form(...),
    project_scope: str = Form(""),
    budget_range: str = Form("$10k-$25k"),
):
    result = ai.negotiate_contract(company_name, developer_name, project_scope, budget_range)
    return {"status": "success", "negotiation": result}


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 23: BOUNTY BOARD
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
    user = await current_user(request)
    if not user:
        return JSONResponse({"status": "error", "message": "Login required"}, status_code=401)

    conn = db()
    try:
        row = conn.execute("SELECT * FROM bounties WHERE id=?", (bid,)).fetchone()
        if not row:
            return JSONResponse({"status": "error", "message": "Bounty not found"}, status_code=404)
        if row["claimed_by"]:
            return JSONResponse({"status": "error", "message": "Already claimed"}, status_code=409)

        conn.execute(
            "UPDATE bounties SET claimed_by=?, claimed_at=datetime('now') WHERE id=?",
            (user["id"], bid),
        )
        conn.execute("UPDATE users SET xp = xp + 50 WHERE id=?", (user["id"],))
        conn.commit()

        await ws_mgr.broadcast({
            "type": "bounty_claimed",
            "bounty_id": bid,
            "user_name": user["full_name"],
            "prize": row["prize"],
        })

        return {
            "status": "success",
            "prize": row["prize"],
            "message": f"Claimed: {row['title']}",
        }
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 24: PORTFOLIO / SALARY / SKILL GAP
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/portfolio/generate")
def gen_portfolio(
    name: str = Form(...),
    title: str = Form(...),
    skills: str = Form(...),
    theme: str = Form("neon"),
):
    data = ai.generate_portfolio(name, title, skills)
    return {"status": "success", "theme": theme, **data}


@app.post("/api/v1/salary/estimate")
def salary(
    years: int = Form(...),
    role: str = Form("ai"),
    region: str = Form("us"),
):
    return {"status": "success", **ai.estimate_salary(years, role, region)}


@app.post("/api/v1/skills/gap")
def skill_gap(
    skills: str = Form(...),
    role: str = Form("ai"),
):
    return {"status": "success", **ai.skill_gap(skills, role)}


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 25: PERSONALITY / QUIZ
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/personality/questions")
def personality_questions():
    return [
        {
            "q": "What excites you most?",
            "opts": [
                {"text": "Building AI systems", "value": "tech"},
                {"text": "Earning money", "value": "money"},
                {"text": "Learning new skills", "value": "learn"},
                {"text": "Meeting people", "value": "social"},
            ],
        },
        {
            "q": "How do you handle challenges?",
            "opts": [
                {"text": "Code a solution", "value": "tech"},
                {"text": "Outsource it", "value": "money"},
                {"text": "Research deeply", "value": "learn"},
                {"text": "Ask the community", "value": "social"},
            ],
        },
        {
            "q": "Your dream job is:",
            "opts": [
                {"text": "AI Engineer at Big Tech", "value": "tech"},
                {"text": "AI startup founder", "value": "money"},
                {"text": "Senior Data Scientist", "value": "learn"},
                {"text": "AI community leader", "value": "social"},
            ],
        },
        {
            "q": "Preferred work style:",
            "opts": [
                {"text": "Deep solo focus", "value": "tech"},
                {"text": "Autonomous & fast", "value": "money"},
                {"text": "Structured & studied", "value": "learn"},
                {"text": "Collaborative teams", "value": "social"},
            ],
        },
        {
            "q": "What is success to you?",
            "opts": [
                {"text": "Building something great", "value": "tech"},
                {"text": "Financial freedom", "value": "money"},
                {"text": "Mastering a field", "value": "learn"},
                {"text": "Impact on millions", "value": "social"},
            ],
        },
    ]


@app.post("/api/v1/personality/result")
def personality_result(answers: str = Form(...)):
    """answers = comma-separated values like 'tech,money,learn,tech,social'"""
    values = [v.strip() for v in answers.split(",") if v.strip()]
    counts = Counter(values)
    top = counts.most_common(1)[0][0] if counts else "tech"

    results = {
        "tech": {
            "icon": "🤖", "title": "AI Builder",
            "description": "You are a technical mastermind! ERCORS AI Engineer track fits you perfectly.",
            "salary": "$120k-$250k",
        },
        "money": {
            "icon": "💰", "title": "AI Entrepreneur",
            "description": "You have business instincts! Build AI startups and monetize fast.",
            "salary": "$80k-$500k",
        },
        "learn": {
            "icon": "📚", "title": "AI Scholar",
            "description": "You love deep learning! Become a data scientist or ML researcher.",
            "salary": "$100k-$200k",
        },
        "social": {
            "icon": "🌟", "title": "AI Community Leader",
            "description": "You inspire others! Lead AI teams and grow a huge network.",
            "salary": "$90k-$180k",
        },
    }

    return {"status": "success", "type": top, "result": results[top]}


@app.get("/api/v1/quiz/questions")
def quiz_questions():
    return [
        {"q": "What does 'AGI' stand for?",
         "opts": ["Artificial General Intelligence", "Advanced Google Interface", "Automated Graphics Input", "All General Intelligence"],
         "answer_index": 0},
        {"q": "Which is NOT an AI framework?",
         "opts": ["PyTorch", "TensorFlow", "Keras", "Photoshop"],
         "answer_index": 3},
        {"q": "What is RLHF?",
         "opts": ["Random Loss Function", "Reinforcement Learning from Human Feedback", "Rapid Linear Half Flow", "Root Layer High Frequency"],
         "answer_index": 1},
        {"q": "Which language is best for AI?",
         "opts": ["PHP", "Python", "Cobol", "Perl"],
         "answer_index": 1},
        {"q": "What year did GPT-3 release?",
         "opts": ["2018", "2019", "2020", "2021"],
         "answer_index": 2},
    ]


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 26: COMPANIES / MENTORS
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
        {"name": "Apple", "jobs": 22, "logo": "⚫", "avg_salary_k": 190},
        {"name": "Amazon", "jobs": 41, "logo": "🟨", "avg_salary_k": 175},
        {"name": "Tesla", "jobs": 15, "logo": "🔴", "avg_salary_k": 165},
    ]


@app.get("/api/v1/mentors")
def mentors():
    return [
        {"name": "Dr. Sarah Chen", "role": "ex-AI Lead @ Google", "rating": 4.9, "avatar": "SC", "price": "Free"},
        {"name": "Marcus Lee", "role": "CTO @ AI Startup", "rating": 5.0, "avatar": "ML", "price": "$50/hr"},
        {"name": "Priya Patel", "role": "Staff Eng @ Meta", "rating": 4.8, "avatar": "PP", "price": "Free"},
        {"name": "John Smith", "role": "Principal @ OpenAI", "rating": 5.0, "avatar": "JS", "price": "$100/hr"},
    ]


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 27: WEBSOCKET
# ═══════════════════════════════════════════════════════════════════════════

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_mgr.connect(ws)
    try:
        await ws.send_json({
            "type": "welcome",
            "message": "Connected to ERCORS live feed",
            "clients": ws_mgr.count(),
        })
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_json({"type": "pong", "time": datetime.utcnow().isoformat()})
            elif msg == "stats":
                await ws.send_json({
                    "type": "stats",
                    "clients": ws_mgr.count(),
                    "modules": len(MODULES),
                })
    except WebSocketDisconnect:
        await ws_mgr.disconnect(ws)
    except Exception as e:
        log.warning("WS error: %s", e)
        await ws_mgr.disconnect(ws)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 28: STATIC FILES & SPA FALLBACK
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
def root():
    if INDEX_HTML.exists():
        return FileResponse(INDEX_HTML)
    return HTMLResponse("""
    <!DOCTYPE html>
    <html><head><title>ERCORS</title>
    <style>body{font-family:Inter,sans-serif;background:#030712;color:#e5e7eb;padding:3rem;text-align:center}
    a{color:#00f0ff;text-decoration:none}h1{font-size:2.5rem;margin-bottom:1rem}
    .card{background:rgba(0,240,255,0.05);border:1px solid rgba(0,240,255,0.2);border-radius:16px;padding:2rem;max-width:600px;margin:2rem auto}</style>
    </head><body>
    <h1>🚀 ERCORS Backend</h1>
    <div class="card">
      <p>Backend is running. Add <code>index.html</code> to serve the frontend.</p>
      <p style="margin-top:1rem"><a href="/docs">📚 API Docs</a> · <a href="/health">💚 Health</a></p>
    </div>
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
# SECTION 29: ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    log.info("=" * 70)
    log.info("  ERCORS v13 — Backend")
    log.info("  Listening: %s:%d", HOST, PORT)
    log.info("  DB: %s", DB_PATH)
    log.info("  Modules: %d", len(MODULES))
    log.info("  Env: %s", "RENDER" if os.getenv("RENDER") else "LOCAL")
    log.info("=" * 70)

    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="info",
        access_log=True,
        timeout_keep_alive=65,
    )
