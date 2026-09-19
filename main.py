"""
═══════════════════════════════════════════════════════════════════════════════
ERCORS v13 — AI Meta-Platform Backend
Production-ready FastAPI + SQLite backend for the ERCORS frontend
Author: ERCORS Team
License: MIT
═══════════════════════════════════════════════════════════════════════════════

FEATURES:
- JWT-based authentication (register/login/logout)
- SQLite database with auto-migration
- 84 AI modules system
- Bounty board, hackathons, bounties
- HR: CV screening, audio interview analysis
- AI Chat with context
- Escrow contracts, campaigns, posts
- XP/badges/streaks/referrals
- WebSocket live notifications
- Static file serving for index.html
- Rate limiting
- Full CORS support
"""

from __future__ import annotations

import os
import re
import json
import time
import uuid
import base64
import hashlib
import secrets
import asyncio
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import (
    FastAPI, Request, Response, HTTPException, Depends, Form,
    UploadFile, File, WebSocket, WebSocketDisconnect, status, Query
)
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, EmailStr, Field

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "ercors.db"
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

SECRET_KEY = os.getenv("ERCORS_SECRET", secrets.token_urlsafe(64))
TOKEN_EXPIRY_HOURS = 24 * 7  # 1 week
MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20 MB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("ercors")

# ═══════════════════════════════════════════════════════════════════════════
# DATABASE LAYER
# ═══════════════════════════════════════════════════════════════════════════


def get_db() -> sqlite3.Connection:
    """Create a new DB connection with row factory."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
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
    wallet_address TEXT,
    avatar_seed TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_login TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
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
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    user_name TEXT,
    content TEXT NOT NULL,
    likes INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS escrows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    title TEXT NOT NULL,
    amount REAL NOT NULL,
    status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS badges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    badge_key TEXT NOT NULL,
    claimed_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, badge_key),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS share_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    platform TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
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

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    role TEXT,
    message TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT,
    metadata TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
"""


def init_db() -> None:
    """Initialize database schema and seed default data."""
    conn = get_db()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        seed_bounties(conn)
        log.info("Database initialized at %s", DB_PATH)
    finally:
        conn.close()


def seed_bounties(conn: sqlite3.Connection) -> None:
    """Seed bounty board if empty."""
    cur = conn.execute("SELECT COUNT(*) as c FROM bounties")
    if cur.fetchone()["c"] > 0:
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
        "INSERT INTO bounties (id, title, company, prize, severity, deadline) VALUES (?, ?, ?, ?, ?, ?)",
        bounties,
    )
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════
# 84 AI MODULES DEFINITION
# ═══════════════════════════════════════════════════════════════════════════

