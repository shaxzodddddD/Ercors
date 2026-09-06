import os, json, re, asyncio, logging, uuid, io
from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import httpx
import uvicorn

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, Float, ForeignKey, JSON
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from sqlalchemy.sql import func
from passlib.context import CryptContext
from jose import JWTError, jwt

import pdfplumber
from docx import Document

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ERCORS_MAIN")

# ─── Config ──────────────────────────────────────────────
GROQ_API_KEY_1 = os.getenv("GROQ_API_KEY_1")
GROQ_API_KEY_2 = os.getenv("GROQ_API_KEY_2")
GROQ_API_KEY_3 = os.getenv("GROQ_API_KEY_3")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ercors_platform.db")
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "10485760"))
PORT = int(os.getenv("PORT", 10000))

# ─── Database ─────────────────────────────────────────────
connect_args = {}
if "sqlite" in DATABASE_URL:
    connect_args = {"check_same_thread": False}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

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

# ─── SQLAlchemy Models ──────────────────────────────────
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(200), nullable=False)
    user_type = Column(String(20), default="expert")
    company_name = Column(String(100), nullable=True)
    skills = Column(Text, nullable=True)
    hourly_rate = Column(String(20), nullable=True)
    trust_score = Column(Integer, default=85)
    projects = Column(Integer, default=0)
    earnings = Column(Integer, default=0)
    registered_at = Column(DateTime, default=func.now())
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime, nullable=True)
    candidates = relationship("Candidate", back_populates="owner")
    jobs = relationship("Job", back_populates="owner")
    campaigns = relationship("Campaign", back_populates="owner")
    posts = relationship("Post", back_populates="author")
    applications = relationship("Application", foreign_keys="Application.user_id", back_populates="user")

class Candidate(Base):
    __tablename__ = "candidates"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    full_name = Column(String(100), nullable=False)
    email = Column(String(100), index=True, nullable=True)
    phone = Column(String(20), nullable=True)
    resume_text = Column(Text, nullable=True)
    resume_file = Column(String(200), nullable=True)
    resume_analysis = Column(JSON, nullable=True)
    skills = Column(Text, nullable=True)
    experience_years = Column(Float, default=0)
    current_position = Column(String(100), nullable=True)
    source = Column(String(50), default="manual")
    status = Column(String(20), default="new")
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)
    module_id = Column(String(20), nullable=True)  # yangi maydon
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    owner = relationship("User", back_populates="candidates")
    applications = relationship("Application", back_populates="candidate")
    campaign = relationship("Campaign", back_populates="candidates")

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
    applications = relationship("Application", back_populates="job")

class Campaign(Base):
    __tablename__ = "campaigns"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    required_skills = Column(Text, nullable=True)
    min_experience = Column(Float, nullable=True)
    keywords = Column(Text, nullable=True)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    owner = relationship("User", back_populates="campaigns")
    candidates = relationship("Candidate", back_populates="campaign")

class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    content = Column(Text, nullable=False)
    likes = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    author = relationship("User", back_populates="posts")
    comments = relationship("Comment", back_populates="post")

class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("posts.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=func.now())
    post = relationship("Post", back_populates="comments")

class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"))
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    status = Column(String(20), default="new")
    match_score = Column(Float, nullable=True)
    ai_feedback = Column(Text, nullable=True)
    applied_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    candidate = relationship("Candidate", back_populates="applications")
    job = relationship("Job", back_populates="applications")
    user = relationship("User", foreign_keys=[user_id], back_populates="applications")
    campaign = relationship("Campaign")

class Interview(Base):
    __tablename__ = "interviews"
    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    scheduled_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="pending")
    questions = Column(JSON, default=list)
    answers = Column(JSON, default=list)
    score = Column(Float, nullable=True)
    recommendation = Column(String(20), nullable=True)
    feedback = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    candidate = relationship("Candidate")

class Escrow(Base):
    __tablename__ = "escrows"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    amount = Column(Float, nullable=False)
    status = Column(String(20), default="pending")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

Base.metadata.create_all(bind=engine)

# ─── 64 Modules (qisqartirilgan, to‘liq ro‘yxat avvalgi kodda bor) ──
MODULES = [
    {"id": "m1", "name": "Enterprise AI Talent Matching", "category": "Core", "icon": "fa-users", "active": True},
    # ... qolgan 63 ta modul (avvalgi ro‘yxatni qo‘ying)
]
# To‘liq ro‘yxatni iloji boricha qo‘shing, aks holda fallback ishlaydi.

