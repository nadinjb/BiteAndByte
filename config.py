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
WS_FOOD_LIBRARY = "Food_Library"

# --- Activity level → PAL multipliers (Mifflin-St Jeor standard) ---
ACTIVITY_FACTORS: dict[str, float] = {
    "sedentary":         1.200,   # desk job, no exercise
    "lightly_active":    1.375,   # 1-3 days/week
    "moderately_active": 1.550,   # 3-5 days/week
    "very_active":       1.725,   # 6-7 days/week
}

# --- Goal → daily caloric delta (kcal) relative to TDEE ---
GOAL_DELTAS: dict[str, int] = {
    "cut":      -500,
    "maintain":    0,
    "bulk":      300,
}

# --- Protein targets (g per kg body weight) per goal ---
PROTEIN_RATES: dict[str, float] = {
    "cut":      2.2,   # higher protein preserves muscle in deficit
    "maintain": 2.0,
    "bulk":     1.8,
}

# --- Carb share of remaining (non-protein) calories per goal ---
CARB_SHARE: dict[str, float] = {
    "cut":      0.40,   # lower carbs on cut
    "maintain": 0.50,
    "bulk":     0.55,   # higher carbs on bulk
}

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