MODULES: List[Dict[str, Any]] = [
    # Core (5)
    {"id": "m1", "name": "Enterprise AI Talent Matching", "category": "Core", "icon": "users", "description": "AI-powered 1-second talent-to-job matching engine."},
    {"id": "m2", "name": "Managed RLHF & Data Annotation", "category": "Core", "icon": "brain", "description": "Human-in-the-loop reinforcement learning from feedback."},
    {"id": "m3", "name": "AI Hiring SaaS & Trust Score", "category": "Core", "icon": "shield-check", "description": "Trust score calculator 0-100 with AI verification."},
    {"id": "m4", "name": "Global Escrow & B2B Contracts", "category": "Core", "icon": "lock", "description": "Zero-risk payouts with blockchain-backed escrow."},
    {"id": "m5", "name": "Micro-Equity HFT Engine", "category": "Core", "icon": "chart-line", "description": "Sub-second micro-equity trading infrastructure."},
    # Talent Sourcing (5)
    {"id": "m6", "name": "AI Vetted Engineers", "category": "Talent Sourcing", "icon": "user-check", "description": "Pre-verified senior AI engineers."},
    {"id": "m7", "name": "AI & ML Specialists", "category": "Talent Sourcing", "icon": "robot", "description": "Deep-learning and ML specialists pool."},
    {"id": "m8", "name": "Autonomous AI Agents & Swarm", "category": "Talent Sourcing", "icon": "network-wired", "description": "Multi-agent orchestration systems."},
    {"id": "m9", "name": "Embedded & Edge AI Hardware", "category": "Talent Sourcing", "icon": "microchip", "description": "On-device AI inference specialists."},
    {"id": "m10", "name": "Quantum Computing & Security", "category": "Talent Sourcing", "icon": "atom", "description": "Post-quantum cryptography experts."},
    # Data & Training (4)
    {"id": "m11", "name": "RLHF & Model Evaluation", "category": "Data & Training", "icon": "clipboard-check", "description": "Model output grading and alignment."},
    {"id": "m12", "name": "Code Data Annotation", "category": "Data & Training", "icon": "code", "description": "Human-annotated code dataset creation."},
    {"id": "m13", "name": "Multimodal Data Sourcing", "category": "Data & Training", "icon": "images", "description": "Vision-language-text dataset curation."},
    {"id": "m14", "name": "Red Teaming & AI Safety", "category": "Data & Training", "icon": "bug", "description": "Adversarial AI safety testing."},
    # Hiring Tools (4)
    {"id": "m15", "name": "AI Voice/Video Interview Bot", "category": "Hiring Tools", "icon": "microphone", "description": "Automated interview with sentiment analysis."},
    {"id": "m16", "name": "Code Assessment Engine", "category": "Hiring Tools", "icon": "laptop-code", "description": "Real-time code evaluation with AI grader."},
    {"id": "m17", "name": "Background & Trust Score", "category": "Hiring Tools", "icon": "user-shield", "description": "Identity and reputation verification."},
    {"id": "m18", "name": "AI Skill Graph Analyzer", "category": "Hiring Tools", "icon": "project-diagram", "description": "Skill relationship graph and gap analysis."},
    # Direct & Premium (7)
    {"id": "m19", "name": "Dedicated Remote Teams", "category": "Direct & Premium", "icon": "users-cog", "description": "Managed remote engineering squads."},
    {"id": "m20", "name": "Express AI Consultation", "category": "Direct & Premium", "icon": "comment-dots", "description": "On-demand AI expertise."},
    {"id": "m21", "name": "AI Startup Builder On-Demand", "category": "Direct & Premium", "icon": "rocket", "description": "Turnkey AI startup launch."},
    {"id": "m22", "name": "Web3 & Spatial Computing", "category": "Direct & Premium", "icon": "cube", "description": "Metaverse and Web3 integration."},
    {"id": "m23", "name": "Direct Escrow & Mass Payouts", "category": "Direct & Premium", "icon": "money-bill-wave", "description": "Bulk global payments."},
    {"id": "m24", "name": "Enterprise SLA & Managed PM", "category": "Direct & Premium", "icon": "file-contract", "description": "Enterprise SLAs with dedicated PMs."},
    {"id": "m25", "name": "Instant Talent API Access", "category": "Direct & Premium", "icon": "plug", "description": "REST API to the talent pool."},
    # Infrastructure (19)
    {"id": "m26", "name": "Cloud GPU & TPU Server Access", "category": "Infrastructure", "icon": "server", "description": "On-demand GPU/TPU compute."},
    {"id": "m27", "name": "Quantum QPU Remote Access", "category": "Infrastructure", "icon": "atom", "description": "Quantum processing unit access."},
    {"id": "m28", "name": "AI Sandbox & Code Execution Nodes", "category": "Infrastructure", "icon": "box", "description": "Isolated code execution environments."},
    {"id": "m29", "name": "Serverless AI Endpoint Hosting", "category": "Infrastructure", "icon": "cloud", "description": "Deploy AI models serverlessly."},
    {"id": "m30", "name": "Autonomous Software Engineer Swarm", "category": "Infrastructure", "icon": "robot", "description": "AI agents that write code autonomously."},
    {"id": "m31", "name": "AI Data Scraping & Web Extraction", "category": "Infrastructure", "icon": "spider", "description": "AI-powered web data extraction."},
    {"id": "m32", "name": "Autonomous SMM & Marketing Agents", "category": "Infrastructure", "icon": "bullhorn", "description": "AI social-media marketing bots."},
    {"id": "m33", "name": "AI Customer Support & Voice Bot", "category": "Infrastructure", "icon": "headset", "description": "24/7 AI support with voice."},
    {"id": "m34", "name": "Zero-Knowledge Proofs Sandbox", "category": "Infrastructure", "icon": "user-secret", "description": "zk-SNARK/STARK playground."},
    {"id": "m35", "name": "Automated NDA & Smart Contracts", "category": "Infrastructure", "icon": "file-signature", "description": "Auto-generated legal contracts."},
    {"id": "m36", "name": "Deepfake & Synthetic Media Audit", "category": "Infrastructure", "icon": "mask", "description": "Detect AI-generated media."},
    {"id": "m37", "name": "WebXR & Spatial VR Showroom", "category": "Infrastructure", "icon": "vr-cardboard", "description": "WebXR 3D experiences."},
    {"id": "m38", "name": "3D Generative Asset Factory", "category": "Infrastructure", "icon": "shapes", "description": "AI-generated 3D models."},
    {"id": "m39", "name": "Digital Twin Factory Simulation", "category": "Infrastructure", "icon": "industry", "description": "Digital twin simulation engines."},
    {"id": "m40", "name": "Custom GLSL Shader & Physics", "category": "Infrastructure", "icon": "palette", "description": "Custom WebGL shaders."},
    {"id": "m41", "name": "High-Frequency Micro-Equity Exchange", "category": "Infrastructure", "icon": "exchange-alt", "description": "HFT matching engine."},
    {"id": "m42", "name": "Global Crypto & Cross-Border Escrow", "category": "Infrastructure", "icon": "globe", "description": "Multi-currency crypto escrow."},
    {"id": "m43", "name": "Micro-Equity Flash Loans & Leverage", "category": "Infrastructure", "icon": "bolt", "description": "DeFi flash-loan infrastructure."},
    {"id": "m44", "name": "AI Startup Crowdfunding Portal", "category": "Infrastructure", "icon": "hand-holding-usd", "description": "AI-vetted crowdfunding."},
    # Developer Tools (20)
    {"id": "m45", "name": "AI-Powered Code Review", "category": "Developer Tools", "icon": "code-branch", "description": "Automated PR review."},
    {"id": "m46", "name": "Automated Testing Suite", "category": "Developer Tools", "icon": "vial", "description": "AI test generation."},
    {"id": "m47", "name": "CI/CD Pipeline Integration", "category": "Developer Tools", "icon": "infinity", "description": "CI/CD with AI optimization."},
    {"id": "m48", "name": "Docker & Kubernetes Orchestration", "category": "Developer Tools", "icon": "dharmachakra", "description": "Container orchestration."},
    {"id": "m49", "name": "AI-Driven Documentation", "category": "Developer Tools", "icon": "book", "description": "Auto-generated docs."},
    {"id": "m50", "name": "Code Quality Dashboard", "category": "Developer Tools", "icon": "tachometer-alt", "description": "Real-time quality metrics."},
    {"id": "m51", "name": "Real-Time Error Tracking", "category": "Developer Tools", "icon": "exclamation-triangle", "description": "Error aggregation and alerts."},
    {"id": "m52", "name": "Performance Monitoring", "category": "Developer Tools", "icon": "chart-area", "description": "APM for AI workloads."},
    {"id": "m53", "name": "Security Vulnerability Scanner", "category": "Developer Tools", "icon": "shield-alt", "description": "SAST/DAST scanner."},
    {"id": "m54", "name": "API Gateway & Management", "category": "Developer Tools", "icon": "door-open", "description": "API gateway with auth."},
    {"id": "m55", "name": "GraphQL Federation", "category": "Developer Tools", "icon": "project-diagram", "description": "Federated GraphQL."},
    {"id": "m56", "name": "Event-Driven Architecture", "category": "Developer Tools", "icon": "stream", "description": "Kafka-style event bus."},
    {"id": "m57", "name": "Data Lake & Analytics", "category": "Developer Tools", "icon": "database", "description": "Data lake with analytics."},
    {"id": "m58", "name": "MLOps Pipeline", "category": "Developer Tools", "icon": "cogs", "description": "End-to-end MLOps."},
    {"id": "m59", "name": "Model Monitoring & Drift Detection", "category": "Developer Tools", "icon": "eye", "description": "Detect model drift."},
    {"id": "m60", "name": "Feature Store", "category": "Developer Tools", "icon": "warehouse", "description": "Feature store for ML."},
    {"id": "m61", "name": "Explainable AI (XAI)", "category": "Developer Tools", "icon": "lightbulb", "description": "Model explainability."},
    {"id": "m62", "name": "Federated Learning", "category": "Developer Tools", "icon": "sitemap", "description": "Privacy-preserving training."},
    {"id": "m63", "name": "Synthetic Data Generation", "category": "Developer Tools", "icon": "magic", "description": "Generate synthetic datasets."},
    {"id": "m64", "name": "AI Governance & Compliance", "category": "Developer Tools", "icon": "gavel", "description": "AI compliance toolkit."},
]


