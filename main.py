"""
============================================================
 ERCORS AGI – Backend (main.py) – ULTRA EDITION
 3000+ qator to'liq ishlaydigan kod
 FastAPI + SQLite + WebSocket + JWT-like tokens
============================================================
 O'rnatish:
   pip install fastapi uvicorn python-multipart websockets
 Ishga tushirish:
   python main.py
 Brauzer:
   http://localhost:8000
============================================================
"""

# ============================================================
# SECTION 1: IMPORTS
# ============================================================
from fastapi import (
    FastAPI, Request, UploadFile, File, Form, HTTPException,
    Depends, Header, WebSocket, WebSocketDisconnect, Query, Body,
    BackgroundTasks, status
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import (
    JSONResponse, HTMLResponse, FileResponse, StreamingResponse,
    PlainTextResponse, RedirectResponse
)
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, validator
from typing import (
    Optional, List, Dict, Any, Set, Tuple, Union
)
from datetime import datetime, timedelta, timezone
from pathlib import Path
from enum import Enum
import sqlite3
import os
import sys
import json
import uuid
import random
import string
import hashlib
import hmac
import secrets
import asyncio
import csv
import io
import re
import math
import logging
from collections import defaultdict, Counter
from contextlib import asynccontextmanager

# ============================================================
# SECTION 2: LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("ercors.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("ercors")

# ============================================================
# SECTION 3: KONFIGURATSIYA
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "ercors.db"
UPLOAD_DIR = BASE_DIR / "uploads"
EXPORT_DIR = BASE_DIR / "exports"
BACKUP_DIR = BASE_DIR / "backups"

for d in [UPLOAD_DIR, EXPORT_DIR, BACKUP_DIR]:
    d.mkdir(exist_ok=True)

APP_NAME = "ERCORS AGI"
APP_VERSION = "9.8.0"
SECRET_KEY = os.getenv("ERCORS_SECRET", "ercors-super-secret-key-change-in-production")
TOKEN_EXPIRY_HOURS = 24 * 7  # 7 kun

# ============================================================
# SECTION 4: ENUMS & MODELS
# ============================================================
class UserType(str, Enum):
    COMPANY = "company"
    EXPERT = "expert"
    ADMIN = "admin"

class TaskPriority(str, Enum):
    HIGH = "high"
    MID = "mid"
    LOW = "low"

class EscrowStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class CampaignStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class NotificationType(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    REFERRAL = "referral"
    PAYMENT = "payment"
    SYSTEM = "system"


# Pydantic models
class RegisterInput(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., regex=r"^[\w\.-]+@[\w\.-]+\.\w+$")
    password: str = Field(..., min_length=6)
    user_type: str = "expert"
    company_name: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    website: Optional[str] = None
    skills: Optional[str] = None
    hourly_rate: Optional[str] = None
    github: Optional[str] = None
    ref: Optional[str] = None


class LoginInput(BaseModel):
    email: str
    password: str


class CampaignInput(BaseModel):
    title: str = Field(..., min_length=3)
    description: str = Field(..., min_length=5)
    required_skills: Optional[str] = ""
    min_experience: float = 0
    keywords: Optional[str] = ""
    budget: str
    deadline: str
    company_id: Optional[int] = None


class PostInput(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)
    user_id: Optional[int] = None


class EscrowInput(BaseModel):
    title: str
    amount: float
    user_id: Optional[int] = None


class TaskInput(BaseModel):
    text: str
    priority: str = "mid"
    user_id: Optional[int] = None


class AIChatInput(BaseModel):
    message: str
    user_id: Optional[int] = None


# ============================================================
# SECTION 5: DATABASE
# ============================================================
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    logger.info("Initializing database...")
    conn = get_db()
    c = conn.cursor()

    # ---------- USERS ----------
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            user_type TEXT NOT NULL DEFAULT 'expert',
            company_name TEXT,
            industry TEXT,
            company_size TEXT,
            website TEXT,
            skills TEXT,
            hourly_rate TEXT,
            github TEXT,
            bio TEXT,
            avatar_url TEXT,
            trust_score REAL DEFAULT 75.0,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            streak INTEGER DEFAULT 0,
            last_login TEXT,
            projects INTEGER DEFAULT 0,
            earnings REAL DEFAULT 0.0,
            referrals INTEGER DEFAULT 0,
            bonus REAL DEFAULT 0.0,
            referred_by INTEGER,
            is_verified INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            country TEXT,
            city TEXT,
            phone TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_type ON users(user_type)")

    # ---------- SESSIONS ----------
    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            expires_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")

    # ---------- CAMPAIGNS ----------
    c.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            required_skills TEXT,
            min_experience REAL DEFAULT 0,
            keywords TEXT,
            budget TEXT,
            deadline TEXT,
            company_id INTEGER,
            company_name TEXT,
            status TEXT DEFAULT 'open',
            views INTEGER DEFAULT 0,
            applications INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(company_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    # ---------- POSTS ----------
    c.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_name TEXT,
            content TEXT NOT NULL,
            likes INTEGER DEFAULT 0,
            shares INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    # ---------- COMMENTS ----------
    c.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            user_id INTEGER,
            user_name TEXT,
            text TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE
        )
    """)

    # ---------- LIKES ----------
    c.execute("""
        CREATE TABLE IF NOT EXISTS post_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(post_id, user_id)
        )
    """)

    # ---------- ESCROW ----------
    c.execute("""
        CREATE TABLE IF NOT EXISTS escrow (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            amount REAL NOT NULL,
            user_id INTEGER,
            client_id INTEGER,
            developer_id INTEGER,
            status TEXT DEFAULT 'pending',
            terms TEXT,
            deadline TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        )
    """)

    # ---------- CANDIDATES (CV) ----------
    c.execute("""
        CREATE TABLE IF NOT EXISTS candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            file_name TEXT,
            file_path TEXT,
            skills TEXT,
            experience_years REAL,
            current_position TEXT,
            summary TEXT,
            raw_text TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ---------- REFERRALS ----------
    c.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            invited_email TEXT,
            invited_user_id INTEGER,
            bonus REAL DEFAULT 50.0,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(referrer_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # ---------- AUDIO INTERVIEWS ----------
    c.execute("""
        CREATE TABLE IF NOT EXISTS audio_interviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            file_name TEXT,
            file_path TEXT,
            position TEXT,
            language TEXT,
            analysis TEXT,
            transcription TEXT,
            match_score REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ---------- TASKS ----------
    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT NOT NULL,
            priority TEXT DEFAULT 'mid',
            done INTEGER DEFAULT 0,
            due_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        )
    """)

    # ---------- NOTIFICATIONS ----------
    c.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT DEFAULT 'info',
            title TEXT NOT NULL,
            message TEXT,
            link TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # ---------- MESSAGES (Chat) ----------
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ---------- TRANSACTIONS (Payments) ----------
    c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL NOT NULL,
            currency TEXT DEFAULT 'USD',
            type TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            description TEXT,
            reference TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ---------- ACHIEVEMENTS ----------
    c.execute("""
        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            icon TEXT,
            xp_reward INTEGER DEFAULT 10,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS user_achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            achievement_id INTEGER NOT NULL,
            unlocked_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, achievement_id)
        )
    """)

    # ---------- LOGS ----------
    c.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT NOT NULL,
            details TEXT,
            ip_address TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ---------- SUBSCRIPTIONS ----------
    c.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan TEXT DEFAULT 'free',
            status TEXT DEFAULT 'active',
            started_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # ---------- REPORTS ----------
    c.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER,
            target_type TEXT,
            target_id INTEGER,
            reason TEXT,
            status TEXT DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ---------- MODULE STATS ----------
    c.execute("""
        CREATE TABLE IF NOT EXISTS module_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module_id TEXT NOT NULL,
            runs INTEGER DEFAULT 0,
            revenue REAL DEFAULT 0.0,
            last_run TEXT,
            UNIQUE(module_id)
        )
    """)

    conn.commit()

    # Seed achievements
    c.executemany(
        """INSERT OR IGNORE INTO achievements (code, title, description, icon, xp_reward)
           VALUES (?, ?, ?, ?, ?)""",
        [
            ("first_login", "Birinchi qadam", "Platformaga birinchi kirish", "fa-sign-in-alt", 10),
            ("profile_complete", "To'liq profil", "Profilni 100% to'ldirish", "fa-user-check", 25),
            ("first_campaign", "Ish beruvchi", "Birinchi kampaniya yaratish", "fa-bullhorn", 20),
            ("first_post", "Ijtimoiy", "Birinchi post yozish", "fa-share-alt", 15),
            ("first_referral", "Taklif qiluvchi", "Birinchi do'stni taklif qilish", "fa-users", 30),
            ("referral_master", "Referral Master", "10 ta do'stni taklif qilish", "fa-crown", 100),
            ("first_escrow", "Ishonchli", "Birinchi escrow yaratish", "fa-lock", 20),
            ("week_streak", "Bir hafta", "7 kun ketma-ket kirish", "fa-fire", 50),
            ("ai_chat_10", "AI do'st", "AI bilan 10 marta suhbat", "fa-robot", 20),
            ("cv_uploaded", "Rezyume", "CV yuklash", "fa-file-pdf", 15),
            ("audio_test", "Ovozli", "Audio intervyu topshirish", "fa-microphone", 15),
            ("level_5", "Tajribali", "5-levelga chiqish", "fa-star", 50),
            ("level_10", "Professional", "10-levelga chiqish", "fa-medal", 100),
            ("verified", "Tasdiqlangan", "Profil tasdiqlangan", "fa-check-circle", 30),
        ]
    )

    # Seed modules
    for i in range(1, 65):
        c.execute(
            "INSERT OR IGNORE INTO module_stats (module_id) VALUES (?)",
            (f"m{i}",)
        )

    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")


# ============================================================
# SECTION 6: HELPERS
# ============================================================
def hash_password(password: str) -> str:
    salt = SECRET_KEY[:16]
    return hashlib.sha256((salt + password).encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed


def generate_token() -> str:
    return secrets.token_urlsafe(48)


def create_session(user_id: int, ip: str = "", ua: str = "") -> str:
    token = generate_token()
    expires = (datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS)).isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO sessions (token, user_id, ip_address, user_agent, expires_at) VALUES (?, ?, ?, ?, ?)",
        (token, user_id, ip, ua[:200], expires)
    )
    conn.commit()
    conn.close()
    return token


def get_user_by_token(token: str) -> Optional[Dict]:
    if not token:
        return None
    conn = get_db()
    row = conn.execute(
        """SELECT u.* FROM users u
           JOIN sessions s ON s.user_id = u.id
           WHERE s.token = ? AND (s.expires_at IS NULL OR s.expires_at > ?)""",
        (token, datetime.utcnow().isoformat())
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def public_user(user: Optional[Dict]) -> Dict:
    if not user:
        return {}
    u = dict(user)
    u.pop("password", None)
    return u


def rows_to_list(rows) -> List[Dict]:
    return [dict(r) for r in rows] if rows else []


def row_to_dict(row) -> Optional[Dict]:
    return dict(row) if row else None


def now_iso() -> str:
    return datetime.utcnow().isoformat()


def log_activity(user_id: Optional[int], action: str, details: str = "", ip: str = ""):
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO activity_logs (user_id, action, details, ip_address) VALUES (?, ?, ?, ?)",
            (user_id, action, details[:500], ip)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Log activity failed: {e}")


def add_notification(user_id: int, type_: str, title: str, message: str = "", link: str = ""):
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO notifications (user_id, type, title, message, link) VALUES (?, ?, ?, ?, ?)",
            (user_id, type_, title, message, link)
        )
        conn.commit()
        conn.close()
        # WebSocket broadcast
        asyncio.create_task(ws_manager.send_to_user(user_id, {
            "type": "notification",
            "title": title,
            "message": message,
            "notification_type": type_,
            "link": link,
        }))
    except Exception as e:
        logger.warning(f"Notification failed: {e}")


def add_xp(user_id: int, amount: int):
    try:
        conn = get_db()
        conn.execute("UPDATE users SET xp = xp + ? WHERE id = ?", (amount, user_id))
        # Level up check
        user = conn.execute("SELECT xp, level FROM users WHERE id = ?", (user_id,)).fetchone()
        if user:
            new_level = user["xp"] // 100 + 1
            if new_level > user["level"]:
                conn.execute("UPDATE users SET level = ? WHERE id = ?", (new_level, user_id))
                conn.commit()
                conn.close()
                add_notification(user_id, "success", f"🎉 Level {new_level}!", f"Siz {new_level}-levelga chiqdingiz!", "/profile")
                return new_level
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Add XP failed: {e}")
    return None


def unlock_achievement(user_id: int, code: str):
    try:
        conn = get_db()
        ach = conn.execute("SELECT * FROM achievements WHERE code = ?", (code,)).fetchone()
        if not ach:
            conn.close()
            return
        exists = conn.execute(
            "SELECT id FROM user_achievements WHERE user_id = ? AND achievement_id = ?",
            (user_id, ach["id"])
        ).fetchone()
        if exists:
            conn.close()
            return
        conn.execute(
            "INSERT INTO user_achievements (user_id, achievement_id) VALUES (?, ?)",
            (user_id, ach["id"])
        )
        conn.commit()
        conn.close()
        add_xp(user_id, ach["xp_reward"])
        add_notification(user_id, "success", f"🏆 {ach['title']}", ach["description"], "/achievements")
    except Exception as e:
        logger.warning(f"Unlock achievement failed: {e}")


# ============================================================
# SECTION 7: MODULES DATA (64)
# ============================================================
MODULE_NAMES = [
    'Enterprise AI Talent Matching', 'Managed RLHF & Data Annotation', 'AI Hiring SaaS & Trust Score',
    'Global Escrow & B2B Contracts', 'Micro‑Equity HFT Engine', 'AI Vetted Engineers',
    'AI & ML Specialists', 'Autonomous AI Agents & Swarm', 'Embedded & Edge AI Hardware',
    'Quantum Computing & Security', 'RLHF & Model Evaluation', 'Code Data Annotation',
    'Multimodal Data Sourcing', 'Red Teaming & AI Safety', 'AI Voice/Video Interview Bot',
    'Code Assessment Engine', 'Background & Trust Score', 'AI Skill Graph Analyzer',
    'Dedicated Remote Teams', 'Express AI Consultation', 'AI Startup Builder On‑Demand',
    'Web3 & Spatial Computing', 'Direct Escrow & Mass Payouts', 'Enterprise SLA & Managed PM',
    'Instant Talent API Access', 'Cloud GPU & TPU Server Access', 'Quantum QPU Remote Access',
    'AI Sandbox & Code Execution Nodes', 'Serverless AI Endpoint Hosting',
    'Autonomous Software Engineer Swarm', 'AI Data Scraping & Web Extraction',
    'Autonomous SMM & Marketing Agents', 'AI Customer Support & Voice Bot',
    'Zero‑Knowledge Proofs Sandbox', 'Automated NDA & Smart Contracts',
    'Deepfake & Synthetic Media Audit', 'WebXR & Spatial VR Showroom',
    '3D Generative Asset Factory', 'Digital Twin Factory Simulation',
    'Custom GLSL Shader & Physics', 'High‑Frequency Micro‑Equity Exchange',
    'Global Crypto & Cross‑Border Escrow', 'Micro‑Equity Flash Loans & Leverage',
    'AI Startup Crowdfunding Portal', 'AI-Powered Code Review', 'Automated Testing Suite',
    'CI/CD Pipeline Integration', 'Docker & Kubernetes Orchestration',
    'AI-Driven Documentation', 'Code Quality Dashboard', 'Real-Time Error Tracking',
    'Performance Monitoring', 'Security Vulnerability Scanner', 'API Gateway & Management',
    'GraphQL Federation', 'Event-Driven Architecture', 'Data Lake & Analytics',
    'MLOps Pipeline', 'Model Monitoring & Drift Detection', 'Feature Store',
    'Explainable AI (XAI)', 'Federated Learning', 'Synthetic Data Generation',
    'AI Governance & Compliance'
]

MODULE_ICONS = [
    'fa-users', 'fa-robot', 'fa-microphone', 'fa-file-signature', 'fa-chart-line',
    'fa-laptop-code', 'fa-brain', 'fa-robot', 'fa-microchip', 'fa-atom', 'fa-comments',
    'fa-tags', 'fa-database', 'fa-shield-halved', 'fa-microphone', 'fa-code',
    'fa-user-check', 'fa-chart-simple', 'fa-people-group', 'fa-user-tie', 'fa-rocket',
    'fa-cubes', 'fa-hand-holding-dollar', 'fa-clipboard-list', 'fa-plug', 'fa-cloud',
    'fa-atom', 'fa-flask', 'fa-server', 'fa-robot', 'fa-spider', 'fa-bullhorn',
    'fa-headset', 'fa-shield', 'fa-gavel', 'fa-video', 'fa-vr-cardboard', 'fa-cube',
    'fa-industry', 'fa-paint-brush', 'fa-chart-pie', 'fa-coins', 'fa-hand-holding-usd',
    'fa-hand-holding-heart', 'fa-code-branch', 'fa-flask', 'fa-gears', 'fa-cubes',
    'fa-book', 'fa-chart-bar', 'fa-bug', 'fa-tachometer-alt', 'fa-shield', 'fa-plug',
    'fa-network-wired', 'fa-bolt', 'fa-database', 'fa-robot', 'fa-chart-line',
    'fa-cubes', 'fa-lightbulb', 'fa-network-wired', 'fa-wand-magic', 'fa-gavel'
]

CATEGORIES = ['Core', 'Talent Sourcing', 'Data & Training', 'Hiring Tools',
              'Direct & Premium', 'Infrastructure', 'Developer Tools']


def get_all_modules() -> List[Dict]:
    modules = []
    for i in range(1, 65):
        cat = CATEGORIES[((i - 1) // 9) % len(CATEGORIES)]
        modules.append({
            "id": f"m{i}",
            "name": MODULE_NAMES[i - 1],
            "category": cat,
            "icon": MODULE_ICONS[i - 1],
            "active": True,
            "description": f"This module provides advanced AI capabilities for {cat.lower()}."
        })
    return modules


# ============================================================
# SECTION 8: AI LOGIC
# ============================================================
AI_RESPONSES = {
    "salom": "Salom, {name}! Men ERCORS AI yordamchisiman. Sizga qanday yordam bera olaman?",
    "hello": "Salom, {name}! Men ERCORS AI yordamchisiman. Sizga qanday yordam bera olaman?",
    "trust": "AI Trust Score (m3) — sizning ko'nikmalaringizni 100% xolis baholovchi tizim. Kod va loyihalaringizni yuklang, 1 soniyada aniq ball olasiz.",
    "ish": "Sizga mos B2B loyihalarni topish uchun CV yuklang yoki GitHub profilingizni ulang. AI avtomatik ravishda eng yaxshi 10 ta loyihani taklif qiladi.",
    "job": "Sizga mos B2B loyihalarni topish uchun CV yuklang yoki GitHub profilingizni ulang. AI avtomatik ravishda eng yaxshi 10 ta loyihani taklif qiladi.",
    "escrow": "ERCORS Escrow — smart-kontrakt asosidagi xavfsiz to'lov tizimi. Kompaniya pulni escrow'ga qo'yadi, ish tugagach avtomatik chiqariladi.",
    "quantum": "Quantum Gateway (m27) — dunyodagi eng tez hisoblash tarmog'i. Kvant algoritmlarini bepul sinab ko'ring.",
    "referral": "Referral dasturi: har bir do'stingiz uchun $50 bonus olasiz! Linkni nusxalab, do'stlaringizga yuboring.",
    "agent": "Autonomous AI Agents (m30) — sizning biznesingizni 24/7 boshqaruvchi sun'iy intellekt. 3 soniyada yaratish mumkin!",
    "ai": "ERCORS AI — sizning shaxsiy yordamchingiz. Trust Score, ish topish, escrow, quantum va boshqa modullar haqida so'rang.",
    "help": "Men quyidagilarda yordam bera olaman: AI Trust Score, ish topish, Escrow to'lovlar, AI Agents, Quantum, Referral va boshqalar.",
}


def ai_chat_response(message: str, user: Optional[Dict]) -> str:
    msg = message.lower()
    name = user.get("full_name", "do'stim") if user else "do'stim"

    for key, response in AI_RESPONSES.items():
        if key in msg:
            return response.format(name=name)

    if "yordam" in msg or "nima qila" in msg:
        return AI_RESPONSES["help"]

    return (f"Tushundim, {name}. ERCORS platformasi 64 ta modulni o'z ichiga oladi. "
            "Sizga aniqroq yordam berish uchun mavzuni aniqlashtirib bering "
            "(masalan: 'ish topish', 'trust score', 'escrow').")


# ============================================================
# SECTION 9: WEBSOCKET MANAGER
# ============================================================
class WebSocketManager:
    def __init__(self):
        self.active: Dict[int, List[WebSocket]] = defaultdict(list)
        self.lock = asyncio.Lock()

    async def connect(self, user_id: int, ws: WebSocket):
        await ws.accept()
        async with self.lock:
            self.active[user_id].append(ws)
        logger.info(f"WS connected: user {user_id}")

    def disconnect(self, user_id: int, ws: WebSocket):
        try:
            if user_id in self.active and ws in self.active[user_id]:
                self.active[user_id].remove(ws)
            if user_id in self.active and not self.active[user_id]:
                del self.active[user_id]
        except Exception:
            pass
        logger.info(f"WS disconnected: user {user_id}")

    async def send_to_user(self, user_id: int, data: dict):
        async with self.lock:
            sockets = list(self.active.get(user_id, []))
        for ws in sockets:
            try:
                await ws.send_json(data)
            except Exception:
                pass

    async def broadcast(self, data: dict):
        async with self.lock:
            all_ws = [ws for lst in self.active.values() for ws in lst]
        for ws in all_ws:
            try:
                await ws.send_json(data)
            except Exception:
                pass


ws_manager = WebSocketManager()


# ============================================================
# SECTION 10: APP LIFESPAN
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("=" * 60)
    logger.info(f" 🚀 {APP_NAME} v{APP_VERSION} ishga tushdi")
    logger.info(f" 📁 Database: {DB_PATH}")
    logger.info(f" 🌐 http://localhost:8000")
    logger.info(f" 📖 Docs:     http://localhost:8000/docs")
    logger.info("=" * 60)
    yield
    logger.info("Server to'xtatildi")


app = FastAPI(
    title=f"{APP_NAME} API",
    version=APP_VERSION,
    lifespan=lifespan,
    description="Global Autonomous Engine & AI Trust Ecosystem"
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1000)


# ============================================================
# SECTION 11: AUTH DEPENDENCY
# ============================================================
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[Dict]:
    if not credentials:
        return None
    return get_user_by_token(credentials.credentials)


async def require_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict:
    user = await get_current_user(credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def require_admin(user: Dict = Depends(require_user)) -> Dict:
    if user.get("user_type") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ============================================================
# SECTION 12: HEALTH & ROOT
# ============================================================
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
        "timestamp": now_iso(),
        "uptime_seconds": int((datetime.utcnow() - datetime(2024, 1, 1)).total_seconds()),
    }


@app.get("/", response_class=HTMLResponse)
def serve_index():
    index_path = BASE_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    return HTMLResponse(content=f"""
        <html><body style="font-family:sans-serif;padding:40px;background:#030712;color:#00f0ff;">
        <h1>{APP_NAME} Backend ✅</h1>
        <p>index.html faylini shu papkaga qo'ying.</p>
        <p>API docs: <a href="/docs" style="color:#22d3ee;">/docs</a></p>
        </body></html>
    """)


# ============================================================
# SECTION 13: MODULES ENDPOINTS
# ============================================================
@app.get("/api/modules")
def api_modules():
    return get_all_modules()


@app.get("/api/modules/{module_id}")
def api_module_detail(module_id: str):
    mod = next((m for m in get_all_modules() if m["id"] == module_id), None)
    if not mod:
        raise HTTPException(status_code=404, detail="Module not found")
    conn = get_db()
    stats = conn.execute(
        "SELECT * FROM module_stats WHERE module_id = ?", (module_id,)
    ).fetchone()
    conn.close()
    result = dict(mod)
    if stats:
        result["stats"] = dict(stats)
    return result


@app.post("/api/modules/{module_id}/action")
async def api_module_action(module_id: str, request: Request):
    mod = next((m for m in get_all_modules() if m["id"] == module_id), None)
    if not mod:
        raise HTTPException(status_code=404, detail="Module not found")

    form = await request.form()
    user_id = form.get("user_id")

    # Update stats
    conn = get_db()
    conn.execute(
        """INSERT INTO module_stats (module_id, runs, revenue, last_run)
           VALUES (?, 1, ?, ?)
           ON CONFLICT(module_id) DO UPDATE SET
             runs = runs + 1,
             revenue = revenue + excluded.revenue,
             last_run = excluded.last_run""",
        (module_id, random.uniform(10, 500), now_iso())
    )
    conn.commit()
    conn.close()

    return {
        "status": "success",
        "module_id": module_id,
        "action_result": {
            "executed_at": now_iso(),
            "message": f"{mod['name']} executed successfully",
            "user_id": user_id,
            "duration_ms": random.randint(50, 500),
            "output": {
                "processed": random.randint(1, 100),
                "success_rate": f"{random.uniform(95, 100):.2f}%",
                "credits_used": random.randint(1, 10)
            }
        }
    }


# ============================================================
# SECTION 14: TALENTS
# ============================================================
@app.get("/api/talents")
def api_talents(limit: int = 20, offset: int = 0, skill: Optional[str] = None):
    conn = get_db()
    query = "SELECT id, full_name, skills, user_type, trust_score, hourly_rate, country FROM users WHERE user_type = 'expert' AND is_active = 1"
    params: List[Any] = []
    if skill:
        query += " AND skills LIKE ?"
        params.append(f"%{skill}%")
    query += " ORDER BY trust_score DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    conn.close()

    talents = [
        {
            "id": r["id"],
            "name": r["full_name"],
            "skills": r["skills"] or "AI, ML",
            "title": "AI Expert",
            "trust_score": f"{r['trust_score']:.1f}",
            "hourly_rate": r["hourly_rate"],
            "country": r["country"],
        }
        for r in rows
    ]

    # Seed mocks if empty
    if not talents:
        defaults = [
            {"id": 1, "name": "Alice Johnson", "skills": "Python, PyTorch, LLM", "title": "Senior AI Engineer", "trust_score": "99.2", "hourly_rate": "150", "country": "US"},
            {"id": 2, "name": "Bob Smith", "skills": "Rust, C++, Quantum", "title": "Systems Architect", "trust_score": "98.7", "hourly_rate": "180", "country": "UK"},
            {"id": 3, "name": "Carol White", "skills": "React, Node, TypeScript", "title": "Full-Stack Lead", "trust_score": "97.9", "hourly_rate": "120", "country": "DE"},
            {"id": 4, "name": "David Chen", "skills": "Go, Kubernetes, AWS", "title": "DevOps Architect", "trust_score": "98.1", "hourly_rate": "140", "country": "SG"},
            {"id": 5, "name": "Elena Rodriguez", "skills": "Data Science, R, SQL", "title": "Data Science Lead", "trust_score": "97.5", "hourly_rate": "130", "country": "ES"},
        ]
        return defaults
    return talents


@app.get("/api/talents/{user_id}")
def api_talent_detail(user_id: int):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE id = ? AND user_type = 'expert'", (user_id,)
    ).fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=404, detail="Talent not found")
    return public_user(dict(user))


# ============================================================
# SECTION 15: CAMPAIGNS
# ============================================================
@app.get("/api/campaigns")
def api_campaigns_list(
    limit: int = 50,
    offset: int = 0,
    status_filter: Optional[str] = Query(None, alias="status"),
):
    conn = get_db()
    query = "SELECT * FROM campaigns"
    params: List[Any] = []
    if status_filter:
        query += " WHERE status = ?"
        params.append(status_filter)
    query += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return rows_to_list(rows)


@app.get("/api/campaigns/{campaign_id}")
def api_campaign_detail(campaign_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")
    # Increment views
    conn.execute("UPDATE campaigns SET views = views + 1 WHERE id = ?", (campaign_id,))
    conn.commit()
    conn.close()
    return dict(row)


@app.post("/api/campaigns")
async def api_campaign_create(request: Request, user: Optional[Dict] = Depends(get_current_user)):
    form = await request.form()
    title = form.get("title")
    if not title:
        raise HTTPException(status_code=400, detail="Title required")

    company_id = form.get("company_id") or (user["id"] if user else None)
    company_name = None
    if company_id:
        conn = get_db()
        row = conn.execute(
            "SELECT company_name, full_name FROM users WHERE id = ?", (company_id,)
        ).fetchone()
        if row:
            company_name = row["company_name"] or row["full_name"]
        conn.close()

    conn = get_db()
    cur = conn.execute(
        """INSERT INTO campaigns
           (title, description, required_skills, min_experience, keywords, budget, deadline, company_id, company_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            title,
            form.get("description", ""),
            form.get("required_skills", ""),
            float(form.get("min_experience") or 0),
            form.get("keywords", ""),
            form.get("budget", ""),
            form.get("deadline", ""),
            int(company_id) if company_id else None,
            company_name,
        ),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()

    if user:
        add_xp(user["id"], 20)
        unlock_achievement(user["id"], "first_campaign")

    return {"status": "success", "message": "Campaign created", "campaign_id": new_id}


@app.delete("/api/campaigns/{campaign_id}")
def api_campaign_delete(campaign_id: int, user: Dict = Depends(require_user)):
    conn = get_db()
    campaign = conn.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
    if not campaign:
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign["company_id"] != user["id"] and user["user_type"] != "admin":
        conn.close()
        raise HTTPException(status_code=403, detail="Not authorized")
    conn.execute("DELETE FROM campaigns WHERE id = ?", (campaign_id,))
    conn.commit()
    conn.close()
    return {"status": "success"}


# ============================================================
# SECTION 16: POSTS & COMMENTS
# ============================================================
@app.get("/api/posts")
def api_posts_list(limit: int = 50, offset: int = 0):
    conn = get_db()
    posts = conn.execute(
        "SELECT * FROM posts ORDER BY id DESC LIMIT ? OFFSET ?",
        (limit, offset)
    ).fetchall()
    result = []
    for p in posts:
        comments = conn.execute(
            "SELECT id, user_id, user_name, text, created_at FROM comments WHERE post_id = ? ORDER BY id ASC",
            (p["id"],)
        ).fetchall()
        post_dict = dict(p)
        post_dict["comments"] = rows_to_list(comments)
        result.append(post_dict)
    conn.close()
    return result


@app.post("/api/posts")
async def api_posts_create(request: Request, user: Optional[Dict] = Depends(get_current_user)):
    form = await request.form()
    content = form.get("content")
    user_id = form.get("user_id") or (user["id"] if user else None)
    if not content:
        raise HTTPException(status_code=400, detail="Content required")

    user_name = "Anonymous"
    if user_id:
        conn = get_db()
        row = conn.execute("SELECT full_name FROM users WHERE id = ?", (user_id,)).fetchone()
        if row:
            user_name = row["full_name"]
        conn.close()

    conn = get_db()
    cur = conn.execute(
        "INSERT INTO posts (user_id, user_name, content) VALUES (?, ?, ?)",
        (int(user_id) if user_id else None, user_name, content),
    )
    conn.commit()
    post_id = cur.lastrowid
    conn.close()

    if user_id:
        add_xp(int(user_id), 5)
        unlock_achievement(int(user_id), "first_post")

    return {"status": "success", "post_id": post_id}


@app.post("/api/posts/{post_id}/like")
def api_post_like(post_id: int, user: Optional[Dict] = Depends(get_current_user)):
    conn = get_db()
    post = conn.execute("SELECT id FROM posts WHERE id = ?", (post_id,)).fetchone()
    if not post:
        conn.close()
        raise HTTPException(status_code=404, detail="Post not found")

    user_id = user["id"] if user else 0
    existing = conn.execute(
        "SELECT id FROM post_likes WHERE post_id = ? AND user_id = ?",
        (post_id, user_id)
    ).fetchone()

    if existing:
        conn.execute("DELETE FROM post_likes WHERE id = ?", (existing["id"],))
        conn.execute("UPDATE posts SET likes = MAX(0, likes - 1) WHERE id = ?", (post_id,))
        conn.commit()
        conn.close()
        return {"status": "success", "action": "unliked"}

    conn.execute("INSERT INTO post_likes (post_id, user_id) VALUES (?, ?)", (post_id, user_id))
    conn.execute("UPDATE posts SET likes = likes + 1 WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()
    if user:
        add_xp(user["id"], 1)
    return {"status": "success", "action": "liked"}


@app.post("/api/posts/{post_id}/comment")
async def api_post_comment(post_id: int, request: Request, user: Optional[Dict] = Depends(get_current_user)):
    form = await request.form()
    text = form.get("text")
    user_id = form.get("user_id") or (user["id"] if user else None)
    if not text:
        raise HTTPException(status_code=400, detail="Text required")

    user_name = "Anonymous"
    if user_id:
        conn = get_db()
        row = conn.execute("SELECT full_name FROM users WHERE id = ?", (user_id,)).fetchone()
        if row:
            user_name = row["full_name"]
        conn.close()

    conn = get_db()
    conn.execute(
        "INSERT INTO comments (post_id, user_id, user_name, text) VALUES (?, ?, ?, ?)",
        (post_id, int(user_id) if user_id else None, user_name, text),
    )
    conn.commit()
    conn.close()

    if user_id:
        add_xp(int(user_id), 3)

    return {"status": "success"}


@app.delete("/api/posts/{post_id}")
def api_post_delete(post_id: int, user: Dict = Depends(require_user)):
    conn = get_db()
    post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if not post:
        conn.close()
        raise HTTPException(status_code=404, detail="Post not found")
    if post["user_id"] != user["id"] and user["user_type"] != "admin":
        conn.close()
        raise HTTPException(status_code=403, detail="Not authorized")
    conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    conn.execute("DELETE FROM comments WHERE post_id = ?", (post_id,))
    conn.commit()
    conn.close()
    return {"status": "success"}


# ============================================================
# SECTION 17: ESCROW
# ============================================================
@app.get("/api/escrow")
def api_escrow_list(user: Optional[Dict] = Depends(get_current_user)):
    conn = get_db()
    if user:
        rows = conn.execute(
            """SELECT * FROM escrow
               WHERE client_id = ? OR developer_id = ? OR user_id = ?
               ORDER BY id DESC LIMIT 100""",
            (user["id"], user["id"], user["id"])
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM escrow ORDER BY id DESC LIMIT 50").fetchall()
    conn.close()
    return rows_to_list(rows)


@app.post("/api/escrow")
async def api_escrow_create(request: Request, user: Optional[Dict] = Depends(get_current_user)):
    form = await request.form()
    title = form.get("title")
    amount = form.get("amount")
    user_id = form.get("user_id") or (user["id"] if user else None)
    if not title or not amount:
        raise HTTPException(status_code=400, detail="Title & amount required")

    conn = get_db()
    cur = conn.execute(
        "INSERT INTO escrow (title, amount, user_id, client_id, status) VALUES (?, ?, ?, ?, 'pending')",
        (title, float(amount), int(user_id) if user_id else None, int(user_id) if user_id else None),
    )
    conn.commit()
    escrow_id = cur.lastrowid
    conn.close()

    if user_id:
        add_xp(int(user_id), 15)
        unlock_achievement(int(user_id), "first_escrow")

    return {"status": "success", "escrow_id": escrow_id}


@app.patch("/api/escrow/{escrow_id}")
async def api_escrow_update(escrow_id: int, request: Request, user: Dict = Depends(require_user)):
    form = await request.form()
    new_status = form.get("status")
    valid = ["pending", "active", "completed", "cancelled"]
    if new_status not in valid:
        raise HTTPException(status_code=400, detail="Invalid status")

    conn = get_db()
    escrow = conn.execute("SELECT * FROM escrow WHERE id = ?", (escrow_id,)).fetchone()
    if not escrow:
        conn.close()
        raise HTTPException(status_code=404, detail="Escrow not found")

    completed_at = now_iso() if new_status == "completed" else None
    conn.execute(
        "UPDATE escrow SET status = ?, completed_at = ? WHERE id = ?",
        (new_status, completed_at, escrow_id)
    )
    conn.commit()
    conn.close()

    if new_status == "completed" and escrow["developer_id"]:
        add_notification(escrow["developer_id"], "payment", "💰 To'lov qabul qilindi",
                        f"${escrow['amount']} escrow'dan chiqarildi", "/escrow")

    return {"status": "success"}


# ============================================================
# SECTION 18: AI CHAT
# ============================================================
@app.post("/api/v1/ai/chat")
async def api_ai_chat(request: Request, user: Optional[Dict] = Depends(get_current_user)):
    form = await request.form()
    message = form.get("message", "")
    user_id = form.get("user_id")
    if user_id:
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            user_id = None

    if not user and user_id:
        conn = get_db()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        user = dict(row) if row else None
        conn.close()

    response = ai_chat_response(message, user)

    if user_id:
        add_xp(user_id, 1)

    return {
        "status": "success",
        "response": response,
        "timestamp": now_iso(),
        "model": "ercors-ai-v1",
    }


# ============================================================
# SECTION 19: HARVESTER
# ============================================================
@app.post("/api/v1/harvester/start")
async def api_harvester_start(request: Request):
    form = await request.form()
    language = form.get("harvesterLanguage", "python")
    min_stars = form.get("harvesterMinStars", 50)
    limit = form.get("harvesterLimit", 10)

    job_id = uuid.uuid4().hex[:12]

    return {
        "status": "RUNNING",
        "message": f"Harvester started: {language}, min stars={min_stars}, limit={limit}",
        "job_id": job_id,
        "found": random.randint(5, 25),
        "repos": [
            {
                "name": f"repo-{i}",
                "url": f"https://github.com/user/repo-{i}",
                "stars": random.randint(50, 5000),
                "language": language
            }
            for i in range(1, 6)
        ]
    }


# ============================================================
# SECTION 20: NEGOTIATOR
# ============================================================
@app.post("/api/v1/negotiate/contract")
async def api_negotiate(request: Request):
    form = await request.form()
    company = form.get("negotiateCompany", "Company")
    developer = form.get("negotiateDeveloper", "Developer")
    scope = form.get("negotiateScope", "AI Project")
    budget_range = form.get("negotiateBudget", "10000-20000")

    try:
        parts = budget_range.replace(",", "").split("-")
        low = float(parts[0].strip())
        high = float(parts[1].strip()) if len(parts) > 1 else low * 1.5
        final_budget = (low + high) / 2
    except Exception:
        final_budget = 15000

    return {
        "status": "success",
        "negotiation": {
            "company": company,
            "developer": developer,
            "scope": scope,
            "budget": round(final_budget, 2),
            "deadline": "30 days",
            "terms": f"Standard NDA + Escrow for {scope}",
            "accepted": True,
            "confidence": round(random.uniform(0.85, 0.99), 2)
        }
    }


# ============================================================
# SECTION 21: CV UPLOAD
# ============================================================
@app.post("/api/upload-cv")
async def api_upload_cv(
    file: UploadFile = File(...),
    user_id: Optional[str] = Form(None),
):
    safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    file_path = UPLOAD_DIR / safe_name
    content = await file.read()
    file_path.write_bytes(content)

    text = content.decode("utf-8", errors="ignore")[:5000].lower()

    skill_keywords = [
        "python", "javascript", "java", "c++", "rust", "go", "react", "node",
        "typescript", "pytorch", "tensorflow", "sql", "aws", "docker",
        "kubernetes", "ai", "ml", "llm", "django", "flask", "fastapi",
        "vue", "angular", "mongodb", "postgresql", "redis", "graphql"
    ]
    found_skills = [s for s in skill_keywords if s in text]
    if not found_skills:
        found_skills = ["Python", "JavaScript", "AI"]

    analysis = {
        "skills": [s.capitalize() for s in found_skills],
        "experience_years": random.randint(3, 10),
        "current_position": "Senior Software Engineer",
        "summary": "Experienced professional with strong AI/ML background."
    }

    conn = get_db()
    cur = conn.execute(
        """INSERT INTO candidates
           (user_id, file_name, file_path, skills, experience_years, current_position, summary, raw_text)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            int(user_id) if user_id else None,
            file.filename,
            str(file_path),
            ",".join(analysis["skills"]),
            analysis["experience_years"],
            analysis["current_position"],
            analysis["summary"],
            text[:1000],
        ),
    )
    conn.commit()
    candidate_id = cur.lastrowid

    campaigns = conn.execute("SELECT * FROM campaigns").fetchall()
    conn.close()

    matched = 0
    for c in campaigns:
        req = (c["required_skills"] or "").lower()
        if any(s.lower() in req for s in analysis["skills"]):
            matched += 1

    if not campaigns:
        matched = random.randint(1, 3)

    if user_id:
        try:
            add_xp(int(user_id), 15)
            unlock_achievement(int(user_id), "cv_uploaded")
        except Exception:
            pass

    return {
        "status": "success",
        "candidate_id": candidate_id,
        "campaigns_matched": matched,
        "analysis": analysis,
        "message": f"CV analyzed. Matched to {matched} campaigns."
    }


@app.get("/api/candidates/{candidate_id}/match")
def api_candidate_match(candidate_id: int):
    conn = get_db()
    candidate = conn.execute("SELECT * FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
    campaigns = conn.execute("SELECT * FROM campaigns LIMIT 20").fetchall()
    conn.close()

    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    cand_skills = set((candidate["skills"] or "").lower().replace(" ", "").split(","))
    matches = []
    for c in campaigns:
        req = set((c["required_skills"] or "").lower().replace(" ", "").split(","))
        if not req:
            score = random.randint(50, 85)
        else:
            overlap = len(cand_skills & req)
            score = min(99, int((overlap / max(len(req), 1)) * 100) + random.randint(0, 20))
        if score >= 50:
            matches.append({
                "campaign_id": c["id"],
                "campaign_name": c["title"],
                "match_score": score,
            })

    matches.sort(key=lambda x: x["match_score"], reverse=True)

    if not matches:
        matches = [
            {"campaign_id": 1, "campaign_name": "AI Platform Development", "match_score": 94},
            {"campaign_id": 2, "campaign_name": "ML Pipeline Engineer", "match_score": 88},
        ]

    return {"status": "success", "matches": matches[:5]}


# ============================================================
# SECTION 22: AUDIO INTERVIEW
# ============================================================
@app.post("/api/v1/hr/audio/analyze-interview")
async def api_audio_analyze(
    file: UploadFile = File(...),
    user_id: Optional[str] = Form(None),
    position: Optional[str] = Form(None),
    language: Optional[str] = Form("en"),
):
    safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    file_path = UPLOAD_DIR / safe_name
    content = await file.read()
    file_path.write_bytes(content)

    strengths_pool = [
        "Problem solving", "Python", "System Design", "Communication",
        "Teamwork", "Leadership", "Machine Learning", "Fast learner"
    ]
    weaknesses_pool = ["Limited frontend", "Public speaking", "Time management"]

    analysis = {
        "summary": "Candidate demonstrates strong technical skills and clear communication.",
        "strengths": random.sample(strengths_pool, 3),
        "weaknesses": random.sample(weaknesses_pool, 1),
        "match_score": random.randint(70, 95),
        "recommendation": "Proceed to technical interview"
    }
    transcription = (
        "[Mock transcription] I have several years of experience in software development, "
        "with a focus on Python, machine learning, and building scalable systems. "
        "I enjoy solving complex problems and working with cross-functional teams."
    )

    conn = get_db()
    conn.execute(
        """INSERT INTO audio_interviews
           (user_id, file_name, file_path, position, language, analysis, transcription, match_score)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            int(user_id) if user_id else None,
            file.filename,
            str(file_path),
            position or "",
            language or "en",
            json.dumps(analysis),
            transcription,
            analysis["match_score"],
        ),
    )
    conn.commit()
    conn.close()

    if user_id:
        try:
            add_xp(int(user_id), 15)
            unlock_achievement(int(user_id), "audio_test")
        except Exception:
            pass

    return {
        "status": "success",
        "analysis": analysis,
        "transcription": transcription,
        "campaigns_matched": random.randint(1, 3),
    }


# ============================================================
# SECTION 23: AUTH
# ============================================================
@app.post("/api/register")
async def api_register(request: Request):
    form = await request.form()
    full_name = form.get("full_name")
    email = form.get("email")
    password = form.get("password")
    user_type = form.get("user_type", "expert")

    if not all([full_name, email, password]):
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Barcha maydonlar to'ldirilishi shart"}
        )

    if len(password) < 6:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Parol kamida 6 ta belgi"}
        )

    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        conn.close()
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Bu email allaqachon ro'yxatdan o'tgan"}
        )

    referred_by = None
    ref_param = form.get("ref")
    if ref_param:
        try:
            referred_by = int(ref_param)
            ref_user = conn.execute("SELECT id FROM users WHERE id = ?", (referred_by,)).fetchone()
            if not ref_user:
                referred_by = None
            else:
                conn.execute(
                    "UPDATE users SET referrals = referrals + 1, bonus = bonus + 50 WHERE id = ?",
                    (referred_by,)
                )
                conn.execute(
                    "INSERT INTO referrals (referrer_id, invited_email, bonus, status) VALUES (?, ?, 50, 'pending')",
                    (referred_by, email)
                )
        except (ValueError, TypeError):
            referred_by = None

    try:
        cur = conn.execute(
            """INSERT INTO users
               (full_name, email, password, user_type, company_name, industry,
                company_size, website, skills, hourly_rate, github, referred_by, xp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 20)""",
            (
                full_name,
                email,
                hash_password(password),
                user_type,
                form.get("company_name"),
                form.get("industry"),
                form.get("company_size"),
                form.get("website"),
                form.get("skills"),
                form.get("hourly_rate"),
                form.get("github"),
                referred_by,
            ),
        )
        conn.commit()
        user_id = cur.lastrowid
    except Exception as e:
        conn.close()
        logger.error(f"Register error: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"DB error: {str(e)}"}
        )

    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()

    token = create_session(user_id)

    # Trigger notifications
    add_notification(user_id, "success", "🎉 Xush kelibsiz!", "ERCORS AGI platformasiga muvaffaqiyatli ro'yxatdan o'tdingiz.", "/dashboard")
    if referred_by:
        add_notification(referred_by, "referral", "💰 Yangi referral!", f"{full_name} sizning linkingiz orqali ro'yxatdan o'tdi. +$50 bonus!", "/viral")

    log_activity(user_id, "register", f"User {email} registered as {user_type}")

    return {
        "status": "success",
        "message": "Muvaffaqiyatli ro'yxatdan o'tdingiz!",
        "user": public_user(dict(user)),
        "session": token,
    }


@app.post("/api/login")
async def api_login(request: Request):
    form = await request.form()
    email = form.get("email")
    password = form.get("password")

    if not email or not password:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Email va parol kiritilishi shart"}
        )

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

    if not user or not verify_password(password, user["password"]):
        conn.close()
        return JSONResponse(
            status_code=401,
            content={"status": "error", "message": "Email yoki parol xato"}
        )

    # Update last login & streak
    today = datetime.utcnow().date().isoformat()
    last_login = (user["last_login"] or "")[:10]
    if last_login != today:
        new_streak = (user["streak"] or 0) + 1 if last_login == (datetime.utcnow().date() - timedelta(days=1)).isoformat() else 1
        conn.execute(
            "UPDATE users SET last_login = ?, streak = ?, xp = xp + 10 WHERE id = ?",
            (now_iso(), new_streak, user["id"])
        )
        conn.commit()

        if new_streak >= 7:
            unlock_achievement(user["id"], "week_streak")

    user_dict = dict(user)
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    user_dict = dict(user)
    conn.close()

    token = create_session(
        user_dict["id"],
        ip=request.client.host if request.client else "",
        ua=request.headers.get("user-agent", "")
    )

    log_activity(user_dict["id"], "login", f"Login from {request.client.host if request.client else 'unknown'}")

    return {
        "status": "success",
        "message": "Xush kelibsiz!",
        "user": public_user(user_dict),
        "session": token,
    }


@app.post("/api/logout")
def api_logout(
    authorization: Optional[str] = Header(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    token = None
    if credentials:
        token = credentials.credentials
    elif authorization:
        token = authorization.replace("Bearer ", "").strip()

    if token:
        conn = get_db()
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        conn.close()
    return {"status": "success"}


@app.get("/api/me")
def api_me(user: Dict = Depends(require_user)):
    conn = get_db()
    achievements = conn.execute(
        """SELECT a.*, ua.unlocked_at FROM achievements a
           JOIN user_achievements ua ON ua.achievement_id = a.id
           WHERE ua.user_id = ?""",
        (user["id"],)
    ).fetchall()
    conn.close()

    result = public_user(user)
    result["achievements"] = rows_to_list(achievements)
    return {"status": "success", "user": result}


# ============================================================
# SECTION 24: USER PROFILE UPDATE
# ============================================================
@app.patch("/api/profile")
async def api_profile_update(request: Request, user: Dict = Depends(require_user)):
    form = await request.form()
    fields = ["full_name", "company_name", "industry", "company_size", "website",
              "skills", "hourly_rate", "github", "bio", "avatar_url", "country", "city", "phone"]

    updates = []
    params = []
    for f in fields:
        v = form.get(f)
        if v is not None:
            updates.append(f"{f} = ?")
            params.append(v)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates.append("updated_at = ?")
    params.append(now_iso())
    params.append(user["id"])

    conn = get_db()
    conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    updated = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    conn.close()

    return {"status": "success", "user": public_user(dict(updated))}


# ============================================================
# SECTION 25: REFERRAL
# ============================================================
@app.get("/api/referral/stats")
def api_referral_stats(user: Dict = Depends(require_user)):
    conn = get_db()
    user_row = conn.execute(
        "SELECT referrals, bonus FROM users WHERE id = ?", (user["id"],)
    ).fetchone()
    history = conn.execute(
        """SELECT r.*, u.full_name as invited_name FROM referrals r
           LEFT JOIN users u ON u.id = r.invited_user_id
           WHERE r.referrer_id = ? ORDER BY r.id DESC LIMIT 20""",
        (user["id"],)
    ).fetchall()
    conn.close()

    return {
        "status": "success",
        "referrals": user_row["referrals"] if user_row else 0,
        "bonus": user_row["bonus"] if user_row else 0,
        "referral_link": f"?ref={user['id']}",
        "history": rows_to_list(history),
    }


@app.get("/api/referral/leaderboard")
def api_referral_leaderboard():
    conn = get_db()
    rows = conn.execute(
        """SELECT full_name, referrals, bonus, avatar_url FROM users
           WHERE referrals > 0 ORDER BY referrals DESC LIMIT 20"""
    ).fetchall()
    conn.close()

    leaderboard = rows_to_list(rows)
    if not leaderboard:
        leaderboard = [
            {"full_name": "Sardor K.", "referrals": 142, "bonus": 7100},
            {"full_name": "Malika A.", "referrals": 98, "bonus": 4900},
            {"full_name": "Javohir T.", "referrals": 76, "bonus": 3800},
            {"full_name": "Dilnoza R.", "referrals": 54, "bonus": 2700},
            {"full_name": "Aziz M.", "referrals": 41, "bonus": 2050},
        ]
    return leaderboard


# ============================================================
# SECTION 26: TASKS
# ============================================================
@app.get("/api/tasks")
def api_tasks_list(user: Dict = Depends(require_user)):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM tasks WHERE user_id = ? ORDER BY done ASC, id DESC",
        (user["id"],)
    ).fetchall()
    conn.close()
    return rows_to_list(rows)


@app.post("/api/tasks")
async def api_task_create(request: Request, user: Dict = Depends(require_user)):
    form = await request.form()
    text = form.get("text")
    if not text:
        raise HTTPException(status_code=400, detail="Text required")

    conn = get_db()
    cur = conn.execute(
        "INSERT INTO tasks (user_id, text, priority) VALUES (?, ?, ?)",
        (user["id"], text, form.get("priority", "mid")),
    )
    conn.commit()
    task_id = cur.lastrowid
    conn.close()
    add_xp(user["id"], 2)
    return {"status": "success", "task_id": task_id}


@app.patch("/api/tasks/{task_id}")
async def api_task_update(task_id: int, request: Request, user: Dict = Depends(require_user)):
    form = await request.form()
    done = int(form.get("done", 0))
    conn = get_db()
    conn.execute(
        "UPDATE tasks SET done = ?, completed_at = ? WHERE id = ? AND user_id = ?",
        (done, now_iso() if done else None, task_id, user["id"])
    )
    conn.commit()
    conn.close()
    if done:
        add_xp(user["id"], 3)
    return {"status": "success"}


@app.delete("/api/tasks/{task_id}")
def api_task_delete(task_id: int, user: Dict = Depends(require_user)):
    conn = get_db()
    conn.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user["id"]))
    conn.commit()
    conn.close()
    return {"status": "success"}


# ============================================================
# SECTION 27: NOTIFICATIONS
# ============================================================
@app.get("/api/notifications")
def api_notifications(user: Dict = Depends(require_user), limit: int = 50):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user["id"], limit)
    ).fetchall()
    unread = conn.execute(
        "SELECT COUNT(*) as c FROM notifications WHERE user_id = ? AND is_read = 0",
        (user["id"],)
    ).fetchone()["c"]
    conn.close()
    return {"status": "success", "notifications": rows_to_list(rows), "unread": unread}


@app.post("/api/notifications/read-all")
def api_notifications_read_all(user: Dict = Depends(require_user)):
    conn = get_db()
    conn.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (user["id"],))
    conn.commit()
    conn.close()
    return {"status": "success"}


@app.post("/api/notifications/{notification_id}/read")
def api_notification_read(notification_id: int, user: Dict = Depends(require_user)):
    conn = get_db()
    conn.execute(
        "UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?",
        (notification_id, user["id"])
    )
    conn.commit()
    conn.close()
    return {"status": "success"}


# ============================================================
# SECTION 28: ACHIEVEMENTS
# ============================================================
@app.get("/api/achievements")
def api_achievements_list():
    conn = get_db()
    rows = conn.execute("SELECT * FROM achievements").fetchall()
    conn.close()
    return rows_to_list(rows)


@app.get("/api/achievements/mine")
def api_achievements_mine(user: Dict = Depends(require_user)):
    conn = get_db()
    rows = conn.execute(
        """SELECT a.*, ua.unlocked_at FROM achievements a
           JOIN user_achievements ua ON ua.achievement_id = a.id
           WHERE ua.user_id = ? ORDER BY ua.id DESC""",
        (user["id"],)
    ).fetchall()
    conn.close()
    return rows_to_list(rows)


# ============================================================
# SECTION 29: LEADERBOARD (Global)
# ============================================================
@app.get("/api/leaderboard")
def api_leaderboard(limit: int = 20):
    conn = get_db()
    rows = conn.execute(
        """SELECT id, full_name, xp, level, trust_score, referrals, earnings, avatar_url
           FROM users WHERE is_active = 1
           ORDER BY xp DESC LIMIT ?""",
        (limit,)
    ).fetchall()
    conn.close()
    return rows_to_list(rows)


# ============================================================
# SECTION 30: ANALYTICS
# ============================================================
@app.get("/api/stats")
def api_stats():
    conn = get_db()
    users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    experts = conn.execute("SELECT COUNT(*) as c FROM users WHERE user_type='expert'").fetchone()["c"]
    companies = conn.execute("SELECT COUNT(*) as c FROM users WHERE user_type='company'").fetchone()["c"]
    campaigns = conn.execute("SELECT COUNT(*) as c FROM campaigns").fetchone()["c"]
    posts = conn.execute("SELECT COUNT(*) as c FROM posts").fetchone()["c"]
    escrows = conn.execute("SELECT COUNT(*) as c FROM escrow").fetchone()["c"]
    conn.close()

    return {
        "status": "success",
        "users": users,
        "experts": experts,
        "companies": companies,
        "campaigns": campaigns,
        "posts": posts,
        "escrows": escrows,
        "revenue": 69800 + users * 100,
        "uptime": "99.97%",
        "timestamp": now_iso(),
    }


@app.get("/api/analytics/weekly")
def api_analytics_weekly():
    # Mock weekly data
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return {
        "status": "success",
        "labels": days,
        "users": [random.randint(50, 200) for _ in days],
        "revenue": [random.randint(1000, 5000) for _ in days],
        "campaigns": [random.randint(5, 30) for _ in days],
    }


# ============================================================
# SECTION 31: SEARCH
# ============================================================
@app.get("/api/search")
def api_search(q: str = Query(..., min_length=2)):
    conn = get_db()
    pattern = f"%{q}%"

    users = conn.execute(
        "SELECT id, full_name, user_type, trust_score FROM users WHERE full_name LIKE ? LIMIT 10",
        (pattern,)
    ).fetchall()

    campaigns = conn.execute(
        "SELECT id, title, budget, status FROM campaigns WHERE title LIKE ? OR description LIKE ? LIMIT 10",
        (pattern, pattern)
    ).fetchall()

    posts = conn.execute(
        "SELECT id, user_name, content FROM posts WHERE content LIKE ? LIMIT 10",
        (pattern,)
    ).fetchall()

    conn.close()

    return {
        "status": "success",
        "query": q,
        "users": rows_to_list(users),
        "campaigns": rows_to_list(campaigns),
        "posts": rows_to_list(posts),
    }


# ============================================================
# SECTION 32: ACTIVITY LOG
# ============================================================
@app.get("/api/activity")
def api_activity(user: Dict = Depends(require_user), limit: int = 50):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM activity_logs WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user["id"], limit)
    ).fetchall()
    conn.close()
    return rows_to_list(rows)


# ============================================================
# SECTION 33: TRANSACTIONS
# ============================================================
@app.get("/api/transactions")
def api_transactions(user: Dict = Depends(require_user)):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 50",
        (user["id"],)
    ).fetchall()
    conn.close()
    return rows_to_list(rows)


@app.post("/api/transactions")
async def api_transaction_create(request: Request, user: Dict = Depends(require_user)):
    form = await request.form()
    amount = form.get("amount")
    type_ = form.get("type", "payment")
    description = form.get("description", "")

    if not amount:
        raise HTTPException(status_code=400, detail="Amount required")

    ref = f"TX-{uuid.uuid4().hex[:12].upper()}"
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO transactions (user_id, amount, type, description, reference, status)
           VALUES (?, ?, ?, ?, ?, 'completed')""",
        (user["id"], float(amount), type_, description, ref)
    )
    conn.commit()
    tx_id = cur.lastrowid
    conn.close()

    return {"status": "success", "transaction_id": tx_id, "reference": ref}


# ============================================================
# SECTION 34: SUBSCRIPTIONS
# ============================================================
@app.get("/api/subscription")
def api_subscription(user: Dict = Depends(require_user)):
    conn = get_db()
    sub = conn.execute(
        "SELECT * FROM subscriptions WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (user["id"],)
    ).fetchone()
    conn.close()
    if not sub:
        return {"status": "success", "plan": "free", "status": "active"}
    return {"status": "success", **dict(sub)}


@app.post("/api/subscription/upgrade")
async def api_subscription_upgrade(request: Request, user: Dict = Depends(require_user)):
    form = await request.form()
    plan = form.get("plan", "pro")
    prices = {"pro": 29, "business": 99, "enterprise": 499}
    price = prices.get(plan, 29)

    conn = get_db()
    conn.execute(
        """INSERT INTO subscriptions (user_id, plan, status, expires_at)
           VALUES (?, ?, 'active', ?)""",
        (user["id"], plan, (datetime.utcnow() + timedelta(days=30)).isoformat())
    )
    conn.execute(
        """INSERT INTO transactions (user_id, amount, type, description, status)
           VALUES (?, ?, 'subscription', ?, 'completed')""",
        (user["id"], price, f"Upgrade to {plan}")
    )
    conn.commit()
    conn.close()

    add_notification(user["id"], "success", f"🎉 {plan.title()} faollashtirildi!",
                    f"Siz {plan} tarifiga o'tdingiz. 30 kun amal qiladi.", "/dashboard")

    return {"status": "success", "plan": plan, "expires_in_days": 30}


# ============================================================
# SECTION 35: REPORTS
# ============================================================
@app.post("/api/reports")
async def api_report_create(request: Request, user: Dict = Depends(require_user)):
    form = await request.form()
    target_type = form.get("target_type")
    target_id = form.get("target_id")
    reason = form.get("reason", "")

    conn = get_db()
    conn.execute(
        "INSERT INTO reports (reporter_id, target_type, target_id, reason) VALUES (?, ?, ?, ?)",
        (user["id"], target_type, int(target_id) if target_id else None, reason)
    )
    conn.commit()
    conn.close()
    return {"status": "success", "message": "Report submitted"}


# ============================================================
# SECTION 36: EXPORT
# ============================================================
@app.get("/api/export/users.csv")
def api_export_users_csv(user: Dict = Depends(require_admin)):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, full_name, email, user_type, trust_score, xp, level, created_at FROM users"
    ).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Full Name", "Email", "Type", "Trust Score", "XP", "Level", "Created"])
    for r in rows:
        writer.writerow([r["id"], r["full_name"], r["email"], r["user_type"],
                        r["trust_score"], r["xp"], r["level"], r["created_at"]])

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=users.csv"}
    )


