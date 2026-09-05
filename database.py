from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, Float, ForeignKey, JSON
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.sql import func
from config import DATABASE_URL

Base = declarative_base()
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ─── Models ──────────────────────────────────────────────
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
    applications = relationship("Application", foreign_keys="Application.user_id", back_populates="user")

class Candidate(Base):
    __tablename__ = "candidates"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    full_name = Column(String(100), nullable=False)
    email = Column(String(100), index=True)
    phone = Column(String(20), nullable=True)
    resume_text = Column(Text, nullable=True)
    resume_file = Column(String(200), nullable=True)
    skills = Column(Text, nullable=True)
    experience_years = Column(Float, default=0)
    current_position = Column(String(100), nullable=True)
    source = Column(String(50), default="manual")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    owner = relationship("User", back_populates="candidates")
    applications = relationship("Application", back_populates="candidate")

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
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    owner = relationship("User", back_populates="campaigns")

class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"))
    job_id = Column(Integer, ForeignKey("jobs.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    status = Column(String(20), default="new")
    match_score = Column(Float, nullable=True)
    ai_feedback = Column(Text, nullable=True)
    applied_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    candidate = relationship("Candidate", back_populates="applications")
    job = relationship("Job", back_populates="applications")
    user = relationship("User", foreign_keys=[user_id], back_populates="applications")

class Interview(Base):
    __tablename__ = "interviews"
    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"))
    scheduled_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="pending")
    questions = Column(JSON, default=list)
    answers = Column(JSON, default=list)
    score = Column(Float, nullable=True)
    recommendation = Column(String(20), nullable=True)
    feedback = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

class EmailTemplate(Base):
    __tablename__ = "email_templates"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)
    subject = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    type = Column(String(20), default="generic")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

Base.metadata.create_all(bind=engine)