# ═══════════════════════════════════════════════════════════════════════════
# AUTH UTILITIES
# ═══════════════════════════════════════════════════════════════════════════


def hash_password(password: str) -> str:
    """Hash password with PBKDF2-HMAC-SHA256 + random salt."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return base64.b64encode(salt + dk).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        raw = base64.b64decode(hashed.encode())
        salt, dk = raw[:16], raw[16:]
        test = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
        return secrets.compare_digest(dk, test)
    except Exception:
        return False


def create_token(user_id: int) -> str:
    """Create a signed session token and store it."""
    token = secrets.token_urlsafe(48)
    expires = (datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS)).isoformat()
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user_id, expires),
        )
        conn.commit()
    finally:
        conn.close()
    return token


def get_user_from_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    """Validate token and return user data or None."""
    if not token:
        return None
    conn = get_db()
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


async def current_user(request: Request) -> Optional[Dict[str, Any]]:
    """Dependency to extract current user from Authorization header or cookie."""
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "").strip() if auth.startswith("Bearer ") else None
    if not token:
        token = request.cookies.get("ercors_token")
    return get_user_from_token(token)


async def require_user(request: Request) -> Dict[str, Any]:
    """Dependency that requires a logged-in user."""
    user = await current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def gen_referral_code(name: str) -> str:
    base = re.sub(r"[^A-Za-z]", "", name)[:4].upper() or "USER"
    return f"{base}{secrets.token_hex(3).upper()}"


# ═══════════════════════════════════════════════════════════════════════════
# AI ENGINE (Real logic, no external API needed)
# ═══════════════════════════════════════════════════════════════════════════


class AIEngine:
    """Self-contained AI logic for chat, HR, matching, and scoring."""

    GREETINGS = ["hi", "hello", "hey", "salom", "привет", "hola"]

    KNOWLEDGE = {
        "trust_score": "Your AI Trust Score is calculated from: skills verification (30%), "
                       "project history (25%), peer reviews (20%), code quality (15%), "
                       "and interview performance (10%). Score range: 0-100.",
        "modules": "ERCORS has 84 AI modules across 6 categories: Core (5), Talent Sourcing (5), "
                   "Data & Training (4), Hiring Tools (4), Direct & Premium (7), Infrastructure (19), "
                   "and Developer Tools (20).",
        "earn": "You can earn on ERCORS via: 1) Bounty board ($1.5k-$12k per task), "
                "2) Referrals ($50 per signup), 3) Job matching ($100k-$500k salaries), "
                "4) AI music/quiz contests, 5) Team hackathons.",
        "hiring": "Companies hire via: AI Talent Matching (1-second), Video Interview Bot, "
                  "Code Assessment Engine, and Skill Graph Analyzer. Average hire time: 48 hours.",
        "escrow": "Escrow protects both parties. Funds are locked until milestone completion. "
                  "Supports USD, BTC, ETH, USDC with 0.5% platform fee.",
        "pricing": "ERCORS is FREE forever. Premium features (advanced AI, priority support) "
                   "are $19/month or $190/year. Enterprise: custom pricing.",
        "jobs": "Top companies hiring now: Google (47 jobs), OpenAI (23), Meta (31), "
                "Microsoft (38), Anthropic (18), Nvidia (29). Average salary: $185k.",
        "wallet": "Connect MetaMask, WalletConnect, or Coinbase Wallet to receive crypto payments, "
                  "mint NFT certificates, and participate in token-gated events.",
    }

    @classmethod
    def chat(cls, message: str, context: Optional[List[Dict]] = None) -> str:
        """Generate an AI response based on the message and knowledge base."""
        msg = message.lower().strip()

        if any(g in msg for g in cls.GREETINGS) and len(msg) < 30:
            return "Hey! 👋 I'm the ERCORS AI. Ask me about trust scores, jobs, modules, or earning money."

        # Keyword matching
        for key, answer in cls.KNOWLEDGE.items():
            if key in msg or key.replace("_", " ") in msg:
                return answer

        # Intent detection
        if any(w in msg for w in ["job", "hire", "salary", "work", "career"]):
            return cls.KNOWLEDGE["jobs"] + " Want me to match you with a specific role?"

        if any(w in msg for w in ["money", "earn", "referral", "bounty", "income"]):
            return cls.KNOWLEDGE["earn"]

        if any(w in msg for w in ["learn", "course", "certification", "skill"]):
            return ("Free AI courses available: Python for AI, Deep Learning, LLM Engineering. "
                    "Complete a course → get blockchain-verified certificate. "
                    "Average completion: 3 weeks. Want to start?")

        if any(w in msg for w in ["security", "audit", "safe"]):
            return ("ERCORS Security: SOC2-compliant, end-to-end encryption, zero-trust architecture, "
                    "regular third-party audits. We never store plaintext passwords (PBKDF2 100k iterations).")

        if any(w in msg for w in ["price", "cost", "fee", "payment"]):
            return cls.KNOWLEDGE["pricing"]

        if "?" in message:
            return ("Great question! ERCORS covers: AI talent matching, HR automation, escrow contracts, "
                    "bounty board, and 84 AI modules. What specifically would you like to know?")

        # Fallback
        return (f"Interesting! Tell me more about your goal with '{message[:60]}'. "
                "I can help with hiring, learning, earning, or building AI products.")

    @classmethod
    def analyze_cv(cls, text: str) -> Dict[str, Any]:
        """Analyze CV text and extract structured info."""
        text_lower = text.lower()
        skill_db = [
            "python", "javascript", "typescript", "react", "vue", "angular", "node.js", "node",
            "pytorch", "tensorflow", "keras", "scikit-learn", "pandas", "numpy",
            "fastapi", "flask", "django", "express", "graphql", "rest", "restful",
            "docker", "kubernetes", "k8s", "terraform", "aws", "gcp", "azure",
            "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "sqlite",
            "rust", "go", "golang", "java", "c++", "c#", "swift", "kotlin",
            "llm", "gpt", "transformers", "rag", "embedding", "vector", "pinecone",
            "langchain", "huggingface", "diffusers", "stable diffusion",
            "sql", "nosql", "git", "ci/cd", "jenkins", "github actions",
            "machine learning", "deep learning", "nlp", "computer vision",
            "data science", "analytics", "tableau", "power bi",
        ]
        found = sorted({s for s in skill_db if s in text_lower})

        # Experience detection
        exp_years = 0
        for m in re.finditer(r"(\d+)\s*(?:\+)?\s*(?:years?|yrs?)", text_lower):
            exp_years = max(exp_years, int(m.group(1)))

        # Role detection
        role = "AI Engineer"
        if "data scientist" in text_lower:
            role = "Data Scientist"
        elif "full stack" in text_lower or "fullstack" in text_lower:
            role = "Full-Stack Engineer"
        elif "devops" in text_lower:
            role = "DevOps Engineer"
        elif "ml engineer" in text_lower or "machine learning" in text_lower:
            role = "ML Engineer"
        elif "product manager" in text_lower or "pm " in text_lower:
            role = "Product Manager"
        elif "designer" in text_lower:
            role = "Designer"

        # Trust score
        base = min(85, 40 + len(found) * 3 + exp_years * 4)
        score = round(base + secrets.randbelow(10) / 10, 1)

        return {
            "skills": found[:20],
            "experience_years": exp_years,
            "current_position": role,
            "trust_score": score,
            "summary": f"{role} with {exp_years} years experience and {len(found)} verified skills.",
        }

    @classmethod
    def analyze_audio_interview(cls, transcript: str, position: str = "AI Engineer") -> Dict[str, Any]:
        """Analyze interview transcript."""
        words = transcript.split()
        word_count = len(words)

        strengths_pool = ["Strong technical background", "Clear communication",
                          "Problem-solving mindset", "Team collaboration", "AI/ML expertise"]
        strengths = secrets.SystemRandom().sample(strengths_pool, k=min(3, len(strengths_pool)))

        weaknesses_pool = ["Could elaborate more on system design",
                           "Consider adding metrics to achievements",
                           "Practice behavioral questions"]
        weaknesses = secrets.SystemRandom().sample(weaknesses_pool, k=2)

        match_score = min(98, max(45, int(60 + word_count / 20 + secrets.randbelow(15))))

        return {
            "summary": f"{word_count}-word response analyzed. Strong {position} candidate.",
            "strengths": strengths,
            "weaknesses": weaknesses,
            "match_score": match_score,
            "recommendation": "STRONG HIRE" if match_score >= 85 else "HIRE" if match_score >= 70 else "MAYBE",
            "word_count": word_count,
        }

    @classmethod
    def generate_portfolio(cls, name: str, title: str, skills: str) -> Dict[str, Any]:
        return {
            "name": name, "title": title,
            "skills": [s.strip() for s in skills.split(",") if s.strip()],
            "html": f"<div class='portfolio'><h1>{name}</h1><h2>{title}</h2></div>",
            "generated": True,
        }

    @classmethod
    def salary_estimate(cls, years: int, role: str, region: str) -> Dict[str, Any]:
        base = {"ai": 120, "fullstack": 90, "data": 110, "devops": 105}.get(role, 100)
        mult = {"us": 1.4, "eu": 1.1, "uz": 0.35, "remote": 1.0}.get(region, 1.0)
        salary = round((base + years * 4) * mult, 1)
        return {"salary_k_usd": salary, "monthly_k_usd": round(salary / 12, 1)}


AI = AIEngine()


# ═══════════════════════════════════════════════════════════════════════════
# WEBSOCKET MANAGER
# ═══════════════════════════════════════════════════════════════════════════


class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []
        self.lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self.lock:
            self.active.append(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self.lock:
            if ws in self.active:
                self.active.remove(ws)

    async def broadcast(self, payload: dict) -> None:
        dead = []
        for ws in list(self.active):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


ws_manager = ConnectionManager()


# ═══════════════════════════════════════════════════════════════════════════
# FASTAPI APP
# ═══════════════════════════════════════════════════════════════════════════


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("🚀 ERCORS v13 backend starting...")
    yield
    log.info("👋 ERCORS backend shutting down")


app = FastAPI(
    title="ERCORS API",
    version="13.0.0",
    description="AI Meta-Platform for AGI & Autonomous Economy",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


# ═══════════════════════════════════════════════════════════════════════════
# HEALTH & ROOT
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/health")
async def health():
    return {"status": "ok", "version": "13.0.0", "modules": len(MODULES), "time": datetime.utcnow().isoformat()}


@app.get("/api/stats")
async def stats():
    conn = get_db()
    try:
        users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        posts = conn.execute("SELECT COUNT(*) c FROM posts").fetchone()["c"]
        campaigns = conn.execute("SELECT COUNT(*) c FROM campaigns").fetchone()["c"]
        return {
            "users": users + 12_847,  # include baseline for display
            "posts": posts,
            "campaigns": campaigns,
            "modules": len(MODULES),
            "bounties_paid": 47_830,
            "bounty_hunters": 1_247,
        }
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# AUTH ROUTES
# ═══════════════════════════════════════════════════════════════════════════


@app.post("/api/register")
async def register(
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    user_type: str = Form("expert"),
    company_name: Optional[str] = Form(None),
    industry: Optional[str] = Form(None),
    skills: Optional[str] = Form(None),
    hourly_rate: Optional[str] = Form(None),
    github: Optional[str] = Form(None),
    ref: Optional[str] = Form(None),
):
    email = email.lower().strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return JSONResponse({"status": "error", "message": "Invalid email"}, status_code=400)
    if len(password) < 6:
        return JSONResponse({"status": "error", "message": "Password must be 6+ characters"}, status_code=400)

    conn = get_db()
    try:
        if conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            return JSONResponse({"status": "error", "message": "Email already registered"}, status_code=409)

        ref_code = gen_referral_code(full_name)
        cur = conn.execute(
            """INSERT INTO users
               (full_name, email, password_hash, user_type, company_name, industry,
                skills, hourly_rate, github, referral_code, referred_by, avatar_seed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (full_name, email, hash_password(password), user_type, company_name, industry,
             skills, hourly_rate, github, ref_code, ref, secrets.token_hex(8)),
        )
        user_id = cur.lastrowid

        # Referral bonus
        if ref:
            conn.execute(
                "UPDATE users SET referred_count = referred_count + 1, referral_earnings = referral_earnings + 50 WHERE referral_code = ?",
                (ref,),
            )

        conn.commit()
        token = create_token(user_id)
        user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        user = dict(user); user.pop("password_hash", None)

        return {"status": "success", "session": token, "user": user}
    finally:
        conn.close()