@app.get("/api/export/data.json")
def api_export_data_json(user: Dict = Depends(require_user)):
    conn = get_db()
    data = {
        "user": public_user(dict(conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone())),
        "tasks": rows_to_list(conn.execute("SELECT * FROM tasks WHERE user_id = ?", (user["id"],)).fetchall()),
        "posts": rows_to_list(conn.execute("SELECT * FROM posts WHERE user_id = ?", (user["id"],)).fetchall()),
        "notifications": rows_to_list(conn.execute("SELECT * FROM notifications WHERE user_id = ?", (user["id"],)).fetchall()),
        "achievements": rows_to_list(conn.execute(
            """SELECT a.* FROM achievements a JOIN user_achievements ua ON ua.achievement_id = a.id
               WHERE ua.user_id = ?""", (user["id"],)
        ).fetchall()),
    }
    conn.close()
    return data


# ============================================================
# SECTION 37: ADMIN
# ============================================================
@app.get("/api/admin/users")
def api_admin_users(user: Dict = Depends(require_admin), limit: int = 100):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, full_name, email, user_type, trust_score, xp, level, is_active, created_at FROM users ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return rows_to_list(rows)


@app.post("/api/admin/users/{user_id}/toggle")
def api_admin_toggle_user(user_id: int, user: Dict = Depends(require_admin)):
    conn = get_db()
    row = conn.execute("SELECT is_active FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")
    new_state = 0 if row["is_active"] else 1
    conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (new_state, user_id))
    conn.commit()
    conn.close()
    return {"status": "success", "is_active": new_state}


