import os
from dotenv import load_dotenv

load_dotenv()

# --- Tokens & credentials ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- Gemini models (cost optimization) ---
GEMINI_FLASH = "gemini-1.5-flash"   # Free-tier daily logging
GEMINI_PRO = "gemini-1.5-pro"       # Complex reviews & blood analysis

# --- Google Sheets worksheet names ---
WS_PROFILES = "User_Profile"
WS_BIOMETRICS = "Biometric_Data"
WS_FOOD = "Food_Log"
WS_HYDRATION = "Hydration_Log"
WS_EXERCISE = "Exercise_Log"
WS_CYCLE = "Cycle_Tracking"
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