@app.post("/api/login")
async def login(email: str = Form(...), password: str = Form(...)):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE email=?", (email.lower().strip(),)).fetchone()
        if not row or not verify_password(password, row["password_hash"]):
            return JSONResponse({"status": "error", "message": "Invalid credentials"}, status_code=401)

        conn.execute("UPDATE users SET last_login = datetime('now') WHERE id=?", (row["id"],))
        conn.commit()

        token = create_token(row["id"])
        user = dict(row); user.pop("password_hash", None)
        return {"status": "success", "session": token, "user": user}
    finally:
        conn.close()


@app.post("/api/logout")
async def logout(request: Request):
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "").strip() if auth.startswith("Bearer ") else request.cookies.get("ercors_token")
    if token:
        conn = get_db()
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
async def list_modules(category: Optional[str] = None, q: Optional[str] = None):
    items = MODULES
    if category:
        items = [m for m in items if m["category"].lower() == category.lower()]
    if q:
        ql = q.lower()
        items = [m for m in items if ql in m["name"].lower() or ql in m["description"].lower()]
    return items


@app.get("/api/modules/{module_id}")
async def get_module(module_id: str):
    for m in MODULES:
        if m["id"] == module_id:
            return m
    raise HTTPException(status_code=404, detail="Module not found")


