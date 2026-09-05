import os
from dotenv import load_dotenv

load_dotenv()

# Groq API
GROQ_API_KEY_1 = os.getenv("GROQ_API_KEY_1", "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")
GROQ_API_KEY_2 = os.getenv("GROQ_API_KEY_2", "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")
GROQ_API_KEY_3 = os.getenv("GROQ_API_KEY_3", "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")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./hr_platform.db")

# JWT
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))

# Upload
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "10485760"))