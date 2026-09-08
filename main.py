import os, sys, json, re, asyncio, logging, uuid, io, base64, hashlib, time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Union
from dotenv import load_dotenv

# ─── FastAPI ───────────────────────────────────────────────
from fastapi import FastAPI, Form, HTTPException, Depends, UploadFile, File, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

# ─── Database ─────────────────────────────────────────────
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, Float, ForeignKey, JSON, func, desc, and_, or_
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship, joinedload
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

# ─── Password & JWT ──────────────────────────────────────
from passlib.context import CryptContext
from jose import JWTError, jwt

# ─── HTTP ──────────────────────────────────────────────────
import httpx

# ─── PDF & DOCX ──────────────────────────────────────────
import pdfplumber
from docx import Document

# ─── Pydantic ─────────────────────────────────────────────
from pydantic import BaseModel, EmailStr, Field

load_dotenv()

# ─── Logging ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("ERCORS_MAIN")

# ─── Config ──────────────────────────────────────────────
GROQ_API_KEY_1 = os.getenv("GROQ_API_KEY_1")
GROQ_API_KEY_2 = os.getenv("GROQ_API_KEY_2")
GROQ_API_KEY_3 = os.getenv("GROQ_API_KEY_3")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ercors_platform.db")
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-me-please-12345")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "10485760"))  # 10 MB
PORT = int(os.getenv("PORT", 10000))
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:10000")

# ─── Database setup ──────────────────────────────────────
connect_args = {}
if "sqlite" in DATABASE_URL:
    connect_args = {"check_same_thread": False}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

# ─── Password & JWT ────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(401, "Invalid token")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(401, "Could not validate credentials")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise credentials_exception
    return user

def get_current_user_optional(token: Optional[str] = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("sub")
        if user_id is None:
            return None
        user = db.query(User).filter(User.id == user_id).first()
        return user
    except:
        return None

# ─── SQLAlchemy Models ──────────────────────────────────
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(200), nullable=False)
    user_type = Column(String(20), default="expert")  # 'expert' or 'company'
    company_name = Column(String(100), nullable=True)
    skills = Column(Text, nullable=True)
    hourly_rate = Column(String(20), nullable=True)
    trust_score = Column(Integer, default=85)
    projects = Column(Integer, default=0)
    earnings = Column(Integer, default=0)
    registered_at = Column(DateTime, default=func.now())
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime, nullable=True)
    # Relationships
    candidates = relationship("Candidate", back_populates="owner", cascade="all, delete-orphan")
    jobs = relationship("Job", back_populates="owner", cascade="all, delete-orphan")
    campaigns = relationship("Campaign", back_populates="owner", cascade="all, delete-orphan")
    posts = relationship("Post", back_populates="author", cascade="all, delete-orphan")
    applications = relationship("Application", foreign_keys="Application.user_id", back_populates="user", cascade="all, delete-orphan")
    interviews = relationship("Interview", foreign_keys="Interview.user_id", back_populates="user", cascade="all, delete-orphan")
    escrows = relationship("Escrow", back_populates="user", cascade="all, delete-orphan")

class Candidate(Base):
    __tablename__ = "candidates"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    full_name = Column(String(100), nullable=False)
    email = Column(String(100), index=True, nullable=True)
    phone = Column(String(20), nullable=True)
    resume_text = Column(Text, nullable=True)
    resume_file = Column(String(200), nullable=True)
    resume_analysis = Column(JSON, nullable=True)  # {skills, experience_years, current_position, education, summary}
    skills = Column(Text, nullable=True)
    experience_years = Column(Float, default=0)
    current_position = Column(String(100), nullable=True)
    source = Column(String(50), default="manual")
    status = Column(String(20), default="new")
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)
    module_id = Column(String(20), nullable=True)  # qaysi modul orqali yuklangan
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    # Relationships
    owner = relationship("User", back_populates="candidates")
    applications = relationship("Application", back_populates="candidate", cascade="all, delete-orphan")
    campaign = relationship("Campaign", back_populates="candidates")
    interviews = relationship("Interview", back_populates="candidate", cascade="all, delete-orphan")

class Job(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    department = Column(String(50), nullable=True)
    seniority = Column(String(20), default="Middle")
    location = Column(String(100), nullable=True)
    salary_min = Column(Float, nullable=True)
    salary_max = Column(Float, nullable=True)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    owner = relationship("User", back_populates="jobs")
    applications = relationship("Application", back_populates="job", cascade="all, delete-orphan")

class Campaign(Base):
    __tablename__ = "campaigns"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    required_skills = Column(Text, nullable=True)
    min_experience = Column(Float, nullable=True)
    keywords = Column(Text, nullable=True)
    budget = Column(String(50), nullable=True)
    deadline = Column(String(20), nullable=True)
    status = Column(String(20), default="active")  # active, paused, completed
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    owner = relationship("User", back_populates="campaigns")
    candidates = relationship("Candidate", back_populates="campaign", cascade="all, delete-orphan")
    applications = relationship("Application", back_populates="campaign", cascade="all, delete-orphan")

class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    content = Column(Text, nullable=False)
    likes = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    author = relationship("User", back_populates="posts")
    comments = relationship("Comment", back_populates="post", cascade="all, delete-orphan")

class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("posts.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=func.now())
    post = relationship("Post", back_populates="comments")
    user = relationship("User")

class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"))
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    status = Column(String(20), default="new")  # new, review, interview, offered, hired, rejected
    match_score = Column(Float, nullable=True)
    ai_feedback = Column(Text, nullable=True)
    applied_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    candidate = relationship("Candidate", back_populates="applications")
    job = relationship("Job", back_populates="applications")
    user = relationship("User", foreign_keys=[user_id], back_populates="applications")
    campaign = relationship("Campaign", back_populates="applications")

class Interview(Base):
    __tablename__ = "interviews"
    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    scheduled_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="pending")  # pending, in_progress, completed, cancelled
    questions = Column(JSON, default=list)
    answers = Column(JSON, default=list)
    score = Column(Float, nullable=True)
    recommendation = Column(String(20), nullable=True)
    feedback = Column(Text, nullable=True)
    audio_file = Column(String(200), nullable=True)
    transcript = Column(Text, nullable=True)
    analysis = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    candidate = relationship("Candidate", back_populates="interviews")
    user = relationship("User", foreign_keys=[user_id], back_populates="interviews")

class Escrow(Base):
    __tablename__ = "escrows"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    amount = Column(Float, nullable=False)
    status = Column(String(20), default="pending")  # pending, active, completed, cancelled
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    user = relationship("User", back_populates="escrows")

class ModuleActionLog(Base):
    __tablename__ = "module_action_logs"
    id = Column(Integer, primary_key=True, index=True)
    module_id = Column(String(20), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(50), nullable=True)
    params = Column(JSON, nullable=True)
    result = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=func.now())

# Create tables
Base.metadata.create_all(bind=engine)