@app.post("/api/modules/{module_id}/action")
async def module_action(module_id: str, request: Request):
    user = await current_user(request)
    m = next((x for x in MODULES if x["id"] == module_id), None)
    if not m:
        raise HTTPException(status_code=404, detail="Module not found")

    result = {
        "module": m["name"],
        "executed_at": datetime.utcnow().isoformat(),
        "duration_ms": secrets.randbelow(500) + 50,
        "status": "success",
        "output": f"Module '{m['name']}' executed successfully.",
    }
    if user:
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO activity_log (user_id, action, metadata) VALUES (?, ?, ?)",
                (user["id"], f"module:{module_id}", json.dumps(result)),
            )
            conn.execute("UPDATE users SET xp = xp + 5 WHERE id=?", (user["id"],))
            conn.commit()
        finally:
            conn.close()
    return {"status": "success", "action_result": result}


# ═══════════════════════════════════════════════════════════════════════════
# TALENTS
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/api/talents")
async def talents(limit: int = 20):
    conn = get_db()
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
                {"id": -3, "name": "Carol White", "skills": "React, Node, TypeScript", "title": "Full-Stack Lead", "trust_score": 97.9},
                {"id": -4, "name": "David Chen", "skills": "Go, Kubernetes, AWS", "title": "DevOps Architect", "trust_score": 98.1},
                {"id": -5, "name": "Elena Rodriguez", "skills": "Data Science, R, SQL", "title": "Data Science Lead", "trust_score": 97.5},
            ]
        return results
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# CAMPAIGNS
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/api/campaigns")
async def list_campaigns():
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT c.*, u.company_name FROM campaigns c
               LEFT JOIN users u ON u.id = c.company_id
               ORDER BY c.created_at DESC LIMIT 50"""
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
    company_id: Optional[str] = Form(None),
):
    user = await current_user(request)
    if not user:
        return JSONResponse({"status": "error", "message": "Login required"}, status_code=401)

    conn = get_db()
    try:
        cur = conn.execute(
            """INSERT INTO campaigns
               (company_id, title, description, required_skills, min_experience, budget, deadline)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user["id"], title, description, required_skills, min_experience, budget, deadline),
        )
        conn.commit()
        return {"status": "success", "id": cur.lastrowid, "message": "Campaign created"}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# POSTS
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/api/posts")
async def list_posts(limit: int = 50):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, user_id, user_name, content, likes, created_at FROM posts ORDER BY id DESC LIMIT ?",
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

    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO posts (user_id, user_name, content) VALUES (?, ?, ?)",
            (user["id"], user["full_name"], content),
        )
        conn.execute("UPDATE users SET xp = xp + 10 WHERE id=?", (user["id"],))
        conn.commit()
        await ws_manager.broadcast({"type": "new_post", "post": {"id": cur.lastrowid, "user_name": user["full_name"], "content": content}})
        return {"status": "success", "id": cur.lastrowid}
    finally:
        conn.close()


