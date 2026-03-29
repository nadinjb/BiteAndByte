import os
from dotenv import load_dotenv

load_dotenv()

# --- Tokens & credentials ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- Reddit API (free tier, read-only) ---
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = os.getenv(
    "REDDIT_USER_AGENT", "BiteAndByte:v1.0 (by /u/BiteAndByteBot)"
)
REDDIT_SUBREDDITS = ["Biohacking", "Nutrition", "Fitness"]

# --- Gemini models (google-genai 2026 SDK) ---
GEMINI_FLASH = "gemini-2.5-flash"       # Default — daily logging & extraction
GEMINI_PRO = "gemini-2.5-pro"           # Complex reviews & blood analysis

# --- Google Sheets worksheet names ---
WS_PROFILES = "User_Profiles"
WS_BIOMETRICS = "Biometrics"
WS_FOOD = "Food_Log"
WS_HYDRATION = "Hydration"
WS_EXERCISE = "Workouts"
WS_CYCLE = "Cycle_Data"
WS_BLOOD = "Blood_Work"
WS_WEARABLE = "Wearable_Sync"

# --- Exercise calorie burn (kcal per minute per intensity unit) ---
CALORIE_RATES = {
    "functional": 0.9,
    "strength": 0.8,
    "cardio": 1.1,
}

# Hydration: extra ml per minute of exercise, scaled by intensity
HYDRATION_ML_PER_MIN_INTENSITY = 3.0

# Protein bump post-workout (grams)
PROTEIN_BUMP_GRAMS = 10

# Cycle phases
CYCLE_PHASES = ["follicular", "ovulation", "luteal", "menstrual"]