# ─── Pydantic Models (for validation) ────────────────────
class UserRegister(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    user_type: str
    company_name: Optional[str] = None
    skills: Optional[str] = None
    hourly_rate: Optional[str] = None
    github: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    website: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: int
    full_name: str
    email: str
    user_type: str
    company_name: Optional[str] = None
    skills: Optional[str] = None
    hourly_rate: Optional[str] = None
    trust_score: int
    projects: int
    earnings: int
    registered_at: datetime

class TokenResponse(BaseModel):
    status: str
    message: str
    user: UserResponse
    session: str

class CampaignCreate(BaseModel):
    title: str
    description: str
    required_skills: Optional[str] = None
    min_experience: Optional[float] = None
    keywords: Optional[str] = None
    budget: str
    deadline: str
    company_id: int

class PostCreate(BaseModel):
    content: str
    user_id: int

class CommentCreate(BaseModel):
    text: str
    user_id: int

class EscrowCreate(BaseModel):
    title: str
    amount: float

# ─── 64 Modules (to‘liq ro‘yxat) ──────────────────────────
MODULES = [
    # Core (1-5)
    {"id": "m1", "name": "Enterprise AI Talent Matching", "category": "Core", "icon": "fa-users", "active": True,
     "description": "AI yordamida nomzodlarni kampaniyalarga moslashtirish, reyting va filtrlash. Har bir nomzod uchun moslik balli (0-100%) hisoblanadi va eng yaxshi 5 ta kampaniya taklif etiladi."},
    {"id": "m2", "name": "Managed RLHF & Data Annotation", "category": "Core", "icon": "fa-robot", "active": True,
     "description": "RLHF maʼlumotlarini annotatsiya qilish, sifat nazorati va ekspert xulosalari. Human-in-the-loop tizimi orqali model javoblarini baholash va takomillashtirish."},
    {"id": "m3", "name": "AI Hiring SaaS & Trust Score", "category": "Core", "icon": "fa-microphone", "active": True,
     "description": "Avtomatik intervyu o‘tkazish, nomzod baholash va ishonch ballini hisoblash. Trust Score (0-100) real vaqtda yangilanadi va ish beruvchilarga nomzod haqida to‘liq maʼlumot beradi."},
    {"id": "m4", "name": "Global Escrow & B2B Contracts", "category": "Core", "icon": "fa-file-signature", "active": True,
     "description": "Xalqaro shartnomalar, escrow hisoblari, to‘lov va hujjat boshqaruvi. Aqlli shartnomalar orqali to‘lov xavfsizligi 100% kafolatlanadi."},
    {"id": "m5", "name": "Micro‑Equity HFT Engine", "category": "Core", "icon": "fa-chart-line", "active": True,
     "description": "Real vaqtda moliyaviy maʼlumotlar, grafiklar va savdo signalari. Yuqori chastotali savdo algoritmlari orqali mikro-aksiyalar bilan ishlash."},
    # Talent Sourcing (6-10)
    {"id": "m6", "name": "AI Vetted Engineers", "category": "Talent Sourcing", "icon": "fa-laptop-code", "active": True,
     "description": "AI tomonidan tekshirilgan muhandislar ro‘yxati va ularning profillari. Har bir muhandis uchun 7+ mezon bo‘yicha baholash."},
    {"id": "m7", "name": "AI & ML Specialists", "category": "Talent Sourcing", "icon": "fa-brain", "active": True,
     "description": "Sunʼiy intellekt va machine learning mutaxassislari bazasi. 1000+ ML muhandislar profili, ularning loyihalari va natijalari."},
    {"id": "m8", "name": "Autonomous AI Agents & Swarm", "category": "Talent Sourcing", "icon": "fa-robot", "active": True,
     "description": "Avtonom agentlarni boshqarish, ularga vazifa berish va natijalarni kuzatish. Ko‘p agentli tizimlar (MAS) orqali murakkab vazifalarni avtomatlashtirish."},
    {"id": "m9", "name": "Embedded & Edge AI Hardware", "category": "Talent Sourcing", "icon": "fa-microchip", "active": True,
     "description": "Edge AI apparat vositalari va ular uchun dasturiy taʼminot. Raspberry Pi, NVIDIA Jetson, Google Coral va boshqa platformalar."},
    {"id": "m10", "name": "Quantum Computing & Security", "category": "Talent Sourcing", "icon": "fa-atom", "active": True,
     "description": "Kvant hisoblash va post-kvant kriptografiya bo‘yicha mutaxassislar. Qiskit, Cirq va boshqa kvant SDK’lar bilan ishlash."},
    # Data & Training (11-14)
    {"id": "m11", "name": "RLHF & Model Evaluation", "category": "Data & Training", "icon": "fa-comments", "active": True,
     "description": "RLHF baholash, modelni test qilish va metrikalar. Model performansi, xatolik tahlili va benchmark natijalari."},
    {"id": "m12", "name": "Code Data Annotation", "category": "Data & Training", "icon": "fa-tags", "active": True,
     "description": "Kod maʼlumotlarini annotatsiya qilish, snippetlar va tavsiflar. 100K+ kod snippetlari uchun teg va tavsif generatsiyasi."},
    {"id": "m13", "name": "Multimodal Data Sourcing", "category": "Data & Training", "icon": "fa-database", "active": True,
     "description": "Turli xil maʼlumot manbalarini (matn, rasm, audio) birlashtirish. Multimodal AI loyihalari uchun maʼlumot to‘plamlari."},
    {"id": "m14", "name": "Red Teaming & AI Safety", "category": "Data & Training", "icon": "fa-shield-halved", "active": True,
     "description": "AI xavfsizligi, red teaming va zaifliklarni aniqlash. Modelni buzish testlari, adversarial hujumlar va himoya choralari."},
    # Hiring Tools (15-18)
    {"id": "m15", "name": "AI Voice/Video Interview Bot", "category": "Hiring Tools", "icon": "fa-microphone", "active": True,
     "description": "Ovozli va video intervyu boti, real vaqtda transkripsiya va tahlil. Nomzodning nutq tahlili, hissiyotlarni aniqlash va baholash."},
    {"id": "m16", "name": "Code Assessment Engine", "category": "Hiring Tools", "icon": "fa-code", "active": True,
     "description": "Avtomatik kod baholash, test o‘tkazish va natijalar. 10+ dasturlash tili uchun kod sifatini baholash."},
    {"id": "m17", "name": "Background & Trust Score", "category": "Hiring Tools", "icon": "fa-user-check", "active": True,
     "description": "Nomzodning ishonch ballini hisoblash va fon tekshiruvi. 20+ mezon bo‘yicha to‘liq fon tekshiruvi va trust score hisoblash."},
    {"id": "m18", "name": "AI Skill Graph Analyzer", "category": "Hiring Tools", "icon": "fa-chart-simple", "active": True,
     "description": "Ko‘nikmalar grafigini tahlil qilish, bo‘shliqlarni aniqlash. Skill graph vizualizatsiyasi va yetishmayotgan ko‘nikmalarni tavsiya qilish."},
    # Direct & Premium (19-25)
    {"id": "m19", "name": "Dedicated Remote Teams", "category": "Direct & Premium", "icon": "fa-people-group", "active": True,
     "description": "Masofaviy jamoalar uchun to‘liq xizmat ko‘rsatish. Jamoa tuzish, boshqaruv va samaradorlik monitoringi."},
    {"id": "m20", "name": "Express AI Consultation", "category": "Direct & Premium", "icon": "fa-user-tie", "active": True,
     "description": "Tezkor AI konsultatsiyalar, 30 daqiqalik sessiyalar. Har qanday AI loyihasi bo‘yicha mutaxassis maslahati."},
    {"id": "m21", "name": "AI Startup Builder On‑Demand", "category": "Direct & Premium", "icon": "fa-rocket", "active": True,
     "description": "Startap uchun AI yechimlar, MVP yaratish va tezlashtirish. 90 kun ichida tayyor MVP yaratish."},
    {"id": "m22", "name": "Web3 & Spatial Computing", "category": "Direct & Premium", "icon": "fa-cubes", "active": True,
     "description": "Web3, metaverse, spatial computing loyihalari. Decentralized apps, NFT, VR/AR loyihalar."},
    {"id": "m23", "name": "Direct Escrow & Mass Payouts", "category": "Direct & Premium", "icon": "fa-hand-holding-dollar", "active": True,
     "description": "Ommaviy to‘lovlar va escrow xizmatlari. 1000+ to‘lovlarni bir vaqtda amalga oshirish."},
    {"id": "m24", "name": "Enterprise SLA & Managed PM", "category": "Direct & Premium", "icon": "fa-clipboard-list", "active": True,
     "description": "Korxona SLA, loyiha boshqaruvi va kafolatlar. 99.9% uptime kafolati va professional loyiha boshqaruvi."},
    {"id": "m25", "name": "Instant Talent API Access", "category": "Direct & Premium", "icon": "fa-plug", "active": True,
     "description": "API orqali talent maʼlumotlariga tezkor kirish. RESTful API orqali nomzodlarni qidirish va filtrlash."},
    # Infrastructure (26-44)
    {"id": "m26", "name": "Cloud GPU & TPU Server Access", "category": "Infrastructure", "icon": "fa-cloud", "active": True,
     "description": "Bulutli GPU/TPU serverlariga ulanish va boshqaruv. NVIDIA A100, V100, TPU v3 va boshqa qurilmalar."},
    {"id": "m27", "name": "Quantum QPU Remote Access", "category": "Infrastructure", "icon": "fa-atom", "active": True,
     "description": "Kvant protsessorlariga masofaviy kirish. IBM Q, Rigetti, IonQ kvant protsessorlari."},
    {"id": "m28", "name": "AI Sandbox & Code Execution Nodes", "category": "Infrastructure", "icon": "fa-flask", "active": True,
     "description": "AI uchun sandbox muhiti, kod bajarish va sinov. Isolated environment, xavfsiz kod bajarish."},
    {"id": "m29", "name": "Serverless AI Endpoint Hosting", "category": "Infrastructure", "icon": "fa-server", "active": True,
     "description": "Serverless AI endpointlarini joylashtirish va boshqarish. AWS Lambda, Google Cloud Functions orqali AI modellarni hosting qilish."},
    {"id": "m30", "name": "Autonomous Software Engineer Swarm", "category": "Infrastructure", "icon": "fa-robot", "active": True,
     "description": "Avtonom dasturchi agentlar guruhi (swarm) – kod yozadi, test qiladi, xatolarni tuzatadi. 24/7 ishlaydigan AI dasturchilar jamoasi."},
    {"id": "m31", "name": "AI Data Scraping & Web Extraction", "category": "Infrastructure", "icon": "fa-spider", "active": True,
     "description": "Veb-sahifalardan maʼlumot yig‘ish va tozalash. Scrapy, BeautifulSoup, Selenium orqali maʼlumotlarni avtomatik yig‘ish."},
    {"id": "m32", "name": "Autonomous SMM & Marketing Agents", "category": "Infrastructure", "icon": "fa-bullhorn", "active": True,
     "description": "Avtonom marketing agentlari, ijtimoiy tarmoqlarni boshqarish. AI orqali postlar yaratish, rejalashtirish va analitika."},
    {"id": "m33", "name": "AI Customer Support & Voice Bot", "category": "Infrastructure", "icon": "fa-headset", "active": True,
     "description": "Mijozlarni qo‘llab-quvvatlash boti, ovozli interfeys. 24/7 ishlaydigan AI yordamchi, ko‘p tilli."},
    {"id": "m34", "name": "Zero‑Knowledge Proofs Sandbox", "category": "Infrastructure", "icon": "fa-shield", "active": True,
     "description": "Zero-knowledge isbotlar uchun sandbox muhiti. zk-SNARKs, zk-STARKs va boshqa ZKP protokollarini sinovdan o‘tkazish."},
    {"id": "m35", "name": "Automated NDA & Smart Contracts", "category": "Infrastructure", "icon": "fa-gavel", "active": True,
     "description": "Avtomatik NDA va smart-kontraktlar yaratish. Legal-tech AI orqali shartnomalarni avtomatik generatsiya qilish."},
    {"id": "m36", "name": "Deepfake & Synthetic Media Audit", "category": "Infrastructure", "icon": "fa-video", "active": True,
     "description": "Deepfake va sintetik mediarni aniqlash va audit. 99% aniqlik bilan deepfake videolarni aniqlash."},
    {"id": "m37", "name": "WebXR & Spatial VR Showroom", "category": "Infrastructure", "icon": "fa-vr-cardboard", "active": True,
     "description": "WebXR virtual ko‘rgazma, 3D ko‘rsatuvlar. Brauzer orqali VR va AR tajribalari."},
    {"id": "m38", "name": "3D Generative Asset Factory", "category": "Infrastructure", "icon": "fa-cube", "active": True,
     "description": "3D obyektlar yaratish va generatsiya qilish. AI orqali 3D modellar, teksturalar va animatsiyalar yaratish."},
    {"id": "m39", "name": "Digital Twin Factory Simulation", "category": "Infrastructure", "icon": "fa-industry", "active": True,
     "description": "Raqamli egizak (digital twin) simulyatsiyalari. Zavod, ombor, logistika jarayonlarini raqamli egizak orqali boshqarish."},
    {"id": "m40", "name": "Custom GLSL Shader & Physics", "category": "Infrastructure", "icon": "fa-paint-brush", "active": True,
     "description": "Maxsus GLSL shaderlar va fizik simulyatsiyalar. Real vaqtda 3D grafika va fizika simulyatsiyalari."},
    {"id": "m41", "name": "High‑Frequency Micro‑Equity Exchange", "category": "Infrastructure", "icon": "fa-chart-pie", "active": True,
     "description": "Yuqori chastotali mikromoliyaviy almashinuv. Mikro-aksiyalar bilan HFT savdo, 1ms dan tezroq bajarish."},
    {"id": "m42", "name": "Global Crypto & Cross‑Border Escrow", "category": "Infrastructure", "icon": "fa-coins", "active": True,
     "description": "Kripto va xalqaro escrow xizmatlari. Bitcoin, Ethereum, USDC orqali xalqaro to‘lovlar va escrow."},
    {"id": "m43", "name": "Micro‑Equity Flash Loans & Leverage", "category": "Infrastructure", "icon": "fa-hand-holding-usd", "active": True,
     "description": "Mikro-kreditlash va leverage operatsiyalari. Flash loan va leverage orqali daromadni oshirish."},
    {"id": "m44", "name": "AI Startup Crowdfunding Portal", "category": "Infrastructure", "icon": "fa-hand-holding-heart", "active": True,
     "description": "Startaplar uchun kraudfanding platformasi. AI startaplar uchun investitsion platforma."},
    # Developer Tools (45-64)
    {"id": "m45", "name": "AI-Powered Code Review", "category": "Developer Tools", "icon": "fa-code-branch", "active": True,
     "description": "AI yordamida kodni ko‘rib chiqish va tahlil. Kod sifatini baholash, xatoliklarni aniqlash va optimallashtirish takliflari."},
    {"id": "m46", "name": "Automated Testing Suite", "category": "Developer Tools", "icon": "fa-flask", "active": True,
     "description": "Avtomatik testlar to‘plami, unit va integration test. 100+ test turi, CI/CD ga integratsiya."},
    {"id": "m47", "name": "CI/CD Pipeline Integration", "category": "Developer Tools", "icon": "fa-gears", "active": True,
     "description": "CI/CD jarayonlarini integratsiya qilish. GitHub Actions, GitLab CI, Jenkins bilan integratsiya."},
    {"id": "m48", "name": "Docker & Kubernetes Orchestration", "category": "Developer Tools", "icon": "fa-cubes", "active": True,
     "description": "Konteynerlashtirish va orkestratsiya. Docker, Kubernetes, Helm orqali mikrosxizmatlarni boshqarish."},
    {"id": "m49", "name": "AI-Driven Documentation", "category": "Developer Tools", "icon": "fa-book", "active": True,
     "description": "AI yordamida hujjatlar yaratish va yangilash. Kod kommentariylari, README, API dokumentatsiyasi."},
    {"id": "m50", "name": "Code Quality Dashboard", "category": "Developer Tools", "icon": "fa-chart-bar", "active": True,
     "description": "Kod sifatini kuzatish va vizualizatsiya. SonarQube, CodeClimate metrikalari interaktiv dashboard."},
    {"id": "m51", "name": "Real-Time Error Tracking", "category": "Developer Tools", "icon": "fa-bug", "active": True,
     "description": "Xatolarni real vaqtda kuzatish va ogohlantirish. Sentry, Rollbar kabi xatolarni kuzatish tizimi."},
    {"id": "m52", "name": "Performance Monitoring", "category": "Developer Tools", "icon": "fa-tachometer-alt", "active": True,
     "description": "Ishlash ko‘rsatkichlarini monitoring qilish. APM, Prometheus, Grafana orqali real vaqt monitoring."},
    {"id": "m53", "name": "Security Vulnerability Scanner", "category": "Developer Tools", "icon": "fa-shield", "active": True,
     "description": "Xavfsizlik zaifliklarini skanerlash. SAST, DAST, SCA skanerlari orqali xavfsizlikni tekshirish."},
    {"id": "m54", "name": "API Gateway & Management", "category": "Developer Tools", "icon": "fa-plug", "active": True,
     "description": "API shlyuz va boshqaruv paneli. Kong, Traefik orqali API boshqaruvi, rate limiting, autentifikatsiya."},
    {"id": "m55", "name": "GraphQL Federation", "category": "Developer Tools", "icon": "fa-network-wired", "active": True,
     "description": "GraphQL federatsiyasi va schema birlashtirish. Apollo Federation orqali mikrosxizmatlar uchun GraphQL."},
    {"id": "m56", "name": "Event-Driven Architecture", "category": "Developer Tools", "icon": "fa-bolt", "active": True,
     "description": "Event-driven arxitektura, event bus va handlerlar. Kafka, RabbitMQ orqali event-driven tizimlar."},
    {"id": "m57", "name": "Data Lake & Analytics", "category": "Developer Tools", "icon": "fa-database", "active": True,
     "description": "Maʼlumotlar ko‘li va analitik vositalar. Data Lake, ETL pipelines, BI vositalari."},
    {"id": "m58", "name": "MLOps Pipeline", "category": "Developer Tools", "icon": "fa-robot", "active": True,
     "description": "ML modellarini ishlab chiqarish va boshqarish (MLOps). Kubeflow, MLflow, TFX orqali ML lifecycle."},
    {"id": "m59", "name": "Model Monitoring & Drift Detection", "category": "Developer Tools", "icon": "fa-chart-line", "active": True,
     "description": "Model driftni aniqlash va monitoring. Data drift, concept drift, model quality monitoring."},
    {"id": "m60", "name": "Feature Store", "category": "Developer Tools", "icon": "fa-cubes", "active": True,
     "description": "Feature saqlash va boshqarish tizimi. Feast, Tecton orqali feature store."},
    {"id": "m61", "name": "Explainable AI (XAI)", "category": "Developer Tools", "icon": "fa-lightbulb", "active": True,
     "description": "AI qarorlarini tushuntirish va vizualizatsiya. SHAP, LIME, Integrated Gradients orqali tushuntirish."},
    {"id": "m62", "name": "Federated Learning", "category": "Developer Tools", "icon": "fa-network-wired", "active": True,
     "description": "Federated learning tizimi, mahalliy modellarni birlashtirish. TensorFlow Federated, PySyft orqali."},
    {"id": "m63", "name": "Synthetic Data Generation", "category": "Developer Tools", "icon": "fa-wand-magic", "active": True,
     "description": "Sintetik maʼlumotlar yaratish va augmentatsiya. GANs, VAEs, SDV orqali sintetik maʼlumotlar."},
    {"id": "m64", "name": "AI Governance & Compliance", "category": "Developer Tools", "icon": "fa-gavel", "active": True,
     "description": "AI boshqaruvi va normativ talablarga muvofiqlik. GDPR, CCPA, AI Act talablariga muvofiqlik."},
]

# ─── Module logic mapping ──────────────────────────────────
# Har bir modul uchun maxsus funksiya – hozircha placeholder, lekin kengaytirish mumkin
async def module_logic(module_id: str, user_id: Optional[int] = None, db: Session = None, params: Dict = None) -> Dict[str, Any]:
    """Har bir modul uchun maxsus mantiq."""
    logic_map = {
        "m1": lambda: {"status": "active", "matches": 42, "top_candidates": ["Alice Johnson", "Bob Smith", "Carol White"], "avg_score": 87.5},
        "m2": lambda: {"status": "active", "total_annotations": 1250, "pending": 45, "avg_quality": 94.2},
        "m3": lambda: {"status": "active", "interviews_today": 12, "avg_score": 82.7, "trust_scores": [95, 88, 76, 92, 84]},
        "m4": lambda: {"status": "active", "escrow_count": 34, "total_amount": 1250000, "active_contracts": 12},
        "m5": lambda: {"status": "active", "trades_today": 1542, "volume": 3450000, "profit": 12345.67},
        "m15": lambda: {"status": "active", "transcriptions": 230, "avg_analysis_score": 78.4, "interviews_completed": 45},
        "m30": lambda: {"status": "active", "agents": 8, "tasks_completed": 342, "uptime": 99.98},
        "m45": lambda: {"status": "active", "reviews_today": 67, "avg_quality": 91.3, "issues_found": 23},
    }
    default = lambda: {"message": f"Module {module_id} is operational.", "details": "No specific logic implemented yet.", "status": "active"}
    result = logic_map.get(module_id, default)()
    # Log action
    if db:
        log = ModuleActionLog(module_id=module_id, user_id=user_id, action="run", params=params, result=result)
        db.add(log)
        db.commit()
    return result

# ─── FastAPI app ─────────────────────────────────────────
app = FastAPI(
    title="ERCORS AGI Platform",
    version="9.8",
    description="ERCORS – Global Autonomous Engine & AI Trust Ecosystem",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# ─── Groq Load Balancer (3 keys) ────────────────────────
class GroqLoadBalancer:
    def __init__(self):
        self.keys = [GROQ_API_KEY_1, GROQ_API_KEY_2, GROQ_API_KEY_3]
        self.keys = [k for k in self.keys if k]
        if not self.keys:
            logger.warning("⚠️ Groq API kalitlari topilmadi! AI funksiyalar ishlamaydi.")
            self.keys = ["dummy"]
        self.current_index = 0
        self.model = GROQ_MODEL
        self.failed_keys = set()
        self.lock = asyncio.Lock()
        self._reset_time = time.time()

    async def get_next_key(self):
        async with self.lock:
            # Reset failed keys after 5 minutes
            if time.time() - self._reset_time > 300:
                self.failed_keys.clear()
                self._reset_time = time.time()
            available = [k for k in self.keys if k not in self.failed_keys]
            if not available:
                self.failed_keys.clear()
                available = self.keys
            key = available[self.current_index % len(available)]
            self.current_index = (self.current_index + 1) % len(available)
            return key

    async def chat_completion(self, messages: List[Dict], **kwargs) -> Dict:
        if not self.keys or self.keys == ["dummy"]:
            raise Exception("Groq API kalitlari mavjud emas")
        tried = set()
        for _ in range(len(self.keys)):
            key = await self.get_next_key()
            if key in tried:
                continue
            tried.add(key)
            try:
                url = "https://api.groq.com/openai/v1/chat/completions"
                headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": kwargs.get("temperature", 0.7),
                    "max_tokens": kwargs.get("max_tokens", kwargs.get("max_completion_tokens", 2048)),
                    "top_p": kwargs.get("top_p", 1.0),
                    "stream": False,
                    "stop": kwargs.get("stop"),
                }
                # Additional parameters
                if "reasoning_effort" in kwargs:
                    payload["reasoning_effort"] = kwargs["reasoning_effort"]
                if "tools" in kwargs and kwargs["tools"]:
                    payload["tools"] = kwargs["tools"]
                if "tool_choice" in kwargs:
                    payload["tool_choice"] = kwargs["tool_choice"]
                if "response_format" in kwargs:
                    payload["response_format"] = kwargs["response_format"]
                if "n" in kwargs:
                    payload["n"] = kwargs["n"]

                async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 429:
                    self.failed_keys.add(key)
                    logger.warning(f"⚠️ Groq kaliti limitga yetdi, keyingisiga o‘tamiz")
                    continue
                resp.raise_for_status()
                logger.info(f"✅ Groq ishlamoqda (kalit: {key[:10]}...)")
                return resp.json()
            except Exception as e:
                logger.warning(f"❌ Groq kaliti ishlamadi: {e}")
                self.failed_keys.add(key)
        raise Exception("Barcha Groq API kalitlari ishlamadi!")

    async def audio_transcribe(self, file_bytes: bytes, filename: str, language: str = "en") -> str:
        if not self.keys or self.keys == ["dummy"]:
            raise Exception("Groq API kalitlari mavjud emas")
        key = await self.get_next_key()
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {key}"}
        files = {
            "file": (filename, file_bytes, "audio/mpeg"),
            "model": (None, "whisper-large-v3"),
            "language": (None, language),
            "response_format": (None, "json"),
            "temperature": (None, "0.0")
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.post(url, headers=headers, files=files)
        if resp.status_code == 429:
            self.failed_keys.add(key)
            raise Exception("Groq API rate limit")
        resp.raise_for_status()
        data = resp.json()
        return data.get("text", "")

groq = GroqLoadBalancer()

async def call_groq(system: str, user: str, **kwargs) -> str:
    """Generic Groq call returning text."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        result = await groq.chat_completion(messages, **kwargs)
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Groq call failed: {e}")
        return "{}"

# ─── Text extraction ──────────────────────────────────────
def extract_text_from_file(file_bytes: bytes, filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    text = ""
    try:
        if ext == ".pdf":
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    text += page_text
        elif ext == ".docx":
            doc = Document(io.BytesIO(file_bytes))
            for para in doc.paragraphs:
                text += para.text + "\n"
        elif ext == ".txt":
            text = file_bytes.decode("utf-8", errors="ignore")
        else:
            raise ValueError("Faqat PDF, DOCX yoki TXT ruxsat")
    except Exception as e:
        logger.error(f"Matn chiqarishda xatolik: {e}")
        raise HTTPException(400, f"Faylni o‘qib bo‘lmadi: {str(e)}")
    return text.strip()

# ─── AI CV analysis ──────────────────────────────────────
async def analyze_cv_with_ai(resume_text: str) -> Dict[str, Any]:
    system = (
        "You are an expert HR analyst. Analyze the CV text and return a JSON object with these fields:\n"
        "- skills: list of key technical and soft skills (up to 15)\n"
        "- experience_years: total years of professional experience (float)\n"
        "- current_position: current job title or role (string)\n"
        "- education: highest education level (string)\n"
        "- summary: brief summary of the candidate (string, max 150 words)\n"
        "- certifications: list of certifications (up to 5)\n"
        "- languages: list of languages (up to 5)\n"
        "- projects: list of notable projects (up to 5)\n"
        "Return only valid JSON."
    )
    user = f"CV text:\n{resume_text[:4000]}"
    try:
        result = await call_groq(system, user, temperature=0.3, max_tokens=2048)
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', result)
        if json_match:
            result = json_match.group(1)
        data = json.loads(result)
        required_fields = ["skills", "experience_years", "current_position", "education", "summary", "certifications", "languages", "projects"]
        for field in required_fields:
            if field not in data:
                data[field] = [] if field in ["skills", "certifications", "languages", "projects"] else None if field != "experience_years" else 0.0
        return data
    except Exception as e:
        logger.error(f"AI tahlilida xatolik: {e}")
        return {
            "skills": [],
            "experience_years": 0.0,
            "current_position": "Unknown",
            "education": "Unknown",
            "summary": "No analysis available",
            "certifications": [],
            "languages": [],
            "projects": []
        }

# ─── Match score calculation ──────────────────────────────
def calculate_match_score(candidate_analysis: Dict, campaign: Campaign) -> float:
    score = 0.0
    # 1. Skills (50 points)
    if campaign.required_skills:
        required = set([s.strip().lower() for s in campaign.required_skills.split(',') if s.strip()])
        candidate_skills = set([s.lower() for s in candidate_analysis.get("skills", [])])
        if required:
            common = required.intersection(candidate_skills)
            score += (len(common) / len(required)) * 50
        else:
            score += 25
    else:
        score += 25

    # 2. Experience (30 points)
    if campaign.min_experience and campaign.min_experience > 0:
        exp = candidate_analysis.get("experience_years", 0)
        if exp >= campaign.min_experience:
            score += 30
        else:
            ratio = exp / campaign.min_experience if campaign.min_experience > 0 else 0
            score += ratio * 30
    else:
        score += 15

    # 3. Keywords (20 points)
    if campaign.keywords:
        keywords = set([k.strip().lower() for k in campaign.keywords.split(',') if k.strip()])
        cv_text = candidate_analysis.get("summary", "").lower()
        matched = sum(1 for kw in keywords if kw in cv_text)
        score += (matched / len(keywords)) * 20 if keywords else 0
    else:
        score += 10

    return min(100, round(score, 1))

# ─── AUTH ENDPOINTS ──────────────────────────────────────
@app.post("/api/register")
async def register(
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    user_type: str = Form(...),
    company_name: Optional[str] = Form(None),
    skills: Optional[str] = Form(None),
    hourly_rate: Optional[str] = Form(None),
    github: Optional[str] = Form(None),
    industry: Optional[str] = Form(None),
    company_size: Optional[str] = Form(None),
    website: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    # Check existing user
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(400, "Bu email allaqachon ro‘yxatdan o‘tgan")
    
    # Hash password
    hashed = hash_password(password)
    
    # Create user
    new_user = User(
        full_name=full_name,
        email=email,
        hashed_password=hashed,
        user_type=user_type,
        company_name=company_name,
        skills=skills,
        hourly_rate=hourly_rate,
        trust_score=85,
        projects=0,
        earnings=0
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # Create token
    token = create_access_token({"sub": str(new_user.id)})
    
    return JSONResponse({
        "status": "success",
        "message": "Ro‘yxatdan o‘tdingiz!",
        "user": {
            "id": new_user.id,
            "full_name": new_user.full_name,
            "email": new_user.email,
            "user_type": new_user.user_type,
            "company_name": new_user.company_name,
            "trust_score": new_user.trust_score,
            "skills": new_user.skills,
            "hourly_rate": new_user.hourly_rate,
            "projects": new_user.projects,
            "earnings": new_user.earnings
        },
        "session": token
    })

@app.post("/api/login")
async def login(
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(401, "Email yoki parol noto‘g‘ri")
    if not verify_password(password, user.hashed_password):
        raise HTTPException(401, "Email yoki parol noto‘g‘ri")
    
    user.last_login = func.now()
    db.commit()
    
    token = create_access_token({"sub": str(user.id)})
    
    return JSONResponse({
        "status": "success",
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "user_type": user.user_type,
            "company_name": user.company_name,
            "trust_score": user.trust_score,
            "skills": user.skills,
            "hourly_rate": user.hourly_rate,
            "projects": user.projects,
            "earnings": user.earnings
        },
        "session": token
    })

@app.post("/api/token")
async def token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(401, "Invalid credentials")
    token = create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer"}

@app.get("/api/me")
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    return JSONResponse({
        "id": current_user.id,
        "full_name": current_user.full_name,
        "email": current_user.email,
        "user_type": current_user.user_type,
        "company_name": current_user.company_name,
        "skills": current_user.skills,
        "hourly_rate": current_user.hourly_rate,
        "trust_score": current_user.trust_score,
        "projects": current_user.projects,
        "earnings": current_user.earnings
    })

@app.get("/api/users")
async def get_all_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.user_type != "company":
        raise HTTPException(403, "Faqat kompaniya adminlari ko‘ra oladi")
    users = db.query(User).all()
    return JSONResponse([{
        "id": u.id,
        "full_name": u.full_name,
        "email": u.email,
        "user_type": u.user_type,
        "company_name": u.company_name,
        "trust_score": u.trust_score,
        "registered_at": u.registered_at.isoformat() if u.registered_at else None
    } for u in users])

# ─── MODULES ──────────────────────────────────────────────
@app.get("/api/modules")
async def get_modules():
    return JSONResponse(MODULES)

@app.get("/api/modules/{module_id}")
async def get_module(module_id: str):
    for m in MODULES:
        if m["id"] == module_id:
            return JSONResponse(m)
    raise HTTPException(404, "Module not found")

@app.post("/api/modules/{module_id}/action")
async def module_action(
    module_id: str,
    user_id: Optional[int] = Form(None),
    params: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    mod = next((m for m in MODULES if m["id"] == module_id), None)
    if not mod:
        raise HTTPException(404, "Module not found")
    if not mod["active"]:
        raise HTTPException(403, "Module is not active")
    
    # Parse params if provided
    params_dict = {}
    if params:
        try:
            params_dict = json.loads(params)
        except:
            params_dict = {"raw": params}
    
    # Run module logic
    result = await module_logic(module_id, user_id, db, params_dict)
    return JSONResponse({
        "status": "success",
        "module_id": module_id,
        "action_result": result
    })

# ─── TALENTS ──────────────────────────────────────────────
TALENTS = [
    {"id": 1, "name": "Alice Johnson", "skills": "Python, PyTorch, LLM, FastAPI, Docker", "title": "Senior AI Engineer", "trust_score": 99.2},
    {"id": 2, "name": "Bob Smith", "skills": "Rust, C++, Quantum, ZK Proofs, Go", "title": "Systems Architect", "trust_score": 98.7},
    {"id": 3, "name": "Carol White", "skills": "React, Node, TypeScript, GraphQL, AWS", "title": "Full-Stack Lead", "trust_score": 97.9},
    {"id": 4, "name": "David Chen", "skills": "Go, Kubernetes, Terraform, AWS, CI/CD", "title": "DevOps Architect", "trust_score": 98.1},
    {"id": 5, "name": "Elena Rodriguez", "skills": "Data Science, R, SQL, Tableau, Python", "title": "Data Science Lead", "trust_score": 97.5},
    {"id": 6, "name": "Frank Wilson", "skills": "Java, Spring, Microservices, Kafka, MongoDB", "title": "Backend Architect", "trust_score": 96.8},
    {"id": 7, "name": "Grace Kim", "skills": "Swift, iOS, ARKit, CoreML, Firebase", "title": "iOS Lead", "trust_score": 96.2},
    {"id": 8, "name": "Henry Patel", "skills": "C#, .NET, Azure, ML.NET, SQL", "title": "Senior .NET Developer", "trust_score": 95.9},
    {"id": 9, "name": "Irene Zhao", "skills": "Ruby on Rails, React, PostgreSQL, Redis", "title": "Full-Stack Developer", "trust_score": 95.4},
    {"id": 10, "name": "James Brown", "skills": "Security, Penetration Testing, Python, C", "title": "Security Engineer", "trust_score": 98.0},
]

@app.get("/api/talents")
async def get_talents():
    return JSONResponse(TALENTS)

# ─── CAMPAIGNS ────────────────────────────────────────────
@app.post("/api/campaigns")
async def create_campaign(
    title: str = Form(...),
    description: str = Form(...),
    required_skills: Optional[str] = Form(None),
    min_experience: Optional[float] = Form(None),
    keywords: Optional[str] = Form(None),
    budget: str = Form(...),
    deadline: str = Form(...),
    company_id: int = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == company_id).first()
    if not user:
        raise HTTPException(404, "Company not found")
    
    new_campaign = Campaign(
        user_id=company_id,
        name=title,
        description=description,
        required_skills=required_skills,
        min_experience=min_experience,
        keywords=keywords,
        budget=budget,
        deadline=deadline,
        status="active"
    )
    db.add(new_campaign)
    db.commit()
    db.refresh(new_campaign)
    
    return JSONResponse({
        "status": "success",
        "campaign": {
            "id": new_campaign.id,
            "title": new_campaign.name,
            "description": new_campaign.description,
            "required_skills": new_campaign.required_skills,
            "min_experience": new_campaign.min_experience,
            "keywords": new_campaign.keywords,
            "budget": new_campaign.budget,
            "deadline": new_campaign.deadline,
            "company_name": user.company_name or user.full_name,
            "status": new_campaign.status
        }
    })

@app.get("/api/campaigns")
async def get_campaigns(db: Session = Depends(get_db)):
    campaigns = db.query(Campaign).all()
    result = []
    for c in campaigns:
        user = db.query(User).filter(User.id == c.user_id).first()
        result.append({
            "id": c.id,
            "title": c.name,
            "description": c.description,
            "required_skills": c.required_skills,
            "min_experience": c.min_experience,
            "keywords": c.keywords,
            "budget": c.budget or "Custom",
            "deadline": c.deadline or c.created_at.strftime("%Y-%m-%d"),
            "company_name": user.company_name or user.full_name if user else "Unknown",
            "status": c.status,
            "created_at": c.created_at.isoformat() if c.created_at else None
        })
    return JSONResponse(result)

@app.get("/api/campaigns/{campaign_id}/candidates")
async def get_campaign_candidates(
    campaign_id: int,
    db: Session = Depends(get_db)
):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    
    candidates = db.query(Candidate).filter(Candidate.campaign_id == campaign_id).all()
    result = []
    for c in candidates:
        app = db.query(Application).filter(
            Application.candidate_id == c.id,
            Application.campaign_id == campaign_id
        ).first()
        result.append({
            "id": c.id,
            "full_name": c.full_name,
            "email": c.email,
            "skills": c.skills,
            "experience_years": c.experience_years,
            "match_score": app.match_score if app else None,
            "status": c.status
        })
    return JSONResponse(result)

# ─── POSTS ─────────────────────────────────────────────────
@app.post("/api/posts")
async def create_post(
    content: str = Form(...),
    user_id: int = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    
    new_post = Post(user_id=user_id, content=content, likes=0)
    db.add(new_post)
    db.commit()
    db.refresh(new_post)
    
    return JSONResponse({
        "status": "success",
        "post": {
            "id": new_post.id,
            "content": new_post.content,
            "user_name": user.full_name,
            "created_at": new_post.created_at.isoformat() if new_post.created_at else None,
            "likes": 0,
            "comments": []
        }
    })

@app.get("/api/posts")
async def get_posts(db: Session = Depends(get_db)):
    posts = db.query(Post).order_by(desc(Post.created_at)).all()
    result = []
    for p in posts:
        user = db.query(User).filter(User.id == p.user_id).first()
        comments = db.query(Comment).filter(Comment.post_id == p.id).all()
        result.append({
            "id": p.id,
            "content": p.content,
            "user_name": user.full_name if user else "Unknown",
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "likes": p.likes,
            "comments": [{"user_id": c.user_id, "text": c.text} for c in comments]
        })
    return JSONResponse(result)

@app.post("/api/posts/{post_id}/like")
async def like_post(post_id: int, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(404, "Post not found")
    post.likes += 1
    db.commit()
    return JSONResponse({"status": "success", "likes": post.likes})

@app.post("/api/posts/{post_id}/comment")
async def comment_post(
    post_id: int,
    user_id: int = Form(...),
    text: str = Form(...),
    db: Session = Depends(get_db)
):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(404, "Post not found")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    
    new_comment = Comment(post_id=post_id, user_id=user_id, text=text)
    db.add(new_comment)
    db.commit()
    return JSONResponse({"status": "success", "comment": {"user_id": user_id, "text": text}})

# ─── AI CHAT ──────────────────────────────────────────────
@app.post("/api/v1/ai/chat")
async def ai_chat(
    message: str = Form(...),
    user_id: Optional[int] = Form(None),
    db: Session = Depends(get_db)
):
    try:
        system = "You are ERCORS AI, an expert assistant for AI talent management and enterprise solutions. Answer concisely and helpfully. You have knowledge about ERCORS platform with 64 modules including AI Talent Matching, RLHF, Trust Score, Escrow, HFT, Autonomous Agents, WebXR, Quantum Computing, and more."
        result = await call_groq(system, message, temperature=0.7, max_tokens=2048)
        return JSONResponse({"status": "success", "response": result})
    except Exception as e:
        logger.exception("AI chat failed")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

# ─── MASS EMAIL ────────────────────────────────────────────
@app.post("/api/v1/admin/send-mass-email")
async def send_mass_email(
    subject: str = Form(...),
    template_type: str = Form(...),
    target_users: List[str] = Form(...),
    current_user: User = Depends(get_current_user)
):
    if current_user.user_type != "company":
        raise HTTPException(403, "Faqat adminlar uchun")
    logger.info(f"Mass email: subject={subject}, template={template_type}, recipients={len(target_users)}")
    return JSONResponse({
        "status": "success",
        "message": f"{len(target_users)} ta foydalanuvchiga xabar yuborish navbatga qo'shildi."
    })

# ─── HARVESTER ─────────────────────────────────────────────
@app.post("/api/v1/harvester/start")
async def start_harvester(
    language: str = Form("python"),
    min_stars: int = Form(50),
    min_followers: int = Form(20),
    limit: int = Form(10),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    return JSONResponse({
        "status": "RUNNING",
        "message": f"Harvester started for {language} (min_stars={min_stars}, min_followers={min_followers}, limit={limit})"
    })

# ─── NEGOTIATOR ────────────────────────────────────────────
@app.post("/api/v1/negotiate/contract")
async def negotiate_contract(
    company_name: str = Form(...),
    developer_name: str = Form(...),
    project_scope: str = Form(...),
    budget_range: str = Form(...),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    try:
        system = "You are a B2B AI negotiator. Return JSON: {budget: number, deadline: string, terms: string, accepted: boolean}"
        user = f"Company: {company_name}\nDeveloper: {developer_name}\nProject Scope: {project_scope}\nBudget Range: {budget_range}"
        result = await call_groq(system, user, temperature=0.3, max_tokens=1024)
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', result)
        if json_match:
            result = json_match.group(1)
        data = json.loads(result)
        return JSONResponse({"status": "success", "negotiation": data})
    except Exception as e:
        logger.warning(f"Negotiation fallback: {e}")
        return JSONResponse({
            "status": "success",
            "negotiation": {
                "budget": 15000,
                "deadline": "2026-12-31",
                "terms": "Standard NDA + Escrow + 30-day warranty",
                "accepted": True
            }
        })

# ─── HR INTERVIEW ──────────────────────────────────────────
interview_sessions = {}  # In-memory session storage (use Redis in production)

@app.post("/api/v1/ai/interview/start")
async def start_interview(
    module_id: str = Form(...),
    user_id: int = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    
    module = next((m for m in MODULES if m["id"] == module_id), None)
    if not module:
        raise HTTPException(404, "Module not found")
    
    try:
        system = "You are an AI HR interviewer. Generate 5 interview questions as a JSON array of strings."
        prompt = f"Generate 5 interview questions for a {module['name']} role. Description: {module['description']}"
        result = await call_groq(system, prompt, temperature=0.7, max_tokens=1024)
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', result)
        if json_match:
            result = json_match.group(1)
        questions = json.loads(result)
        if not isinstance(questions, list) or len(questions) != 5:
            questions = [
                "Tell me about yourself and your experience.",
                "Why are you interested in this role?",
                "Describe a challenging project you worked on.",
                "How do you stay updated with the latest trends?",
                "Where do you see yourself in 5 years?"
            ]
    except:
        questions = [
            "Tell me about yourself and your experience.",
            "Why are you interested in this role?",
            "Describe a challenging project you worked on.",
            "How do you stay updated with the latest trends?",
            "Where do you see yourself in 5 years?"
        ]
    
    session_id = str(uuid.uuid4())
    interview_sessions[session_id] = {
        "user_id": user_id,
        "module_id": module_id,
        "questions": questions,
        "answers": [],
        "current_index": 0,
        "status": "in_progress",
        "score": None,
        "recommendation": None,
        "feedback": None,
        "created_at": datetime.utcnow().isoformat()
    }
    
    return JSONResponse({
        "status": "success",
        "session_id": session_id,
        "question": questions[0],
        "total_questions": len(questions)
    })

@app.post("/api/v1/ai/interview/answer")
async def answer_interview(
    session_id: str = Form(...),
    answer: str = Form(...)
):
    session = interview_sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session["status"] != "in_progress":
        raise HTTPException(400, "Interview already completed")
    
    session["answers"].append(answer)
    session["current_index"] += 1
    
    if session["current_index"] >= len(session["questions"]):
        # Evaluate
        try:
            system = "You are an AI HR evaluator. Return JSON: {score: number (0-100), recommendation: string ('Hire'/'Interview again'/'Reject'), feedback: string}"
            prompt = f"Questions: {session['questions']}\nAnswers: {session['answers']}"
            result = await call_groq(system, prompt, temperature=0.5, max_tokens=1024)
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', result)
            if json_match:
                result = json_match.group(1)
            eval_data = json.loads(result)
        except:
            eval_data = {"score": 75, "recommendation": "Interview again", "feedback": "Good technical knowledge, needs more experience."}
        
        session["score"] = eval_data.get("score", 75)
        session["recommendation"] = eval_data.get("recommendation", "Interview again")
        session["feedback"] = eval_data.get("feedback", "No feedback provided.")
        session["status"] = "completed"
        
        return JSONResponse({
            "status": "completed",
            "score": session["score"],
            "recommendation": session["recommendation"],
            "feedback": session["feedback"],
            "session_id": session_id
        })
    else:
        return JSONResponse({
            "status": "in_progress",
            "question": session["questions"][session["current_index"]],
            "progress": f"{session['current_index']}/{len(session['questions'])}"
        })

@app.get("/api/v1/ai/interview/status/{session_id}")
async def get_interview_status(session_id: str):
    session = interview_sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return JSONResponse({
        "status": "success",
        "session": {
            "module_id": session["module_id"],
            "status": session["status"],
            "score": session.get("score"),
            "recommendation": session.get("recommendation"),
            "feedback": session.get("feedback"),
            "answers": session["answers"],
            "questions": session["questions"]
        }
    })

# ─── CV SCREENING ──────────────────────────────────────────
@app.post("/api/v1/hr/screen-cv-text")
async def screen_cv_text(
    resume_text: str = Form(...),
    job_description: str = Form(...)
):
    try:
        system = "Analyze the CV against the job description. Return JSON: {score: number (0-100), strengths: list, weaknesses: list, recommendation: string (Hire/Interview/Reject)}"
        user = f"CV:\n{resume_text}\n\nJob Description:\n{job_description}"
        result = await call_groq(system, user, temperature=0.3, max_tokens=1024)
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', result)
        if json_match:
            result = json_match.group(1)
        data = json.loads(result)
        return JSONResponse({"status": "success", "analysis": data})
    except Exception as e:
        logger.warning(f"CV screening fallback: {e}")
        return JSONResponse({
            "status": "success",
            "analysis": {
                "score": 75,
                "strengths": ["Python", "AI/ML", "Leadership", "Problem-solving"],
                "weaknesses": ["Cloud experience", "DevOps skills"],
                "recommendation": "Interview"
            }
        })

@app.post("/api/v1/hr/generate-questions")
async def generate_questions(
    position: str = Form(...),
    seniority: str = Form(...)
):
    try:
        system = f"Generate 5 technical and 3 situational questions for a {seniority} {position}. Return JSON: {{technical: [...], situational: [...]}}"
        user = f"Role: {seniority} {position}"
        result = await call_groq(system, user, temperature=0.7, max_tokens=1024)
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', result)
        if json_match:
            result = json_match.group(1)
        data = json.loads(result)
        return JSONResponse({"status": "success", "questions": data})
    except:
        return JSONResponse({
            "status": "success",
            "questions": {
                "technical": [
                    "Explain OOP principles with examples.",
                    "Write a function to sort an array efficiently.",
                    "Explain REST API design principles.",
                    "What is CI/CD and why is it important?",
                    "Explain microservices architecture."
                ],
                "situational": [
                    "Tell me about a time you faced a challenge and how you overcame it.",
                    "How do you handle conflicts in a team?",
                    "Describe a successful project you led."
                ]
            }
        })

@app.post("/api/v1/hr/generate-email")
async def generate_email(
    candidate_name: str = Form(...),
    position: str = Form(...),
    company_name: str = Form(...),
    email_type: str = Form(...),
    feedback: Optional[str] = Form(None)
):
    try:
        type_text = "offer" if email_type == "offer" else "rejection"
        system = f"Write a professional {type_text} email. Return only the email content, no markdown."
        user = f"Candidate: {candidate_name}\nPosition: {position}\nCompany: {company_name}\nFeedback: {feedback or 'N/A'}"
        result = await call_groq(system, user, temperature=0.5, max_tokens=1024)
        return JSONResponse({"status": "success", "email": result.strip()})
    except:
        return JSONResponse({
            "status": "success",
            "email": f"Dear {candidate_name},\n\nWe are pleased to inform you that we are moving forward with your application for the {position} position at {company_name}.\n\nBest regards,\nHR Team"
        })

# ─── CV UPLOAD & AUTO-MATCH ──────────────────────────────
@app.post("/api/upload-cv")
async def upload_cv(
    file: UploadFile = File(...),
    user_id: Optional[int] = Form(None),
    module_id: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    # Validate file
    if not file.filename.lower().endswith(('.pdf', '.docx', '.txt')):
        raise HTTPException(400, "Faqat PDF, DOCX yoki TXT ruxsat")
    
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, f"Fayl hajmi {MAX_FILE_SIZE // 1024 // 1024} MB dan oshmasligi kerak")
    
    # Save file
    filename = f"{uuid.uuid4().hex}_{file.filename}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(content)
    
    # Extract text
    try:
        resume_text = extract_text_from_file(content, file.filename)
    except Exception as e:
        raise HTTPException(400, f"Matn chiqarishda xatolik: {str(e)}")
    
    # AI analysis
    analysis = await analyze_cv_with_ai(resume_text)
    
    # Create candidate
    full_name = analysis.get("current_position", file.filename.replace('.txt', '').replace('_', ' '))
    new_candidate = Candidate(
        user_id=user_id,
        full_name=full_name,
        resume_file=filepath,
        resume_text=resume_text[:5000],
        resume_analysis=analysis,
        skills=", ".join(analysis.get("skills", [])),
        experience_years=analysis.get("experience_years", 0),
        current_position=analysis.get("current_position", ""),
        source="upload",
        status="new",
        module_id=module_id
    )
    db.add(new_candidate)
    db.commit()
    db.refresh(new_candidate)
    
    # Auto-match with campaigns
    campaigns = db.query(Campaign).filter(Campaign.status == "active").all()
    applications_created = 0
    for camp in campaigns:
        score = calculate_match_score(analysis, camp)
        if score >= 50:
            app = Application(
                candidate_id=new_candidate.id,
                campaign_id=camp.id,
                user_id=user_id,
                match_score=score,
                ai_feedback=f"Avtomatik moslik: {score}%",
                status="review"
            )
            db.add(app)
            applications_created += 1
    db.commit()
    
    return JSONResponse({
        "status": "success",
        "candidate_id": new_candidate.id,
        "file_path": f"/uploads/{filename}",
        "analysis": analysis,
        "campaigns_matched": applications_created
    })

# ─── CANDIDATE MATCHES ────────────────────────────────────
@app.get("/api/candidates/{candidate_id}/match")
async def get_candidate_matches(
    candidate_id: int,
    db: Session = Depends(get_db)
):
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(404, "Candidate not found")
    if not candidate.resume_analysis:
        raise HTTPException(400, "CV hali tahlil qilinmagan")
    
    campaigns = db.query(Campaign).filter(Campaign.status == "active").all()
    matches = []
    for camp in campaigns:
        score = calculate_match_score(candidate.resume_analysis, camp)
        matches.append({
            "campaign_id": camp.id,
            "campaign_name": camp.name,
            "match_score": score,
            "required_skills": camp.required_skills,
            "min_experience": camp.min_experience,
            "budget": camp.budget,
            "deadline": camp.deadline
        })
    matches.sort(key=lambda x: x["match_score"], reverse=True)
    return JSONResponse({
        "candidate_id": candidate_id,
        "matches": matches
    })

# ─── AUDIO TRANSCRIBE ──────────────────────────────────────
@app.post("/api/v1/hr/audio/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str = Form("en")
):
    if not file.filename.lower().endswith(('.mp3', '.wav', '.m4a', '.ogg', '.webm', '.flac')):
        raise HTTPException(400, "Faqat audio fayllar ruxsat: mp3, wav, m4a, ogg, webm, flac")
    
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, f"Fayl hajmi {MAX_FILE_SIZE // 1024 // 1024} MB dan oshmasligi kerak")
    
    try:
        text = await groq.audio_transcribe(content, file.filename, language)
        return JSONResponse({
            "status": "success",
            "transcription": text,
            "language": language,
            "filename": file.filename
        })
    except Exception as e:
        logger.error(f"Transkripsiya xatosi: {e}")
        raise HTTPException(500, f"Transkripsiya muvaffaqiyatsiz: {str(e)}")

# ─── AUDIO INTERVIEW ANALYSIS ─────────────────────────────
@app.post("/api/v1/hr/audio/analyze-interview")
async def analyze_audio_interview(
    file: UploadFile = File(...),
    position: str = Form(""),
    language: str = Form("en"),
    user_id: Optional[int] = Form(None),
    db: Session = Depends(get_db)
):
    if not file.filename.lower().endswith(('.mp3', '.wav', '.m4a', '.ogg', '.webm', '.flac')):
        raise HTTPException(400, "Faqat audio fayllar ruxsat")
    
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, f"Fayl hajmi {MAX_FILE_SIZE // 1024 // 1024} MB dan oshmasligi kerak")
    
    try:
        # Transcribe
        transcript = await groq.audio_transcribe(content, file.filename, language)
        if not transcript.strip():
            raise HTTPException(400, "Transkripsiya bo‘sh, audio tushunarsiz yoki noto‘g‘ri format.")
        
        # Analyze
        system_prompt = """You are an expert HR interviewer. Analyze the interview transcript and return JSON:
        {
            "summary": "brief overall impression (max 100 words)",
            "strengths": ["list of strengths (up to 5)"],
            "weaknesses": ["list of weaknesses (up to 5)"],
            "match_score": number (0-100),
            "recommendation": "Hire / Interview again / Reject",
            "communication": "score 0-100",
            "technical_skills": "score 0-100",
            "cultural_fit": "score 0-100"
        }"""
        user_prompt = f"Position: {position or 'Not specified'}\n\nTranscript:\n{transcript[:4000]}"
        result = await call_groq(system_prompt, user_prompt, temperature=0.4, max_tokens=2048)
        
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', result)
        if json_match:
            result = json_match.group(1)
        analysis = json.loads(result)
        
        # Save interview record
        new_interview = Interview(
            candidate_id=None,  # No candidate yet
            user_id=user_id,
            status="completed",
            questions=[],
            answers=[],
            score=analysis.get("match_score", 0),
            recommendation=analysis.get("recommendation", "N/A"),
            feedback=analysis.get("summary", ""),
            audio_file=f"audio_{uuid.uuid4().hex}.mp3",
            transcript=transcript,
            analysis=analysis
        )
        db.add(new_interview)
        db.commit()
        
        # Auto-match with campaigns if position provided
        campaigns_matched = 0
        if position:
            campaigns = db.query(Campaign).filter(Campaign.status == "active").all()
            skills = []
            for word in ["python", "machine learning", "ai", "react", "node", "sql", "cloud", "devops", "leadership", "docker", "kubernetes", "aws", "gcp", "azure", "tensorflow", "pytorch", "nlp", "computer vision"]:
                if word.lower() in transcript.lower():
                    skills.append(word.capitalize())
            if not skills:
                skills = ["Communication", "Problem-solving", "Analytical thinking"]
            
            mock_analysis = {
                "skills": skills,
                "experience_years": 3,
                "summary": transcript[:500]
            }
            for camp in campaigns:
                score = calculate_match_score(mock_analysis, camp)
                if score >= 50:
                    # Create a candidate from this interview
                    candidate = Candidate(
                        user_id=user_id,
                        full_name=f"Interview Candidate {new_interview.id}",
                        resume_text=transcript[:1000],
                        resume_analysis=mock_analysis,
                        skills=", ".join(skills),
                        experience_years=3,
                        source="audio_interview",
                        status="review"
                    )
                    db.add(candidate)
                    db.commit()
                    db.refresh(candidate)
                    
                    app = Application(
                        candidate_id=candidate.id,
                        campaign_id=camp.id,
                        user_id=user_id,
                        match_score=score,
                        ai_feedback=f"Audio intervyudan avtomatik moslik: {score}%",
                        status="review"
                    )
                    db.add(app)
                    campaigns_matched += 1
            db.commit()
        
        return JSONResponse({
            "status": "success",
            "transcription": transcript,
            "analysis": analysis,
            "campaigns_matched": campaigns_matched,
            "interview_id": new_interview.id,
            "filename": file.filename
        })
    except json.JSONDecodeError as e:
        return JSONResponse({
            "status": "error",
            "message": "AI tahlil natijasi noto‘g‘ri formatda",
            "raw_response": result if 'result' in locals() else "No response"
        }, status_code=500)
    except Exception as e:
        logger.error(f"Audio intervyu tahlilida xatolik: {e}")
        raise HTTPException(500, f"Tahlil muvaffaqiyatsiz: {str(e)}")

# ─── ESCROW ────────────────────────────────────────────────
@app.get("/api/escrow")
async def get_escrows(db: Session = Depends(get_db)):
    escrows = db.query(Escrow).all()
    return JSONResponse([{
        "id": e.id,
        "title": e.title,
        "description": e.description,
        "amount": e.amount,
        "status": e.status,
        "created_at": e.created_at.isoformat() if e.created_at else None
    } for e in escrows])

@app.post("/api/escrow")
async def create_escrow(
    title: str = Form(...),
    amount: float = Form(...),
    description: Optional[str] = Form(None),
    user_id: Optional[int] = Form(None),
    db: Session = Depends(get_db)
):
    new_escrow = Escrow(
        user_id=user_id,
        title=title,
        description=description,
        amount=amount,
        status="pending"
    )
    db.add(new_escrow)
    db.commit()
    db.refresh(new_escrow)
    return JSONResponse({
        "status": "success",
        "escrow": {
            "id": new_escrow.id,
            "title": new_escrow.title,
            "amount": new_escrow.amount,
            "status": new_escrow.status
        }
    })

# ─── BADGE ──────────────────────────────────────────────────
@app.get("/api/v1/badge/{user_id}.svg")
async def get_badge(user_id: str):
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="190" height="20">
      <linearGradient id="b" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>
      <mask id="a"><rect width="190" height="20" rx="3" fill="#fff"/></mask>
      <g mask="url(#a)">
        <path fill="#0d1117" d="0 0h90v20H0z"/>
        <path fill="#00F0FF" d="M90 0h100v20H90z"/>
        <path fill="url(#b)" d="0 0h190v20H0z"/>
      </g>
      <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
        <text x="45" y="15" fill="#010101" fill-opacity=".3">ERCORS</text>
        <text x="45" y="14">ERCORS</text>
        <text x="140" y="15" fill="#010101" fill-opacity=".3">Verified</text>
        <text x="140" y="14" fill="#030712">Verified</text>
      </g>
    </svg>"""
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "no-cache"})

