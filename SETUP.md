# BiteAndByte — Setup Guide

## 1. Gemini API Key (Google AI Studio — Free Tier)

1. Go to [Google AI Studio](https://aistudio.google.com/)
2. Sign in with your Google account
3. Click **Get API Key** in the left sidebar
4. Click **Create API Key** → select or create a Google Cloud project
5. Copy the API key — this is your `GEMINI_API_KEY`

The bot uses Gemini 2.5 Flash for daily logging (fast) and Gemini 2.5 Pro only for weekly reviews and blood test analysis.

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

The bot will auto-create all worksheet tabs on first use:
- User_Profiles, Biometrics, Food_Log, Hydration
- Workouts, Cycle_Data, Blood_Work, Wearable_Sync, Food_Cache

## 3. Telegram Bot Setup

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the **bot token**

### Set Bot Commands (optional)
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
# Edit .env with your tokens:
#   TELEGRAM_BOT_TOKEN=...
#   GOOGLE_SHEET_ID=...
#   GEMINI_API_KEY=...

# Run the bot
python main.py
```

## 5. Commands Reference

| Short | Full | Description | Example |
|-------|------|-------------|---------|
| `/start` | | Profile setup (guided) | `/start` |
| `/food` | `/log_food` | Log food (text or photo) | `/food חזה עוף עם אורז` |
| `/water` | `/log_water` | Log water intake | `/water 0.5` |
| `/workout` | `/log_workout` | Log exercise | `/workout functional 45 7` |
| `/scale` | `/log_scale` | Log body composition | `/scale 75.2 18.5 55.3 3.1 35.8` |
| `/cycle` | `/log_cycle` | Log cycle phase | `/cycle luteal` |
| `/blood` | `/upload_blood` | Enter blood markers (guided) | `/blood` |
| `/sleep` | `/log_wearable` | Log steps & sleep | `/sleep 8500 7.5 good` |
| `/status` | | Daily snapshot | `/status` |
| `/review` | | Weekly AI review (Gemini Pro) | `/review` |
| `/fix` | | Fix last food entry | `/fix protein 25` |
| `/correct` | | Save item to Food Cache | `/correct מולר 200 160 25 12 2` |
| `/help` | | Show all commands | `/help` |

### Photo Detection
Send a photo with one of these captions:
- **"אוכל"** or **"food"** — Food analysis (Gemini Vision)
- **"דם"** or **"blood"** — Blood test extraction (Gemini Pro Vision)
- **"משקל"** or **"scale"** — Scale screenshot extraction
- No caption — defaults to food analysis

### Free-text Chat
Send any message without a command and the bot will answer based on your last 14 days of data (food, sleep, cycle, workouts, weight, blood work).

## 6. Architecture

```
main.py             → Entry point, all Telegram handlers & bot wiring
config.py           → Environment vars, constants
sheets_handler.py   → Google Sheets CRUD (9 worksheets)
gemini_client.py    → Gemini 2.5 Flash/Pro API (text + vision)
insights.py         → Local BMR/TDEE math, context builder
nutrition_db.py     → Local food nutrition database (100+ foods)
```

**Pipeline:** Gemini extracts → Python calculates → Gemini verbalizes. All math is done in Python.

**Cost optimization strategy:**
- BMR, TDEE, calorie burn, hydration goals → calculated locally in Python
- Food cache → checks Google Sheets before calling Gemini
- Daily logging → Gemini 2.5 Flash (fast)
- Weekly reviews & blood analysis → Gemini 2.5 Pro (complex)