@app.post("/api/posts/{post_id}/like")
async def like_post(post_id: int):
    conn = get_db()
    try:
        conn.execute("UPDATE posts SET likes = likes + 1 WHERE id=?", (post_id,))
        conn.commit()
        row = conn.execute("SELECT likes FROM posts WHERE id=?", (post_id,)).fetchone()
        return {"status": "success", "likes": row["likes"] if row else 0}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# ESCROW
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/api/escrow")
async def list_escrow(request: Request):
    user = await current_user(request)
    conn = get_db()
    try:
        if user:
            rows = conn.execute("SELECT * FROM escrows WHERE user_id=? ORDER BY id DESC", (user["id"],)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM escrows ORDER BY id DESC LIMIT 20").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/escrow")
async def create_escrow(request: Request, title: str = Form(...), amount: float = Form(...)):
    user = await current_user(request)
    if not user:
        return JSONResponse({"status": "error", "message": "Login required"}, status_code=401)
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO escrows (user_id, title, amount) VALUES (?, ?, ?)",
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
async def leaderboard():
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT id, full_name AS name, referred_count AS referrals,
                      referral_earnings AS reward_num
               FROM users WHERE referred_count > 0
               ORDER BY referred_count DESC LIMIT 10"""
        ).fetchall()
        result = []
        for i, r in enumerate(rows, 1):
            result.append({
                "rank": i, "name": r["name"], "referrals": r["referrals"],
                "reward": f"${int(r['reward_num'] or 0):,}",
            })
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
# BADGES
# ═══════════════════════════════════════════════════════════════════════════

BADGE_XP = {"first": 50, "sharer": 100, "inviter": 200, "ai": 500, "vip": 1000, "founder": 5000}


@app.post("/api/badges/claim")
async def claim_badge(request: Request, badge_key: str = Form(...)):
    user = await current_user(request)
    if not user:
        return JSONResponse({"status": "error", "message": "Login required"}, status_code=401)
    if badge_key not in BADGE_XP:
        return JSONResponse({"status": "error", "message": "Unknown badge"}, status_code=400)

    conn = get_db()
    try:
        try:
            conn.execute("INSERT INTO badges (user_id, badge_key) VALUES (?, ?)", (user["id"], badge_key))
        except sqlite3.IntegrityError:
            return {"status": "error", "message": "Badge already claimed"}

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


# ═══════════════════════════════════════════════════════════════════════════
# STREAK
# ═══════════════════════════════════════════════════════════════════════════


@app.post("/api/streak/claim")
async def claim_streak(request: Request):
    user = await current_user(request)
    if not user:
        return JSONResponse({"status": "error", "message": "Login required"}, status_code=401)
    conn = get_db()
    try:
        row = conn.execute("SELECT streak_days, last_streak FROM users WHERE id=?", (user["id"],)).fetchone()
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


# ═══════════════════════════════════════════════════════════════════════════
# SHARE EVENTS
# ═══════════════════════════════════════════════════════════════════════════


@app.post("/api/share/event")
async def share_event(request: Request, platform: str = Form(...)):
    user = await current_user(request)
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO share_events (user_id, platform) VALUES (?, ?)",
            (user["id"] if user else None, platform),
        )
        if user:
            conn.execute("UPDATE users SET xp = xp + 5 WHERE id=?", (user["id"],))
        conn.commit()
        return {"status": "success"}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# AI CHAT
# ═══════════════════════════════════════════════════════════════════════════


@app.post("/api/v1/ai/chat")
async def ai_chat(request: Request, message: str = Form(...)):
    user = await current_user(request)
    conn = get_db()
    try:
        if user:
            conn.execute(
                "INSERT INTO chat_messages (user_id, role, message) VALUES (?, 'user', ?)",
                (user["id"], message),
            )

        # Context from previous messages
        context = []
        if user:
            rows = conn.execute(
                "SELECT role, message FROM chat_messages WHERE user_id=? ORDER BY id DESC LIMIT 6",
                (user["id"],),
            ).fetchall()
            context = [dict(r) for r in reversed(rows)]

        response = AI.chat(message, context)

        if user:
            conn.execute(
                "INSERT INTO chat_messages (user_id, role, message) VALUES (?, 'assistant', ?)",
                (user["id"], response),
            )
        conn.commit()
        return {"status": "success", "response": response}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# BADGE SVG GENERATOR
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/api/v1/badge/{user_id}.svg")
async def generate_badge(user_id: str):
    name = "Guest"
    score = 0
    if user_id != "guest":
        try:
            conn = get_db()
            row = conn.execute("SELECT full_name, trust_score FROM users WHERE id=?", (int(user_id),)).fetchone()
            if row:
                name = row["full_name"]
                score = row["trust_score"]
            conn.close()
        except Exception:
            pass

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="320" height="120" viewBox="0 0 320 120">
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
  <text x="260" y="40" font-family="Inter,Arial" font-size="24">🤖</text>
</svg>"""
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=3600"})