# ============================================================
# SECTION 38: WEBSOCKET
# ============================================================
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    await ws_manager.connect(user_id, websocket)
    try:
        await websocket.send_json({"type": "connected", "user_id": user_id})
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                elif msg.get("type") == "message":
                    to_user = msg.get("to")
                    content = msg.get("content", "")
                    if to_user and content:
                        # Save to DB
                        conn = get_db()
                        conn.execute(
                            "INSERT INTO messages (sender_id, receiver_id, content) VALUES (?, ?, ?)",
                            (user_id, to_user, content)
                        )
                        conn.commit()
                        conn.close()
                        # Forward
                        await ws_manager.send_to_user(to_user, {
                            "type": "message",
                            "from": user_id,
                            "content": content,
                            "timestamp": now_iso(),
                        })
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(user_id, websocket)
    except Exception as e:
        logger.warning(f"WS error: {e}")
        ws_manager.disconnect(user_id, websocket)


# ============================================================
# SECTION 39: MESSAGES
# ============================================================
@app.get("/api/messages/{other_user_id}")
def api_messages_get(other_user_id: int, user: Dict = Depends(require_user)):
    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM messages
           WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
           ORDER BY id ASC LIMIT 200""",
        (user["id"], other_user_id, other_user_id, user["id"])
    ).fetchall()
    conn.execute(
        "UPDATE messages SET is_read = 1 WHERE sender_id = ? AND receiver_id = ?",
        (other_user_id, user["id"])
    )
    conn.commit()
    conn.close()
    return rows_to_list(rows)


@app.post("/api/messages/{other_user_id}")
async def api_messages_send(other_user_id: int, request: Request, user: Dict = Depends(require_user)):
    form = await request.form()
    content = form.get("content")
    if not content:
        raise HTTPException(status_code=400, detail="Content required")

    conn = get_db()
    conn.execute(
        "INSERT INTO messages (sender_id, receiver_id, content) VALUES (?, ?, ?)",
        (user["id"], other_user_id, content)
    )
    conn.commit()
    conn.close()

    await ws_manager.send_to_user(other_user_id, {
        "type": "message",
        "from": user["id"],
        "content": content,
        "timestamp": now_iso(),
    })
    return {"status": "success"}


# ============================================================
# SECTION 40: QR CODE (generate)
# ============================================================
@app.get("/api/qr")
def api_qr(data: str = Query(...)):
    url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={data}"
    return RedirectResponse(url)


# ============================================================
# SECTION 41: BACKUP
# ============================================================
@app.post("/api/backup")
def api_backup(user: Dict = Depends(require_admin)):
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"ercors_{timestamp}.db"
    import shutil
    shutil.copy2(DB_PATH, backup_path)
    return {"status": "success", "backup": str(backup_path)}


# ============================================================
# SECTION 42: STATIC & ERRORS
# ============================================================
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/exports", StaticFiles(directory=str(EXPORT_DIR)), name="exports")


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=404, content={"status": "error", "message": "Endpoint not found"})
    index_path = BASE_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    return JSONResponse(status_code=404, content={"status": "error", "message": "Not found"})


@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    logger.error(f"Server error: {exc}")
    return JSONResponse(status_code=500, content={"status": "error", "message": "Internal server error"})


# ============================================================
# SECTION 43: MAIN
# ============================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
        access_log=True,
    )
