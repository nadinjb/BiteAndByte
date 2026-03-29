# BiteAndByte — Setup Guide

## 1. Gemini API Key (Google AI Studio — Free Tier)

1. Go to [Google AI Studio](https://aistudio.google.com/)
2. Sign in with your Google account
3. Click **Get API Key** in the left sidebar
4. Click **Create API Key** → select or create a Google Cloud project
5. Copy the API key — this is your `GEMINI_API_KEY`

**Free tier includes:**
- Gemini 1.5 Flash: 15 RPM, 1M TPM, 1500 RPD
- Gemini 1.5 Pro: 2 RPM, 32K TPM, 50 RPD

The bot uses Flash for daily logging (fast, free) and Pro only for weekly reviews and blood test analysis.

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
- User_Profile, Biometric_Data, Food_Log, Hydration_Log
- Exercise_Log, Cycle_Tracking, Blood_Work, Wearable_Sync

## 3. Telegram Bot Setup

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the **bot token**

### Set Bot Commands (optional)
Send to BotFather after selecting your bot with `/setcommands`:
```
start - הגדרת פרופיל
log_food - רישום ארוחה (טקסט או תמונה)
log_water - רישום שתייה
log_workout - רישום אימון
log_scale - רישום מדידת משקל
log_cycle - רישום מחזור
upload_blood - הזנת בדיקת דם
log_wearable - רישום שינה וצעדים
status - סטטוס יומי
review - סיכום שבועי AI
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
python bot.py
```

## 5. Commands Reference

| Command | Description | Example |
|---------|-------------|---------|
| `/start` | Profile setup (guided) | `/start` |
| `/log_food` | Log food (text, Gemini analyzes) | `/log_food חזה עוף עם אורז` |
| Photo | Send food/blood/scale photo | Photo + caption "אוכל" |
| `/log_water` | Log water intake | `/log_water 0.5` |
| `/log_workout` | Log exercise | `/log_workout functional 45 7` |
| `/log_scale` | Log body composition | `/log_scale 75.2 18.5 55.3 3.1 35.8` |
| `/log_cycle` | Log cycle phase | `/log_cycle luteal` |
| `/upload_blood` | Enter blood markers (guided) | `/upload_blood` |
| `/log_wearable` | Log steps & sleep | `/log_wearable 8500 7.5 good` |
| `/status` | Daily snapshot | `/status` |
| `/review` | Weekly AI review (Gemini Pro) | `/review` |

### Photo Detection
Send a photo with one of these captions:
- **"אוכל"** or **"food"** → Food analysis (Gemini Vision)
- **"דם"** or **"blood"** → Blood test extraction (Gemini Pro Vision)
- **"משקל"** or **"scale"** → Scale screenshot extraction
- No caption → defaults to food analysis

## 6. Architecture

```
bot.py              → Entry point, handler wiring
config.py           → Environment vars, constants
sheets.py           → Google Sheets CRUD (8 worksheets)
gemini_client.py    → Gemini Flash/Pro API (text + vision)
insights.py         → Local BMR/TDEE math + Gemini-powered reviews
handlers.py         → Telegram command & photo handlers
```

**Cost optimization strategy:**
- BMR, TDEE, calorie burn, hydration goals → calculated locally in Python
- Food cache → checks Google Sheets before calling Gemini
- Daily logging → Gemini 1.5 Flash (free tier, fast)
- Weekly reviews & blood analysis → Gemini 1.5 Pro (complex, 50 RPD free)