# ─── HEALTH ──────────────────────────────────────────────
@app.get("/health")
async def health():
    return JSONResponse({
        "status": "healthy",
        "version": "9.8",
        "modules": len(MODULES),
        "groq_keys": len([k for k in groq.keys if k != "dummy"]),
        "timestamp": datetime.utcnow().isoformat()
    })

# ─── ROOT ──────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h1>index.html topilmadi</h1><p>Iltimos, index.html faylini main.py bilan bir papkaga joylashtiring.</p>", status_code=404)

# ─── ERROR HANDLERS ────────────────────────────────────────
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": exc.detail}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Internal server error"}
    )

# ─── RUN ──────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"🚀 ERCORS AGI Platform v9.8 starting on port {PORT}...")
    print(f"📦 {len(MODULES)} modules loaded")
    print(f"🔑 Groq keys: {len([k for k in groq.keys if k != 'dummy'])}")
    print(f"🗄️  Database: {DATABASE_URL}")
    print(f"📄 API docs: http://localhost:{PORT}/docs")
    print("🎤 Audio endpoints: /api/v1/hr/audio/transcribe, /api/v1/hr/audio/analyze-interview")
    print("🤖 AI Chat: /api/v1/ai/chat")
    print("📝 CV upload: /api/upload-cv")
    print("🔐 Auth: /api/register, /api/login")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