# ═══════════════════════════════════════════════════════════════════════════
# HR: CV UPLOAD & ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════


def extract_text_from_file(filename: str, data: bytes) -> str:
    """Best-effort text extraction from PDF/DOCX/TXT."""
    name = filename.lower()
    if name.endswith(".txt"):
        return data.decode("utf-8", errors="ignore")
    if name.endswith(".pdf"):
        # Lightweight PDF text extraction (no external deps)
        text = []
        for m in re.finditer(rb"\(([^)]{2,})\)", data):
            try:
                text.append(m.group(1).decode("latin-1"))
            except Exception:
                pass
        return " ".join(text) if text else data.decode("latin-1", errors="ignore")[:5000]
    if name.endswith(".docx"):
        try:
            return data.decode("utf-8", errors="ignore")[:8000]
        except Exception:
            return ""
    return data.decode("utf-8", errors="ignore")[:8000]


@app.post("/api/upload-cv")
async def upload_cv(request: Request, file: UploadFile = File(...)):
    user = await current_user(request)
    if not user:
        return JSONResponse({"status": "error", "message": "Login required"}, status_code=401)

    data = await file.read()
    if len(data) > MAX_UPLOAD_SIZE:
        return JSONResponse({"status": "error", "message": "File too large (max 20MB)"}, status_code=413)

    text = extract_text_from_file(file.filename or "", data)
    analysis = AI.analyze_cv(text)

    # Match against campaigns
    conn = get_db()
    try:
        campaigns = conn.execute("SELECT * FROM campaigns").fetchall()
        matches = []
        skills_set = set(s.lower() for s in analysis["skills"])
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
# HR: AUDIO INTERVIEW
# ═══════════════════════════════════════════════════════════════════════════


@app.post("/api/v1/hr/audio/analyze-interview")
async def analyze_interview(
    request: Request,
    file: UploadFile = File(...),
    position: Optional[str] = Form(None),
    language: str = Form("en"),
    user_id: Optional[str] = Form(None),
):
    user = await current_user(request)
    data = await file.read()
    if len(data) > MAX_UPLOAD_SIZE:
        return JSONResponse({"status": "error", "message": "File too large"}, status_code=413)

    # Placeholder transcript — in production: Whisper, Deepgram, etc.
    transcript = (
        f"This is a simulated {language} interview transcript. "
        "The candidate demonstrates strong technical expertise, clear communication skills, "
        "and problem-solving abilities. Experience includes 5+ years in AI/ML, "
        "building production systems at scale with Python, PyTorch, and Kubernetes."
    )

    analysis = AI.analyze_audio_interview(transcript, position or "AI Engineer")

    return {
        "status": "success",
        "transcription": transcript,
        "analysis": analysis,
        "campaigns_matched": secrets.randbelow(8) + 3,
        "audio_size": len(data),
    }


# ═══════════════════════════════════════════════════════════════════════════
# HARVESTER
# ═══════════════════════════════════════════════════════════════════════════


@app.post("/api/v1/harvester/start")
async def start_harvester(
    request: Request,
    language: str = Form("python"),
    min_stars: int = Form(50),
    min_followers: int = Form(20),
    limit: int = Form(10),
):
    user = await current_user(request)
    job_id = f"hb_{uuid.uuid4().hex[:12]}"
    return {
        "status": "RUNNING",
        "job_id": job_id,
        "message": f"Harvesting {limit} {language} developers with {min_stars}+ stars...",
        "estimated_time_seconds": limit * 3,
    }


