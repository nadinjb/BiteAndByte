# BiteAndByte — Setup & Reference Guide

## 1. API Keys & Credentials

### 1a. Gemini API Key (Google AI Studio — Free Tier)

1. Go to [Google AI Studio](https://aistudio.google.com/)
2. Sign in with your Google account
3. Click **Get API Key** in the left sidebar
4. Click **Create API Key** → select or create a Google Cloud project
5. Copy the API key — this is your `GEMINI_API_KEY`

The bot uses **Gemini 2.5 Flash** for daily logging, food extraction, context-aware chat, and Reddit research. **Gemini 2.5 Pro** is reserved for weekly reviews and blood test analysis only (auto-falls back to Flash if Pro fails).

### 1b. Reddit API (Free Tier — optional)

1. Go to [Reddit App Preferences](https://www.reddit.com/prefs/apps)
2. Click **"create another app..."**
3. Name: `BiteAndByte`, Type: **script**
4. Redirect URI: `http://localhost:8080` (not used, but required)
5. Click **Create App**
6. Copy the **client ID** (under the app name) and **secret**

The `/research` command searches r/Biohacking, r/Nutrition, and r/Fitness for community insights and compares them to your personal health data. If Reddit credentials are not configured, the bot works normally — only `/research` will be unavailable.

## 2. Google Cloud & Sheets Setup

### Create a Google Cloud Project
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click **New Project** → name it `BiteAndByte` → **Create**

### Enable APIs
1. Go to **APIs & Services** → **Library**
2. Search and enable:
   - **Google Sheets API**
   - **Google Drive API**

### Create a Service Account
1. Go to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **Service Account**
3. Name: `biteandbyte-bot` → **Create and Continue**
4. Role: **Editor** → **Done**
5. Click the created service account → **Keys** tab
6. **Add Key** → **Create new key** → **JSON**
7. Save the downloaded file as `credentials.json` in the project root

### Create the Google Sheet
1. Go to [Google Sheets](https://sheets.google.com/) and create a new spreadsheet
2. Name it `BiteAndByte`
3. Copy the **Spreadsheet ID** from the URL:
   ```
   https://docs.google.com/spreadsheets/d/SPREADSHEET_ID_HERE/edit
   ```
4. **Share the spreadsheet** with the service account email
   (found in `credentials.json` → `client_email` field) — give **Editor** access

The bot will auto-create all 9 worksheet tabs on first use:

| Worksheet | Columns | Purpose |
|-----------|---------|---------|
| `User_Profiles` | user_id, name, age, gender, height_cm, initial_weight_kg | Profile data |
| `Food_Log` | user_id, date, item, calories, protein_g, carbs_g, fats_g | Meal entries |
| `Food_Cache` | user_id, item, grams, calories, protein_g, carbs_g, fats_g | Learned food corrections (Rule #3) |
| `Biometrics` | user_id, date, weight_kg, body_fat_pct, water_pct, bone_mass_kg, muscle_mass_kg | Body composition |
| `Hydration` | user_id, date, liters | Daily water intake (cumulative) |
| `Workouts` | user_id, date, type, duration_min, intensity, estimated_kcal | Exercise sessions |
| `Cycle_Data` | user_id, date, phase, notes | Menstrual cycle tracking |
| `Blood_Work` | user_id, date, glucose_mg_dl, hba1c_pct, cholesterol_total, hdl, ldl, triglycerides, iron, ferritin, vitamin_d, b12, tsh, crp, notes | Blood test results |
| `Wearable_Sync` | user_id, date, steps, sleep_hours, sleep_quality | Sleep & activity data |

## 3. Telegram Bot Setup

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the **bot token**

### Set Bot Commands
Send to BotFather after selecting your bot with `/setcommands`:
```
start - הגדרת פרופיל
food - רישום ארוחה (טקסט או תמונה)
water - רישום שתייה
workout - רישום אימון
scale - רישום מדידת משקל
cycle - רישום מחזור
blood - הזנת בדיקת דם
sleep - רישום שינה וצעדים
status - סטטוס יומי
review - סיכום שבועי AI
fix - תיקון רישום אוכל אחרון
correct - שמירת פריט לזיהוי עתידי
research - מחקר רדיט על נושא בריאותי
help - רשימת פקודות
cancel - ביטול פעולה
```

## 4. Install & Run

```bash
cd BiteAndByte

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your credentials:
#   TELEGRAM_BOT_TOKEN=...       (from @BotFather)
#   GOOGLE_SHEET_ID=...          (from spreadsheet URL)
#   GOOGLE_CREDENTIALS_FILE=...  (default: credentials.json)
#   GEMINI_API_KEY=...           (from Google AI Studio)
#   REDDIT_CLIENT_ID=...         (optional, from Reddit App Preferences)
#   REDDIT_CLIENT_SECRET=...     (optional, from Reddit App Preferences)

# Run the bot
python main.py
```

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `python-telegram-bot` | 21.6 | Telegram bot framework (async) |
| `gspread` | 6.1.4 | Google Sheets API client |
| `google-auth` | 2.36.0 | Google service account auth |
| `google-genai` | >= 1.14.0 | Gemini 2.5 API (2026 SDK) |
| `python-dotenv` | 1.0.1 | Load `.env` variables |
| `Pillow` | 11.1.0 | Image processing for photo analysis |
| `praw` | 7.8.1 | Reddit API client |

## 5. Commands Reference

| Short | Full | Description | Example |
|-------|------|-------------|---------|
| `/start` | | Profile setup (guided: name, age, gender, height, weight) | `/start` |
| `/food` | `/log_food` | Log food — text or photo (Gemini extracts, Python calculates) | `/food חזה עוף 200 גרם עם אורז` |
| `/water` | `/log_water` | Log water intake (cumulative per day) | `/water 0.5` |
| `/workout` | `/log_workout` | Log exercise (type, duration, intensity 1-10) | `/workout functional 45 7` |
| `/scale` | `/log_scale` | Log body composition (weight, fat%, water%, bone, muscle) | `/scale 75.2 18.5 55.3 3.1 35.8` |
| `/cycle` | `/log_cycle` | Log cycle phase with optional notes | `/cycle luteal עייפות קלה` |
| `/blood` | `/upload_blood` | Enter blood markers step-by-step (12 markers, skip/end anytime) | `/blood` |
| `/sleep` | `/log_wearable` | Log steps, sleep hours, sleep quality | `/sleep 8500 7.5 good` |
| `/status` | | Daily snapshot (BMR, TDEE, calories, protein, hydration, sleep, cycle) | `/status` |
| `/review` | | Weekly AI review — 7-day comprehensive summary (Gemini Pro) | `/review` |
| `/fix` | | Fix last food entry field (calories/protein/carbs/fats) | `/fix protein 25` |
| `/correct` | | Save corrected food item to Food Cache for future recognition | `/correct מולר 200 160 25 12 2` |
| `/research` | | Reddit research + personalized AI analysis | `/research creatine` |
| `/help` | | Show all available commands | `/help` |
| `/cancel` | | Cancel any active conversation | `/cancel` |

All `log_*` and `upload_blood` long-form commands still work alongside the short aliases.

### Photo Detection
Send a photo with one of these captions:
- **"אוכל"** or **"food"** — Food analysis (Gemini Flash Vision)
- **"דם"**, **"blood"**, or **"בדיקה"** — Blood test extraction (Gemini Pro Vision)
- **"משקל"**, **"scale"**, or **"מדידה"** — Scale screenshot extraction
- No caption — defaults to food analysis

### Free-text Chat (Context Injection)
Send any message without a command and the bot will answer based on your last **14 days** of data from all tabs (food, biometrics, hydration, exercise, sleep, cycle, blood work). The bot shows an immediate acknowledgment message and typing indicator while processing.

Examples:
- **"בוקר טוב"** — Daily briefing: last night's sleep, cycle phase, today's goals, hydration, planned workout
- **"למה אני עייפה?"** — Checks sleep hours/quality, iron levels, carb intake, cycle phase
- **"מה לאכול עכשיו?"** — Plans a meal based on remaining calories and protein target
- **"תסביר לי את בדיקות הדם"** — Explains blood results in plain Hebrew
- **"נשאר לי 500 קלוריות ו-40 גרם חלבון"** — Suggests what to eat

### Reddit Research
`/research <topic>` searches r/Biohacking, r/Nutrition, and r/Fitness for the top 10 most relevant threads from the past year. Extracts the top 5 comments per thread (min 2 upvotes, max 500 chars each). Gemini then compares the community advice to your personal data and returns a Hebrew summary:

- **Pros** — key benefits from community discussions
- **Cons & risks** — warnings and side effects mentioned
- **Community consensus** — what most people agree on, and where they disagree
- **Personal verdict** — tailored to your profile (blood work, weight, cycle, supplements)
- **Disclaimer** — notes this is community research, not medical advice

## 6. How It Works

### Pipeline
```
Gemini extracts → Python calculates → Gemini verbalizes
```
All math is done in Python (`insights.py`). Gemini never does math — it only extracts raw data and generates Hebrew verbal feedback from pre-calculated results.

### Food Extraction Rules
1. **Explicit Data Priority** — If the user states exact values ("25g protein", "300 calories"), those numbers are used as-is
2. **Brand Awareness** — Gemini recognizes brand names (Muller, PRO, Danone) and defaults to the high-protein variant
3. **Correction Learning** — Items saved via `/correct` go to `Food_Cache` and are auto-recognized next time

### Nutrition Lookup Priority
When calculating nutrition for a food item, the system checks in order:
1. **Explicit values** — User-provided numbers from the message
2. **Food Cache** — Previously corrected items per user (`Food_Cache` sheet)
3. **Local DB** — Built-in database of ~225 foods with per-100g values (`nutrition_db.py`)
4. **Generic estimate** — Fallback: 1.2 cal/g, 0.08g protein/g, 0.15g carbs/g, 0.05g fat/g

### Calculations (insights.py)

**BMR & TDEE:**
- BMR: Mifflin-St Jeor formula (weight, height, age, gender)
- TDEE: BMR * 1.2 + daily exercise calories (updates in real-time)

**Body Metrics:**
- BMI with Hebrew categories (underweight / normal / overweight / obese)
- 30-day composition deltas (weight, fat%, muscle, water%)

**Macro Targets (3 modes):**
- Maintain: 30% protein / 40% carbs / 30% fat
- Cut: TDEE - 300 cal, 35% protein / 35% carbs / 30% fat
- Bulk: TDEE + 300 cal, 30% protein / 45% carbs / 25% fat

**Exercise:**
- Calorie burn rates: functional 0.9, strength 0.8, cardio 1.1 (kcal/min per intensity unit)
- Post-workout protein bump: +10g for strength/functional workouts
- Extra hydration: 3ml per minute of exercise per intensity unit

**Hydration:**
- Base target: 2.5L/day
- Adjusted upward for exercise and cycle phase

**Blood Work (12 markers):**
- Glucose (70-100), HbA1c (< 5.7%), Total Cholesterol (< 200), HDL (> 40), LDL (< 100), Triglycerides (< 150), Iron (60-170), Ferritin (20-200), Vitamin D (30-100), B12 (200-900), TSH (0.4-4.0), CRP (< 3.0)
- Each marker flagged as high/low/normal

**Cycle Phase Adjustments:**

| Phase | Calories | Extra Water | Recommended Intensity | Notes |
|-------|----------|-------------|----------------------|-------|
| Follicular | +0 | +0.0L | High | Peak energy |
| Ovulation | +100 | +0.2L | Peak | Highest strength |
| Luteal | +200 | +0.3L | Moderate | Cravings normal, reduce intensity |
| Menstrual | +100 | +0.2L | Low-moderate | Extra iron, gentle movement |

**Sleep & Wearable:**
- Sleep deficit: target 7.5h, calculates gap
- Calorie adjustment based on sleep quality (poor: -200 kcal target)
- Intensity recommendation based on sleep quality + deficit
- Step count bonus: 10,000+ steps → additional calorie allowance

### UX Features
- **Immediate ACK** — Bot sends a temporary "analyzing..." message instantly
- **Typing indicator** — Shows "typing..." in Telegram while Gemini processes
- **Slow warning** — After 10s, edits message to "still processing..."
- **Message editing** — Final answer replaces the temp message (keeps chat clean)
- **Error recovery** — If Gemini fails, user sees a retry prompt instead of silence
- **Gemini retry** — Auto-retries on 429 rate limit (3 attempts, 6s/12s/18s backoff)
- **Pro → Flash fallback** — If Gemini Pro fails, automatically retries with Flash

## 7. Architecture

```
main.py             → Entry point, all Telegram handlers & bot wiring
config.py           → Environment vars, model names, constants
sheets_handler.py   → Google Sheets CRUD (9 auto-created worksheets)
gemini_client.py    → Gemini 2.5 Flash/Pro API (text + vision + retry)
insights.py         → All Python math (BMR, TDEE, macros, blood ranges, context builder)
nutrition_db.py     → Local food database (~225 foods, per-100g values)
reddit_research.py  → Reddit API via praw (search + extract top comments)
```

### Gemini Functions

| Function | Model | Purpose |
|----------|-------|---------|
| `extract_food_from_text()` | Flash | Extract food items + grams from text |
| `extract_food_from_photo()` | Flash | Extract food items from photo |
| `extract_blood_markers()` | Pro | Extract 12 blood markers from screenshot |
| `extract_scale_metrics()` | Flash | Extract body composition from scale photo |
| `generate_food_feedback()` | Flash | Verbal feedback on logged meal |
| `generate_workout_feedback()` | Flash | Post-workout encouragement + tips |
| `generate_blood_feedback()` | Pro | Detailed blood analysis explanation |
| `generate_scale_feedback()` | Flash | Body composition trends + BMI |
| `generate_wearable_feedback()` | Flash | Sleep insight + intensity recommendation |
| `generate_cycle_feedback()` | Flash | Phase-specific health adjustments |
| `generate_weekly_review()` | Pro | Comprehensive 7-day summary |
| `generate_status_feedback()` | Flash | Daily tip based on current status |
| `answer_with_context()` | Flash | Free-text Q&A with 14-day context |
| `analyze_reddit_research()` | Flash | Compare Reddit advice to personal data |

### Cost Optimization
- All math (BMR, TDEE, calorie burn, hydration, macros, blood ranges) calculated locally in Python
- Food Cache checked in Google Sheets before calling Gemini
- Daily logging, context chat, Reddit research → **Gemini 2.5 Flash** (fast, free tier)
- Weekly reviews & blood analysis → **Gemini 2.5 Pro** (complex, free tier)
- Reddit comments truncated to 500 chars, max 10 threads, 5 comments each → stays within token limits
- Gemini Pro auto-falls back to Flash on failure → no wasted retries

## 8. Running Tests

```bash
source venv/bin/activate
python -m pytest tests/ -v
```

Test coverage:
- `tests/test_insights.py` — BMR, TDEE, BMI, macros, blood ranges, cycle adjustments, wearable insights (50 tests)
- `tests/test_nutrition_db.py` — Food lookup, calculation, data integrity (22 tests)
- `tests/test_gemini_client.py` — JSON parsing edge cases (7 tests)

Total: **79 tests**