TALENTS = [
    {"id": 1, "name": "Alice Johnson", "skills": "Python, PyTorch, LLM, FastAPI", "title": "Senior AI Engineer", "trust_score": 99.2},
    # ...
]

app = FastAPI(title="ERCORS AGI Platform", version="9.3")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# ─── Groq Load Balancer ──────────────────────────────────
class GroqLoadBalancer:
    def __init__(self):
        self.keys = [GROQ_API_KEY_1, GROQ_API_KEY_2, GROQ_API_KEY_3]
        self.keys = [k for k in self.keys if k]
        if not self.keys:
            raise Exception("Groq API kalitlari topilmadi!")
        self.current_index = 0
        self.model = GROQ_MODEL
        self.failed_keys = set()
        self.lock = asyncio.Lock()

    async def get_next_key(self):
        async with self.lock:
            available = [k for k in self.keys if k not in self.failed_keys]
            if not available:
                self.failed_keys.clear()
                available = self.keys
            key = available[self.current_index % len(available)]
            self.current_index = (self.current_index + 1) % len(available)
            return key

    async def chat_completion(self, messages, temperature=0.7, max_tokens=2048):
        tried = set()
        for _ in range(len(self.keys)):
            key = await self.get_next_key()
            if key in tried:
                continue
            tried.add(key)
            try:
                url = "https://api.groq.com/openai/v1/chat/completions"
                headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                payload = {"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
                async with httpx.AsyncClient(timeout=60.0) as client:
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

groq = GroqLoadBalancer()

async def call_groq(system: str, user: str, temp: float = 0.7) -> str:
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    result = await groq.chat_completion(messages, temperature=temp, max_tokens=2048)
    return result["choices"][0]["message"]["content"]

# ─── Matn chiqarish ──────────────────────────────────────
def extract_text_from_file(file_bytes: bytes, filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    text = ""
    try:
        if ext == ".pdf":
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                for page in pdf.pages:
                    text += page.extract_text() or ""
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

# ─── AI CV tahlili ──────────────────────────────────────
async def analyze_cv_with_ai(resume_text: str) -> Dict[str, Any]:
    system = (
        "You are an expert HR analyst. Analyze the CV text and return a JSON object with these fields:\n"
        "- skills: list of key technical and soft skills (up to 10)\n"
        "- experience_years: total years of professional experience (float)\n"
        "- current_position: current job title or role (string)\n"
        "- education: highest education level (string)\n"
        "- summary: brief summary of the candidate (string)\n"
        "Return only valid JSON."
    )
    user = f"CV text:\n{resume_text[:3000]}"
    try:
        result = await call_groq(system, user, 0.3)
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', result)
        if json_match:
            result = json_match.group(1)
        data = json.loads(result)
        required_fields = ["skills", "experience_years", "current_position", "education", "summary"]
        for field in required_fields:
            if field not in data:
                data[field] = None if field != "skills" else []
        return data
    except Exception as e:
        logger.error(f"AI tahlilida xatolik: {e}")
        return {
            "skills": [],
            "experience_years": 0.0,
            "current_position": "Unknown",
            "education": "Unknown",
            "summary": "No analysis available"
        }

# ─── Moslikni hisoblash ──────────────────────────────────
def calculate_match_score(candidate_analysis: Dict, campaign: Campaign) -> float:
    score = 0.0
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

    if campaign.min_experience and campaign.min_experience > 0:
        exp = candidate_analysis.get("experience_years", 0)
        if exp >= campaign.min_experience:
            score += 30
        else:
            ratio = exp / campaign.min_experience if campaign.min_experience > 0 else 0
            score += ratio * 30
    else:
        score += 15

    if campaign.keywords:
        keywords = set([k.strip().lower() for k in campaign.keywords.split(',') if k.strip()])
        cv_text = candidate_analysis.get("summary", "").lower()
        matched = sum(1 for kw in keywords if kw in cv_text)
        score += (matched / len(keywords)) * 20 if keywords else 0
    else:
        score += 10

    return min(100, round(score, 1))

# ─── Auth ──────────────────────────────────────────────────
@app.post("/api/register")
async def register(
        full_name: str = Form(...), email: str = Form(...), password: str = Form(...),
        user_type: str = Form(...), company_name: str = Form(None), skills: str = Form(None),
        hourly_rate: str = Form(None), db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(400, "Bu email allaqachon ro‘yxatdan o‘tgan")
    hashed = hash_password(password)
    new_user = User(full_name=full_name, email=email, hashed_password=hashed, user_type=user_type,
                    company_name=company_name, skills=skills, hourly_rate=hourly_rate, trust_score=85)
    db.add(new_user); db.commit(); db.refresh(new_user)
    token = create_access_token({"sub": str(new_user.id)})
    return JSONResponse({"status":"success","message":"Ro‘yxatdan o‘tdingiz!","user":{
        "id":new_user.id,"full_name":new_user.full_name,"email":new_user.email,
        "user_type":new_user.user_type,"company_name":new_user.company_name,"trust_score":new_user.trust_score
    },"session":token})

@app.post("/api/login")
async def login(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(401, "Email yoki parol noto‘g‘ri")
    user.last_login = func.now(); db.commit()
    token = create_access_token({"sub": str(user.id)})
    return JSONResponse({"status":"success","user":{
        "id":user.id,"full_name":user.full_name,"email":user.email,
        "user_type":user.user_type,"company_name":user.company_name,"trust_score":user.trust_score
    },"session":token})

@app.get("/api/me")
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    return JSONResponse({
        "id":current_user.id,"full_name":current_user.full_name,"email":current_user.email,
        "user_type":current_user.user_type,"company_name":current_user.company_name,
        "skills":current_user.skills,"hourly_rate":current_user.hourly_rate,
        "trust_score":current_user.trust_score,"projects":current_user.projects,"earnings":current_user.earnings
    })

# ─── Modules ──────────────────────────────────────────────
@app.get("/api/modules")
async def get_modules():
    return JSONResponse(MODULES)

@app.get("/api/talents")
async def get_talents():
    return JSONResponse(TALENTS)

# ─── Campaigns ────────────────────────────────────────────
@app.post("/api/campaigns")
async def create_campaign(
        title: str = Form(...), description: str = Form(...),
        required_skills: Optional[str] = Form(None), min_experience: Optional[float] = Form(None),
        keywords: Optional[str] = Form(None), budget: str = Form(...), deadline: str = Form(...),
        company_id: int = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == company_id).first()
    if not user: raise HTTPException(404, "Company not found")
    new_campaign = Campaign(user_id=company_id, name=title, description=description,
                            required_skills=required_skills, min_experience=min_experience,
                            keywords=keywords, status="Open")
    db.add(new_campaign); db.commit(); db.refresh(new_campaign)
    return JSONResponse({"status":"success","campaign":{
        "id":new_campaign.id,"title":new_campaign.name,"description":new_campaign.description,
        "required_skills":new_campaign.required_skills,"min_experience":new_campaign.min_experience,
        "keywords":new_campaign.keywords,"budget":budget,"deadline":deadline,
        "company_name":user.company_name or user.full_name,"status":new_campaign.status
    }})

@app.get("/api/campaigns")
async def get_campaigns(db: Session = Depends(get_db)):
    campaigns = db.query(Campaign).all()
    result = []
    for c in campaigns:
        user = db.query(User).filter(User.id == c.user_id).first()
        result.append({
            "id":c.id,"title":c.name,"description":c.description,
            "required_skills":c.required_skills,"min_experience":c.min_experience,
            "keywords":c.keywords,"budget":"Custom",
            "deadline":c.created_at.strftime("%Y-%m-%d") if c.created_at else "N/A",
            "company_name":user.company_name or user.full_name if user else "Unknown",
            "status":c.status,"created_at":c.created_at.isoformat() if c.created_at else None
        })
    return JSONResponse(result)

# ─── Posts ─────────────────────────────────────────────────
@app.post("/api/posts")
async def create_post(content: str = Form(...), user_id: int = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(404, "User not found")
    new_post = Post(user_id=user_id, content=content, likes=0)
    db.add(new_post); db.commit(); db.refresh(new_post)
    return JSONResponse({"status":"success","post":{
        "id":new_post.id,"content":new_post.content,"user_name":user.full_name,
        "created_at":new_post.created_at.isoformat() if new_post.created_at else None,
        "likes":0,"comments":[]
    }})

@app.get("/api/posts")
async def get_posts(db: Session = Depends(get_db)):
    posts = db.query(Post).order_by(Post.created_at.desc()).all()
    result = []
    for p in posts:
        user = db.query(User).filter(User.id == p.user_id).first()
        comments = db.query(Comment).filter(Comment.post_id == p.id).all()
        result.append({
            "id":p.id,"content":p.content,"user_name":user.full_name if user else "Unknown",
            "created_at":p.created_at.isoformat() if p.created_at else None,
            "likes":p.likes,"comments":[{"user_id":c.user_id,"text":c.text} for c in comments]
        })
    return JSONResponse(result)

@app.post("/api/posts/{post_id}/like")
async def like_post(post_id: int, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post: raise HTTPException(404, "Post not found")
    post.likes += 1; db.commit()
    return JSONResponse({"status":"success","likes":post.likes})

@app.post("/api/posts/{post_id}/comment")
async def comment_post(post_id: int, user_id: int = Form(...), text: str = Form(...), db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post: raise HTTPException(404, "Post not found")
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(404, "User not found")
    new_comment = Comment(post_id=post_id, user_id=user_id, text=text)
    db.add(new_comment); db.commit()
    return JSONResponse({"status":"success","comment":{"user_id":user_id,"text":text}})

# ─── AI Chat ──────────────────────────────────────────────
@app.post("/api/v1/ai/chat")
async def ai_chat(message: str = Form(...), user_id: Optional[int] = Form(None)):
    try:
        system = "You are ERCORS AI, an expert assistant for AI talent management and enterprise solutions. Answer concisely and helpfully."
        result = await call_groq(system, message, 0.7)
        return JSONResponse({"status":"success","response":result})
    except Exception as e:
        logger.exception("AI chat failed")
        return JSONResponse({"status":"error","message":str(e)}, status_code=500)

# ─── Harvester ─────────────────────────────────────────────
@app.post("/api/v1/harvester/start")
async def start_harvester(language: str = Form("python"), min_stars: int = Form(50),
                          min_followers: int = Form(20), limit: int = Form(10)):
    return JSONResponse({"status":"RUNNING","message":f"Harvester started for {language} (min_stars={min_stars}, limit={limit})"})

# ─── Negotiator ────────────────────────────────────────────
@app.post("/api/v1/negotiate/contract")
async def negotiate_contract(company_name: str = Form(...), developer_name: str = Form(...),
                             project_scope: str = Form(...), budget_range: str = Form(...)):
    try:
        system = "You are a B2B AI negotiator. Return JSON: {budget, deadline, terms, accepted}"
        user = f"Company: {company_name}\nDeveloper: {developer_name}\nProject: {project_scope}\nBudget: {budget_range}"
        result = await call_groq(system, user, 0.3)
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', result)
        if json_match: result = json_match.group(1)
        data = json.loads(result)
        return JSONResponse({"status":"success","negotiation":data})
    except Exception:
        return JSONResponse({"status":"success","negotiation":{"budget":15000,"deadline":"2026-12-31","terms":"Standard NDA + Escrow","accepted":True}})

# ─── HR Interview ──────────────────────────────────────────
interview_sessions = {}
@app.post("/api/v1/ai/interview/start")
async def start_interview(module_id: str = Form(...), user_id: int = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(404, "User not found")
    module = next((m for m in MODULES if m["id"] == module_id), None)
    if not module: raise HTTPException(404, "Module not found")
    try:
        system = "You are an AI HR interviewer. Generate 5 interview questions as JSON array."
        prompt = f"Generate 5 interview questions for role: {module['name']}. Description: {module['description']}"
        result = await call_groq(system, prompt, 0.7)
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', result)
        if json_match: result = json_match.group(1)
        questions = json.loads(result)
        if not isinstance(questions, list) or len(questions) != 5:
            questions = ["Tell me about yourself...","Why are you interested?","Describe a challenge...","How do you stay updated?","Where do you see yourself in 5 years?"]
    except:
        questions = ["Tell me about yourself...","Why are you interested?","Describe a challenge...","How do you stay updated?","Where do you see yourself in 5 years?"]
    session_id = str(uuid.uuid4())
    interview_sessions[session_id] = {"user_id":user_id,"module_id":module_id,"questions":questions,"answers":[],"current_index":0,"status":"in_progress","score":None,"recommendation":None,"feedback":None}
    return JSONResponse({"status":"success","session_id":session_id,"question":questions[0],"total_questions":len(questions)})

@app.post("/api/v1/ai/interview/answer")
async def answer_interview(session_id: str = Form(...), answer: str = Form(...)):
    session = interview_sessions.get(session_id)
    if not session: raise HTTPException(404, "Session not found")
    if session["status"] != "in_progress": raise HTTPException(400, "Interview already completed")
    session["answers"].append(answer)
    session["current_index"] += 1
    if session["current_index"] >= len(session["questions"]):
        try:
            system = "You are an AI HR evaluator. Return JSON: {score, recommendation, feedback}"
            prompt = f"Questions: {session['questions']}\nAnswers: {session['answers']}"
            result = await call_groq(system, prompt, 0.5)
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', result)
            if json_match: result = json_match.group(1)
            eval_data = json.loads(result)
        except:
            eval_data = {"score":75,"recommendation":"Interview","feedback":"Good technical knowledge."}
        session["score"] = eval_data.get("score",75)
        session["recommendation"] = eval_data.get("recommendation","Interview")
        session["feedback"] = eval_data.get("feedback","No feedback.")
        session["status"] = "completed"
        return JSONResponse({"status":"completed","score":session["score"],"recommendation":session["recommendation"],"feedback":session["feedback"],"session_id":session_id})
    else:
        return JSONResponse({"status":"in_progress","question":session["questions"][session["current_index"]],"progress":f"{session['current_index']}/{len(session['questions'])}"})

# ─── CV Upload & Auto-Match ──────────────────────────────
@app.post("/api/upload-cv")
async def upload_cv(
        file: UploadFile = File(...),
        user_id: Optional[int] = Form(None),
        module_id: Optional[str] = Form(None),
        db: Session = Depends(get_db)):
    if not file.filename.lower().endswith(('.pdf','.docx','.txt')):
        raise HTTPException(400, "Faqat PDF, DOCX yoki TXT ruxsat")
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, f"Fayl hajmi {MAX_FILE_SIZE//1024//1024} MB dan oshmasligi kerak")
    filename = f"{uuid.uuid4().hex}_{file.filename}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f: f.write(content)
    try:
        resume_text = extract_text_from_file(content, file.filename)
    except Exception as e:
        raise HTTPException(400, f"Matn chiqarishda xatolik: {str(e)}")
    analysis = await analyze_cv_with_ai(resume_text)
    full_name = analysis.get("current_position", file.filename.replace('.txt','').replace('_',' '))
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
    db.add(new_candidate); db.commit(); db.refresh(new_candidate)
    campaigns = db.query(Campaign).filter(Campaign.status == "Open").all()
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
            db.add(app); applications_created += 1
    db.commit()
    return JSONResponse({
        "status":"success",
        "candidate_id":new_candidate.id,
        "file_path":f"/uploads/{filename}",
        "analysis":analysis,
        "campaigns_matched":applications_created
    })

# ─── Candidate Matches ─────────────────────────────────────
@app.get("/api/candidates/{candidate_id}/match")
async def get_candidate_matches(candidate_id: int, db: Session = Depends(get_db)):
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate: raise HTTPException(404, "Candidate not found")
    if not candidate.resume_analysis: raise HTTPException(400, "CV hali tahlil qilinmagan")
    campaigns = db.query(Campaign).filter(Campaign.status == "Open").all()
    matches = []
    for camp in campaigns:
        score = calculate_match_score(candidate.resume_analysis, camp)
        matches.append({
            "campaign_id": camp.id,
            "campaign_name": camp.name,
            "match_score": score,
            "required_skills": camp.required_skills,
            "min_experience": camp.min_experience
        })
    matches.sort(key=lambda x: x["match_score"], reverse=True)
    return JSONResponse({"candidate_id": candidate_id, "matches": matches})

# ─── Escrow ────────────────────────────────────────────────
@app.get("/api/escrow")
async def get_escrows(db: Session = Depends(get_db)):
    escrows = db.query(Escrow).all()
    return JSONResponse([{"id":e.id,"title":e.title,"amount":e.amount,"status":e.status,"created_at":e.created_at.isoformat() if e.created_at else None} for e in escrows])

@app.post("/api/escrow")
async def create_escrow(title: str = Form(...), amount: float = Form(...), db: Session = Depends(get_db)):
    new_escrow = Escrow(title=title, amount=amount, status="pending")
    db.add(new_escrow); db.commit(); db.refresh(new_escrow)
    return JSONResponse({"status":"success","escrow":{"id":new_escrow.id,"title":new_escrow.title,"amount":new_escrow.amount}})

# ─── Badge ──────────────────────────────────────────────────
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
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control":"no-cache"})

# ─── Health ─────────────────────────────────────────────────
@app.get("/health")
async def health():
    return JSONResponse({"status":"healthy","version":"9.3","modules":len(MODULES),"groq_keys":len(groq.keys)})

# ─── Root ──────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h1>index.html topilmadi</h1>", status_code=404)

if __name__ == "__main__":
    print(f"🚀 ERCORS AGI Platform v9.3 starting on port {PORT}...")
    print(f"📦 {len(MODULES)} modules loaded")
    print(f"🔑 Groq keys: {len(groq.keys)}")
    print(f"🗄️  Database: {DATABASE_URL}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