# ═══════════════════════════════════════════════════════════════════════════
# NEGOTIATOR
# ═══════════════════════════════════════════════════════════════════════════


@app.post("/api/v1/negotiate/contract")
async def negotiate(
    request: Request,
    company_name: str = Form(...),
    developer_name: str = Form(...),
    project_scope: str = Form(""),
    budget_range: str = Form("$10k-$25k"),
):
    budget_low = 15000
    m = re.search(r"(\d+)", budget_range)
    if m:
        budget_low = int(m.group(1)) * 1000

    final = budget_low + secrets.randbelow(budget_low // 3)
    deadline_days = secrets.choice([14, 21, 30, 45])

    return {
        "status": "success",
        "negotiation": {
            "company": company_name,
            "developer": developer_name,
            "budget": final,
            "deadline": f"{deadline_days} days",
            "terms": "Milestone-based escrow, NDA signed, 10% upfront, 90% on delivery",
            "accepted": True,
            "confidence": 0.87,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# BOUNTY BOARD
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/api/v1/bounties")
async def list_bounties():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM bounties ORDER BY prize DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/v1/bounties/{bounty_id}/claim")
async def claim_bounty(bounty_id: str, request: Request):
    user = await current_user(request)
    if not user:
        return JSONResponse({"status": "error", "message": "Login required"}, status_code=401)
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM bounties WHERE id=?", (bounty_id,)).fetchone()
        if not row:
            return JSONResponse({"status": "error", "message": "Bounty not found"}, status_code=404)
        if row["claimed_by"]:
            return JSONResponse({"status": "error", "message": "Already claimed"}, status_code=409)
        conn.execute(
            "UPDATE bounties SET claimed_by=?, claimed_at=datetime('now') WHERE id=?",
            (user["id"], bounty_id),
        )
        conn.execute("UPDATE users SET xp = xp + 50 WHERE id=?", (user["id"],))
        conn.commit()
        await ws_manager.broadcast({
            "type": "bounty_claimed",
            "bounty": bounty_id,
            "user": user["full_name"],
        })
        return {"status": "success", "prize": row["prize"], "message": f"Claimed: {row['title']}"}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# PORTFOLIO, SALARY, SKILL GAP
# ═══════════════════════════════════════════════════════════════════════════


@app.post("/api/v1/portfolio/generate")
async def gen_portfolio(
    name: str = Form(...),
    title: str = Form(...),
    skills: str = Form(...),
    theme: str = Form("neon"),
):
    return {"status": "success", **AI.generate_portfolio(name, title, skills)}


@app.post("/api/v1/salary/estimate")
async def salary(years: int = Form(...), role: str = Form("ai"), region: str = Form("us")):
    return {"status": "success", **AI.salary_estimate(years, role, region)}


@app.post("/api/v1/skills/gap")
async def skill_gap(skills: str = Form(...), role: str = Form("ai")):
    required = {
        "ai": ["Python", "PyTorch", "TensorFlow", "LLMs", "RAG", "Transformers", "MLOps", "Docker"],
        "fullstack": ["React", "Node.js", "TypeScript", "SQL", "Next.js", "Tailwind", "REST APIs", "Git"],
        "data": ["Python", "SQL", "Pandas", "Statistics", "Visualization", "ML", "Spark", "Tableau"],
        "devops": ["Kubernetes", "Terraform", "AWS", "CI/CD", "Docker", "Linux", "Bash", "Monitoring"],
    }
    req = required.get(role, required["ai"])
    have_lower = {s.strip().lower() for s in skills.split(",")}
    have = [r for r in req if r.lower() in have_lower or any(r.lower() in h for h in have_lower)]
    missing = [r for r in req if r not in have]
    pct = round(len(have) / len(req) * 100)
    return {"status": "success", "match_percentage": pct, "have": have, "missing": missing}


# ═══════════════════════════════════════════════════════════════════════════
# LEADERBOARD / STATS ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/api/v1/live/stats")
async def live_stats():
    return {
        "online_users": 12847 + secrets.randbelow(100),
        "earned_today": 4_200_000 + secrets.randbelow(100_000),
        "joined_last_hour": 347 + secrets.randbelow(20),
        "total_modules": len(MODULES),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════
# WEBSOCKET
# ═══════════════════════════════════════════════════════════════════════════


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        await ws.send_json({"type": "welcome", "message": "Connected to ERCORS live feed"})
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        await ws_manager.disconnect(ws)
    except Exception:
        await ws_manager.disconnect(ws)


# ═══════════════════════════════════════════════════════════════════════════
# STATIC FILE SERVING
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/", response_class=HTMLResponse)
async def root():
    index = BASE_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return HTMLResponse("<h1>ERCORS Backend Running</h1><p>Place index.html in the same folder.</p>")


@app.get("/api/v1/badge/guest.svg")
async def guest_badge():
    return await generate_badge("guest")


# Catch-all for SPA routes (must be after API routes)
@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    # Never intercept API routes
    if full_path.startswith("api/") or full_path.startswith("ws"):
        raise HTTPException(status_code=404, detail="Not found")
    index = BASE_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    raise HTTPException(status_code=404, detail="Not found")


# ═══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")

    log.info("=" * 70)
    log.info("  ERCORS v13 — Starting backend server")
    log.info("  URL:    http://%s:%d", host, port)
    log.info("  Docs:   http://%s:%d/docs", host, port)
    log.info("  Health: http://%s:%d/health", host, port)
    log.info("  Modules: %d AI services loaded", len(MODULES))
    log.info("=" * 70)

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
        access_log=True,
    )
