"""BiteAndByte — Bio-Hacking & Health Telegram Bot.

Powered by Gemini 2.5 Flash/Pro (google-genai SDK) + Google Sheets.

Pipeline: Gemini extracts → Python calculates → Gemini verbalizes.
All math is done in Python (insights.py). Gemini NEVER does math.
"""

import asyncio
import logging
import re

from telegram import Update
from telegram.error import BadRequest as TgBadRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.constants import ChatAction, ParseMode

import config
import sheets_handler as sheets
import insights
import gemini_client
import nutrition_db
import reddit_research

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conversation states
# ---------------------------------------------------------------------------

NAME, AGE, GENDER, HEIGHT, WEIGHT = range(5)
ACTIVITY_LEVEL = 7
GOAL = 8
FOOD_INPUT = 6
BLOOD_INPUT = 10


# ---------------------------------------------------------------------------
# Safe reply helper — falls back to plain text if Markdown fails
# ---------------------------------------------------------------------------

async def _safe_reply(message, text: str) -> None:
    try:
        await message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        plain = text.replace("*", "").replace("_", "")
        await message.reply_text(plain)


# ============================================================================
# /start — Profile setup
# ============================================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "👋 ברוכים הבאים ל-BiteAndByte — הסוכן האולטימטיבי לבריאות!\n\n"
        "בוא/י נגדיר את הפרופיל שלך.\n"
        "מה השם שלך?",
    )
    return NAME


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("מה הגיל שלך?")
    return AGE


async def get_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["age"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("⚠️ נא להזין מספר. מה הגיל שלך?")
        return AGE
    await update.message.reply_text("מה המין שלך? (male / female)")
    return GENDER


async def get_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    gender = update.message.text.strip().lower()
    if gender not in ("male", "female", "m", "f", "זכר", "נקבה"):
        await update.message.reply_text("⚠️ נא לבחור: male / female")
        return GENDER
    context.user_data["gender"] = gender
    await update.message.reply_text("מה הגובה שלך בסנטימטרים?")
    return HEIGHT


async def get_height(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["height_cm"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("⚠️ נא להזין מספר. גובה בס\"מ?")
        return HEIGHT
    await update.message.reply_text("מה המשקל ההתחלתי שלך בק\"ג?")
    return WEIGHT


async def get_weight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        weight = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("⚠️ נא להזין מספר. משקל בק\"ג?")
        return WEIGHT

    context.user_data["initial_weight_kg"] = weight
    await update.message.reply_text(
        "מה רמת הפעילות הגופנית שלך?\n\n"
        "1 — יושבני (עבודת משרד, כמעט ללא ספורט)\n"
        "2 — פעיל קלות (1-3 אימונים בשבוע)\n"
        "3 — פעיל מתון (3-5 אימונים בשבוע)\n"
        "4 — פעיל מאוד (6-7 אימונים בשבוע)\n\n"
        "כתוב/י מספר 1-4:"
    )
    return ACTIVITY_LEVEL


_ACTIVITY_LEVEL_MAP = {
    "1": "sedentary",
    "2": "lightly_active",
    "3": "moderately_active",
    "4": "very_active",
    "sedentary": "sedentary",
    "lightly_active": "lightly_active",
    "moderately_active": "moderately_active",
    "very_active": "very_active",
}

_ACTIVITY_LEVEL_HEB = {
    "sedentary": "יושבני",
    "lightly_active": "פעיל קלות",
    "moderately_active": "פעיל מתון",
    "very_active": "פעיל מאוד",
}


async def get_activity_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip().lower()
    activity = _ACTIVITY_LEVEL_MAP.get(raw)
    if not activity:
        await update.message.reply_text("⚠️ נא להזין מספר 1-4.")
        return ACTIVITY_LEVEL

    context.user_data["activity_level"] = activity
    await update.message.reply_text(
        "מה המטרה שלך?\n\n"
        "1 — ירידה במשקל (חיסרון קלורי של 500 קק\"ל)\n"
        "2 — שמירה על משקל\n"
        "3 — עלייה במסה (עודף של 300 קק\"ל)\n\n"
        "כתוב/י מספר 1-3:"
    )
    return GOAL


_GOAL_MAP = {
    "1": "cut", "cut": "cut",
    "2": "maintain", "maintain": "maintain",
    "3": "bulk", "bulk": "bulk",
}

_GOAL_HEB = {"cut": "ירידה במשקל", "maintain": "שמירה", "bulk": "עלייה במסה"}


async def get_goal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip().lower()
    goal = _GOAL_MAP.get(raw)
    if not goal:
        await update.message.reply_text("⚠️ נא להזין מספר 1-3.")
        return GOAL

    user_id = update.effective_user.id
    d = context.user_data
    weight = d["initial_weight_kg"]
    activity_level = d["activity_level"]

    sheets.save_profile(
        user_id=user_id, name=d["name"], age=d["age"], gender=d["gender"],
        height_cm=d["height_cm"], initial_weight_kg=weight,
        activity_level=activity_level, goal=goal,
    )

    # Calculate targets using the new engine (no Gemini)
    targets = insights.calculate_daily_targets(user_id)
    bmi = insights.calculate_bmi(weight, d["height_cm"])

    await update.message.reply_text(
        f"✅ הפרופיל נשמר!\n"
        f"👤 {d['name']} | גיל {d['age']} | {d['height_cm']:.0f}cm | {weight:.1f}kg\n"
        f"🏃 פעילות: {_ACTIVITY_LEVEL_HEB[activity_level]} | "
        f"🎯 מטרה: {_GOAL_HEB[goal]}\n\n"
        f"📊 *יעדים יומיים מחושבים:*\n"
        f"🔥 BMR: {targets['bmr']:.0f} קק\"ל\n"
        f"⚡ TDEE: {targets['tdee']:.0f} קק\"ל "
        f"(×{targets['activity_factor']} פעילות)\n"
        f"🍽️ יעד קלורי: {targets['calories']} קק\"ל/יום\n"
        f"🥩 חלבון: {targets['protein_g']}g "
        f"({targets['protein_per_kg']}g/kg)\n"
        f"🍚 פחמימות: {targets['carbs_g']}g | "
        f"🥑 שומן: {targets['fats_g']}g\n"
        f"📏 BMI: {bmi} ({insights.bmi_category(bmi)})\n\n"
        "💬 *פשוט כתוב/י לי בשפה רגילה!*\n"
        "/help לכל היכולות",
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ בוטל.")
    return ConversationHandler.END


# ============================================================================
# /help — Command reference
# ============================================================================

HELP_TEXT = (
    "🤖 *BiteAndByte — הסוכן החכם שלך לבריאות*\n\n"
    "פשוט כתוב/י בעברית — אני מבין הכל! 💬\n\n"
    "🍽️ *אוכל ושתייה*\n"
    "• \"אכלתי חזה עוף 200 גרם עם אורז\"\n"
    "• \"שתיתי שייק חלבון\"\n"
    "• שלח/י תמונה של הצלחת\n\n"
    "🏋️ *אימונים*\n"
    "• \"עשיתי 45 דקות כוח, היה חזק\"\n"
    "• \"ריצה קלה של חצי שעה\"\n\n"
    "💧 *שתייה*\n"
    "• \"שתיתי שתי כוסות מים\"\n"
    "• \"1.5 ליטר מים\"\n\n"
    "⚖️ *מדידות*\n"
    "• \"שקלתי 74.3 ק\"ג\"\n"
    "• שלח/י תמונת מסך מהמשקל\n\n"
    "🔄 *מחזור*\n"
    "• \"התחלתי שלב לוטאלי\"\n"
    "• \"יש לי ביוץ היום\"\n\n"
    "😴 *שינה*\n"
    "• \"ישנתי 7 שעות, שינה טובה, 8000 צעדים\"\n\n"
    "✏️ *תיקונים*\n"
    "• \"תתקן את חלב השקדים ל-39 קלוריות\"\n"
    "• \"זה היה 13 קל ולא 126, ל-300 מ\"ל\"\n\n"
    "📊 *דוחות ומחקר*\n"
    "/status — סטטוס יומי\n"
    "/review — סיכום שבועי\n"
    "/research <נושא> — מחקר Reddit + ניתוח אישי\n"
    "/blood — הזנת בדיקת דם\n\n"
    "❓ *שאלות*\n"
    "• \"למה אני עייפה?\"\n"
    "• \"כמה חלבון יש לי היום?\"\n"
    "• \"מה כדאי לאכול לארוחת ערב?\""
)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _safe_reply(update.message, HELP_TEXT)


# ============================================================================
# /log_food — 3-step: Gemini extracts → Python calculates → Gemini verbalizes
# ============================================================================

# Matches an explicit quantity in a food description, e.g. "300 מל", "200g", "1.5 ליטר"
_QUANTITY_RE = re.compile(
    r'\b(\d+\.?\d*)\s*'
    r'(גרם|g|מל|מ"ל|ml|cc|ליטר|l|ק"ג|kg)\b',
    re.IGNORECASE | re.UNICODE,
)


def _try_quick_parse(description: str, user_id: int) -> list[dict] | None:
    """Attempt to resolve a food description using only the local DB.

    Returns a minimal Gemini-compatible item list when confident, so the
    caller can skip the extract_food_from_text Gemini call entirely.

    Conditions for skipping Gemini:
    - Exactly one numeric quantity present (e.g. "300 גרם", "200ml")
    - The food name (description minus quantity) hits the local nutrition_db
      OR the fuzzy sheets lookup at ≥ 85% confidence

    Falls back to None for multi-item descriptions, ambiguous units (scoops),
    or when the item is not found locally — Gemini handles those.
    """
    quantities = _QUANTITY_RE.findall(description)
    if len(quantities) != 1:
        return None  # 0 or multiple quantities — too ambiguous

    grams = float(quantities[0][0])
    # Strip the quantity token from the description to isolate the food name
    food_name = _QUANTITY_RE.sub("", description).strip(" ,./–-")
    if not food_name:
        return None

    if nutrition_db.lookup(food_name) is not None:
        return [{"item": food_name, "grams": grams}]

    fuzzy = sheets.find_food_fuzzy(food_name, user_id=user_id, threshold=85)
    if fuzzy:
        return [{"item": food_name, "grams": grams}]

    return None

async def log_food_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    args = context.args
    if not args:
        await update.message.reply_text(
            "🍽️ מה אכלת? כתוב/י את הארוחה.\n"
            "דוגמה: חזה עוף 200 גרם עם אורז",
        )
        return FOOD_INPUT

    description = " ".join(args)
    await _process_food_text(update, description)
    return ConversationHandler.END


async def food_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    description = update.message.text.strip()
    if not description:
        await update.message.reply_text("⚠️ נא לכתוב מה אכלת.")
        return FOOD_INPUT
    await _process_food_text(update, description)
    return ConversationHandler.END


async def _process_food_text(
    update: Update, description: str, ack_msg=None,
) -> None:
    """3-step food pipeline: Gemini extracts → Python calculates → Gemini verbalizes.

    ack_msg: if provided (from unified NLP handler), edit it instead of sending a new one.
    """
    user_id = update.effective_user.id
    if ack_msg is None:
        await update.message.reply_text("🔎 מחפש במילון שלי ומנתח...")

    try:
        # STEP 1: Try local DB first — skips Gemini entirely when confident.
        # Falls back to Gemini for multi-item, ambiguous, or unknown descriptions.
        extracted = _try_quick_parse(description, user_id)
        if extracted is None:
            cached_items = sheets.lookup_food_cache(user_id, description)
            extracted = gemini_client.extract_food_from_text(
                description, cached_items=cached_items,
            )

        if not extracted or not isinstance(extracted, list):
            await update.message.reply_text(
                "⚠️ לא הצלחתי לזהות פריטי מזון. נסה/י שוב עם תיאור מפורט יותר.\n"
                "דוגמה: חזה עוף 200 גרם עם אורז"
            )
            return

        # STEP 2: Python CALCULATES (explicit > cache > DB > estimate)
        nutrition = insights.calculate_food_nutrition(extracted, user_id=user_id)

        if not nutrition["items"]:
            await update.message.reply_text(
                "⚠️ לא הצלחתי לחשב ערכים תזונתיים. נסה/י שוב."
            )
            return

        total = nutrition
        item_names = ", ".join(i.get("item", "?") for i in nutrition["items"])
        sheets.log_food(
            user_id, item_names,
            total["total_calories"], total["total_protein"],
            total["total_carbs"], total["total_fats"],
        )

        # Daily totals (Python math)
        today_food = [f for f in sheets.get_food(user_id, days=1) if f.get("date") == sheets.today()]
        daily_cal = sum(float(f.get("calories", 0)) for f in today_food)
        daily_pro = sum(float(f.get("protein_g", 0)) for f in today_food)
        tdee = insights.get_tdee_for_user(user_id)
        remaining = round(max(0, tdee - daily_cal))

        items_text = ""
        for item in nutrition["items"]:
            if item.get("explicit"):
                src = "📌 מדויק"
            elif item.get("source") == "cache":
                src = "📦 Cache"
            elif item.get("source") == "library":
                score = item.get("match_score", 0)
                src = f"📚 ספרייה ({score}%)"
            elif item.get("from_db"):
                src = "📗 DB"
            else:
                src = "📙 הערכה"
            cal = float(item.get("calories", 0) or 0)
            grams = float(item.get("grams", 0) or 0)
            items_text += (
                f"  • {item['item']} ({grams:.0f}g) — "
                f"{cal:.0f} קק\"ל [{src}]\n"
            )

        h_goal = insights.calculate_hydration_target(
            exercise_entries=sheets.get_exercise(user_id, days=1)
        )
        h_consumed = sum(
            float(r.get("liters", 0))
            for r in sheets.get_hydration(user_id, days=1)
        )
        h_status = f"{h_consumed:.1f} / {h_goal:.1f} ליטר"

        # STEP 3: Gemini VERBALIZES from pre-calculated data
        feedback = gemini_client.generate_food_feedback({
            "item": item_names,
            "grams": sum(float(i.get("grams", 0) or 0) for i in nutrition["items"]),
            "calories": total["total_calories"],
            "protein_g": total["total_protein"],
            "carbs_g": total["total_carbs"],
            "fats_g": total["total_fats"],
            "daily_total_cal": round(daily_cal),
            "daily_total_protein": round(daily_pro),
            "tdee": round(tdee),
            "remaining_cal": remaining,
            "hydration_status": h_status,
            "from_db": all(i.get("from_db") for i in nutrition["items"]),
        })

        msg = (
            f"✅ נרשם:\n{items_text}\n"
            f"📊 סה\"כ: {total['total_calories']:.0f} קק\"ל | "
            f"P {total['total_protein']:.0f}g | C {total['total_carbs']:.0f}g | "
            f"F {total['total_fats']:.0f}g\n\n"
            f"📈 יומי: {daily_cal:.0f} / {tdee:.0f} קק\"ל (נותרו {remaining})\n"
            f"🥩 חלבון: {daily_pro:.0f}g"
        )
        if feedback:
            msg += f"\n\n🤖 {feedback}"
        if nutrition.get("has_suspicious_estimates"):
            msg += (
                "\n\n⚠️ זה נראה לי קצת גבוה — הערכתי כי הפריט לא נמצא במילון שלי. "
                "אם הערכים שגויים, פשוט אמור/י לי: \"תתקן את X ל-Y קלוריות\" ואעדכן הכל."
            )
        await _safe_reply(update.message, msg)

    except Exception:
        logger.exception("Food processing failed for: %s", description)
        await update.message.reply_text(
            "⚠️ שגיאה בעיבוד הארוחה. נסה/י שוב.\n"
            "אם הבעיה חוזרת, נסה/י תיאור קצר יותר."
        )


# ============================================================================
# Photo handler — Gemini extracts → Python calculates → Gemini verbalizes
# ============================================================================

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caption = (update.message.caption or "").lower().strip()
    photo = update.message.photo[-1]
    file = await photo.get_file()
    image_bytes = bytes(await file.download_as_bytearray())
    user_id = update.effective_user.id

    if any(w in caption for w in ("דם", "blood", "בדיקה")):
        await _handle_blood_photo(update, user_id, image_bytes)
    elif any(w in caption for w in ("משקל", "scale", "מדידה")):
        await _handle_scale_photo(update, user_id, image_bytes)
    else:
        await _handle_food_photo(update, user_id, image_bytes)


async def _handle_food_photo(update: Update, user_id: int, image_bytes: bytes) -> None:
    await update.message.reply_text("📸 שלב 1/3: מזהה פריטי מזון...")

    extracted = gemini_client.extract_food_from_photo(image_bytes)

    await update.message.reply_text("🔢 שלב 2/3: מחשב ערכים תזונתיים...")

    nutrition = insights.calculate_food_nutrition(extracted)
    item_names = ", ".join(i.get("item", "?") for i in nutrition["items"])
    sheets.log_food(
        user_id, item_names,
        nutrition["total_calories"], nutrition["total_protein"],
        nutrition["total_carbs"], nutrition["total_fats"],
    )

    today_food = [f for f in sheets.get_food(user_id, days=1) if f.get("date") == sheets.today()]
    daily_cal = sum(float(f.get("calories", 0)) for f in today_food)
    tdee = insights.get_tdee_for_user(user_id)

    feedback = gemini_client.generate_food_feedback({
        "item": item_names,
        "grams": sum(i.get("grams", 0) for i in nutrition["items"]),
        "calories": nutrition["total_calories"],
        "protein_g": nutrition["total_protein"],
        "carbs_g": nutrition["total_carbs"],
        "fats_g": nutrition["total_fats"],
        "daily_total_cal": round(daily_cal),
        "daily_total_protein": round(sum(float(f.get("protein_g", 0)) for f in today_food)),
        "tdee": round(tdee),
        "remaining_cal": round(max(0, tdee - daily_cal)),
        "hydration_status": "",
        "from_db": all(i.get("from_db") for i in nutrition["items"]),
    })

    items_text = "\n".join(
        f"  • {i['item']} ({i['grams']:.0f}g) — {i['calories']:.0f} קק\"ל"
        for i in nutrition["items"]
    )
    msg = (
        f"✅ מהתמונה:\n{items_text}\n\n"
        f"📊 סה\"כ: {nutrition['total_calories']:.0f} קק\"ל\n"
        f"📈 יומי: {daily_cal:.0f} / {tdee:.0f} קק\"ל"
    )
    if feedback:
        msg += f"\n\n🤖 {feedback}"
    await _safe_reply(update.message, msg)


async def _handle_blood_photo(update: Update, user_id: int, image_bytes: bytes) -> None:
    await update.message.reply_text("🩸 שלב 1/3: מחלץ סמנים מהתמונה (Gemini Pro)...")

    markers = gemini_client.extract_blood_markers(image_bytes)
    clean = {k: v for k, v in markers.items() if v is not None and k != "_raw"}
    calculated = insights.calculate_blood_analysis(user_id, clean)

    await update.message.reply_text("🔢 שלב 2/3: בודק טווחים...")
    feedback = gemini_client.generate_blood_feedback(calculated)

    flags_text = "\n".join(calculated.get("flags", [])) or "אין חריגים"
    ok_text = "\n".join(calculated.get("ok", [])) or ""

    msg = f"🩸 בדיקת דם — {calculated.get('date', '?')}\n\nסמנים חריגים:\n{flags_text}\n\n"
    if ok_text:
        msg += f"תקינים:\n{ok_text}\n\n"
    msg += f"🤖 ניתוח:\n{feedback}"
    await _safe_reply(update.message, msg)


async def _handle_scale_photo(update: Update, user_id: int, image_bytes: bytes) -> None:
    await update.message.reply_text("⚖️ שלב 1/3: מחלץ נתונים מהמשקל...")

    raw = gemini_client.extract_scale_metrics(image_bytes)
    weight = float(raw.get("weight_kg", 0))
    if weight <= 0:
        await update.message.reply_text(
            "⚠️ לא זוהו ערכים.\nנסה/י: /log_scale 75.2 18.5 55.3 3.1 35.8"
        )
        return

    calculated = insights.calculate_scale_data(
        user_id, weight,
        float(raw.get("body_fat_pct", 0)),
        float(raw.get("water_pct", 0)),
        float(raw.get("bone_mass_kg", 0)),
        float(raw.get("muscle_mass_kg", 0)),
    )

    feedback = gemini_client.generate_scale_feedback(calculated)
    msg = (
        f"✅ נרשם: {weight}kg | BMI {calculated['bmi']} ({calculated['bmi_category']})\n\n"
        f"🤖 {feedback}"
    )
    await _safe_reply(update.message, msg)


# ============================================================================
# /log_water
# ============================================================================

async def log_water_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text("שימוש: /log_water <ליטרים>\nדוגמה: /log_water 0.5")
        return

    try:
        liters = float(args[0])
    except ValueError:
        await update.message.reply_text("⚠️ נא להזין מספר. דוגמה: /log_water 0.5")
        return

    user_id = update.effective_user.id
    sheets.log_hydration(user_id, liters)

    goal = insights.calculate_hydration_target(
        exercise_entries=sheets.get_exercise(user_id, days=1)
    )
    today_records = sheets.get_hydration(user_id, days=1)
    consumed = sum(float(r.get("liters", 0)) for r in today_records)
    remaining = max(0, goal - consumed)
    pct = round(consumed / max(goal, 0.1) * 100)

    if remaining <= 0:
        status = f"💧 שתית {consumed:.1f}L — עמדת ביעד ({goal:.1f}L)! 🎉"
    else:
        status = f"💧 {consumed:.1f} / {goal:.1f}L ({pct}%) — נשאר {remaining:.1f}L"

    await update.message.reply_text(f"✅ נרשמו {liters} ליטר מים.\n\n{status}")


# ============================================================================
# /log_workout
# ============================================================================

async def log_workout_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    usage = (
        "שימוש: /log_workout <סוג> <דקות> <עצימות 1-10>\n"
        "סוגים: functional, strength, cardio\n"
        "דוגמה: /log_workout functional 45 7"
    )
    args = context.args
    if not args or len(args) < 3:
        await update.message.reply_text(usage)
        return

    exercise_type = args[0].lower()
    if exercise_type not in config.CALORIE_RATES:
        await update.message.reply_text(
            f"⚠️ סוג לא מוכר: {exercise_type}\n"
            "אפשרויות: functional, strength, cardio"
        )
        return

    try:
        duration = int(args[1])
        intensity = int(args[2])
    except ValueError:
        await update.message.reply_text("⚠️ משך ועצימות חייבים להיות מספרים.\n" + usage)
        return

    if not 1 <= intensity <= 10:
        await update.message.reply_text("⚠️ עצימות: 1-10.")
        return

    user_id = update.effective_user.id
    calculated = insights.calculate_workout_data(user_id, exercise_type, duration, intensity)
    feedback = gemini_client.generate_workout_feedback(calculated)

    msg = (
        f"✅ אימון נרשם: {exercise_type}, {duration} דקות, עצימות {intensity}/10\n\n"
        f"🔥 קלוריות: {calculated['calories_burned']} קק\"ל\n"
        f"📊 TDEE מעודכן: {calculated['updated_tdee']:.0f} קק\"ל\n"
        f"💧 מים נוספים: +{calculated['extra_water_l']}L\n"
    )
    if calculated["protein_bump_g"] > 0:
        msg += f"🥩 חלבון נוסף: +{calculated['protein_bump_g']}g\n"
    if feedback:
        msg += f"\n🤖 {feedback}"
    await _safe_reply(update.message, msg)


# ============================================================================
# /log_scale — Manual entry
# ============================================================================

async def log_scale_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    usage = (
        "שימוש: /log_scale <משקל> <שומן%> <מים%> <עצם> <שריר>\n"
        "דוגמה: /log_scale 75.2 18.5 55.3 3.1 35.8\n"
        "או שלח/י צילום מסך עם הכיתוב 'משקל'"
    )
    args = context.args
    if not args or len(args) < 5:
        await update.message.reply_text(usage)
        return

    try:
        weight, fat, water, bone, muscle = [float(a) for a in args[:5]]
    except ValueError:
        await update.message.reply_text("⚠️ כל הערכים חייבים להיות מספרים.\n" + usage)
        return

    user_id = update.effective_user.id
    calculated = insights.calculate_scale_data(user_id, weight, fat, water, bone, muscle)
    feedback = gemini_client.generate_scale_feedback(calculated)

    msg = (
        f"✅ נרשם: {weight}kg | שומן {fat}% | שריר {muscle}kg\n"
        f"📏 BMI: {calculated['bmi']} ({calculated['bmi_category']})\n\n"
        f"🤖 {feedback}"
    )
    await _safe_reply(update.message, msg)


# ============================================================================
# /log_cycle
# ============================================================================

async def log_cycle_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    usage = (
        "שימוש: /log_cycle <שלב> [הערות]\n"
        "שלבים: follicular, ovulation, luteal, menstrual\n"
        "דוגמה: /log_cycle luteal עייפות קלה"
    )
    args = context.args
    if not args:
        await update.message.reply_text(usage)
        return

    phase = args[0].lower()
    if phase not in config.CYCLE_PHASES:
        await update.message.reply_text(
            f"⚠️ שלב לא מוכר: {phase}\nאפשרויות: {', '.join(config.CYCLE_PHASES)}"
        )
        return

    notes = " ".join(args[1:]) if len(args) > 1 else ""
    user_id = update.effective_user.id
    sheets.log_cycle(user_id, phase, notes)

    adjustments = insights.get_cycle_adjustments(phase)
    calculated = {"phase": phase, **adjustments}
    feedback = gemini_client.generate_cycle_feedback(calculated)

    msg = (
        f"✅ שלב מחזור: {phase}\n\n"
        f"📊 התאמות מחושבות:\n"
        f"🔥 קלוריות: {adjustments['calorie_adjustment']:+d} קק\"ל\n"
        f"💧 מים נוספים: +{adjustments['water_adjustment_l']}L\n"
        f"🏋️ עצימות מומלצת: {adjustments['recommended_intensity']}\n"
        f"⚖️ {adjustments['weight_fluctuation_note']}\n"
        f"🩸 {adjustments['iron_note']}\n\n"
        f"🤖 {feedback}"
    )
    await _safe_reply(update.message, msg)


# ============================================================================
# /upload_blood — Manual guided entry
# ============================================================================

BLOOD_MARKERS = [
    ("glucose_mg_dl", "גלוקוז בצום (mg/dL)"),
    ("hba1c_pct", "HbA1c (%)"),
    ("cholesterol_total", "כולסטרול כללי"),
    ("hdl", "HDL"),
    ("ldl", "LDL"),
    ("triglycerides", "טריגליצרידים"),
    ("iron", "ברזל"),
    ("ferritin", "פריטין"),
    ("vitamin_d", "ויטמין D"),
    ("b12", "ויטמין B12"),
    ("tsh", "TSH"),
    ("crp", "CRP"),
]


async def upload_blood_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["blood_markers"] = {}
    context.user_data["blood_idx"] = 0
    _, marker_heb = BLOOD_MARKERS[0]
    await update.message.reply_text(
        "🩸 הזנת בדיקת דם\n\n"
        "💡 אפשר גם לשלוח צילום מסך עם הכיתוב 'דם'\n\n"
        "הזן/י ערך, 'דלג' לדילוג, 'סיום' לסיום מוקדם.\n\n"
        f"📌 {marker_heb}:",
    )
    return BLOOD_INPUT


async def blood_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    idx = context.user_data.get("blood_idx", 0)
    markers = context.user_data.get("blood_markers", {})

    if text.lower() in ("סיום", "done", "end"):
        return await _save_blood_manual(update, context, markers)

    if text.lower() not in ("דלג", "skip", "-"):
        marker_key = BLOOD_MARKERS[idx][0]
        try:
            markers[marker_key] = float(text)
        except ValueError:
            await update.message.reply_text("⚠️ מספר, 'דלג', או 'סיום'.")
            return BLOOD_INPUT

    idx += 1
    context.user_data["blood_idx"] = idx
    context.user_data["blood_markers"] = markers

    if idx >= len(BLOOD_MARKERS):
        return await _save_blood_manual(update, context, markers)

    _, marker_heb = BLOOD_MARKERS[idx]
    await update.message.reply_text(f"📌 {marker_heb}:")
    return BLOOD_INPUT


async def _save_blood_manual(update: Update, context: ContextTypes.DEFAULT_TYPE, markers: dict) -> int:
    user_id = update.effective_user.id
    calculated = insights.calculate_blood_analysis(user_id, markers)
    feedback = gemini_client.generate_blood_feedback(calculated)

    flags_text = "\n".join(calculated.get("flags", [])) or "🎉 הכל תקין!"
    msg = f"🩸 בדיקת דם נשמרה\n\n{flags_text}\n\n🤖 ניתוח:\n{feedback}"
    await _safe_reply(update.message, msg)
    return ConversationHandler.END


# ============================================================================
# /log_wearable
# ============================================================================

async def log_wearable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    usage = (
        "שימוש: /log_wearable <צעדים> <שעות שינה> <איכות>\n"
        "איכות: good, fair, poor\n"
        "דוגמה: /log_wearable 8500 7.5 good"
    )
    args = context.args
    if not args or len(args) < 3:
        await update.message.reply_text(usage)
        return

    try:
        steps = int(args[0])
        sleep_hours = float(args[1])
    except ValueError:
        await update.message.reply_text("⚠️ צעדים ושעות חייבים להיות מספרים.\n" + usage)
        return

    sleep_quality = args[2].lower()
    if sleep_quality not in ("good", "fair", "poor"):
        await update.message.reply_text("⚠️ איכות: good / fair / poor")
        return

    user_id = update.effective_user.id
    sheets.log_wearable(user_id, steps, sleep_hours, sleep_quality)

    calculated = insights.calculate_wearable_insights(sleep_hours, sleep_quality, steps)
    feedback = gemini_client.generate_wearable_feedback(calculated)

    msg = (
        f"✅ נרשם: {steps} צעדים | {sleep_hours}h שינה ({sleep_quality})\n\n"
        f"📊 מחושב:\n"
        f"😴 גירעון שינה: {calculated['sleep_deficit']}h\n"
        f"🏋️ עצימות מומלצת: {calculated['recommended_intensity']}\n"
        f"🔥 התאמת קלוריות: {calculated['calorie_adjustment']:+d} קק\"ל\n\n"
        f"🤖 {feedback}"
    )
    await _safe_reply(update.message, msg)


# ============================================================================
# /status
# ============================================================================

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    calculated = insights.calculate_daily_status(user_id)

    if not calculated:
        await update.message.reply_text("⚠️ לא נמצא פרופיל. הפעל/י /start")
        return

    tip = gemini_client.generate_status_feedback(calculated)

    msg = (
        f"📊 סטטוס יומי — {calculated['date']}\n"
        f"👤 {calculated['name']}\n\n"
        f"🔥 BMR: {calculated['bmr']:.0f} | TDEE: {calculated['tdee']:.0f} קק\"ל\n"
        f"🍽️ קלוריות: {calculated['total_cal']:.0f} / {calculated['tdee']:.0f} "
        f"(נותרו {calculated['remaining_cal']})\n"
        f"🥩 חלבון: {calculated['protein_status']}\n"
        f"💧 שתייה: {calculated['hydration_pct']}% מהיעד\n"
        f"🏋️ אימון: {calculated['exercise_today']}\n"
        f"😴 שינה: {calculated['sleep_note']}\n"
        f"🔄 מחזור: {calculated['cycle_note']}\n\n"
        f"💡 {tip}"
    )
    await _safe_reply(update.message, msg)


# ============================================================================
# /review
# ============================================================================

async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    profile = sheets.get_profile(user_id)
    if not profile:
        await update.message.reply_text("⚠️ לא נמצא פרופיל. הפעל/י /start")
        return

    await update.message.reply_text("🔢 מחשב נתונים שבועיים...")
    calculated = insights.calculate_weekly_review(user_id)

    await update.message.reply_text("🤖 Gemini Pro כותב סיכום...")
    review = gemini_client.generate_weekly_review(calculated)

    await _safe_reply(update.message, review)


# ============================================================================
# /fix — Update the last Food_Log entry
# ============================================================================

async def fix_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "איזה שדה תרצה/י לתקן ברישום האחרון?\n"
            "למשל: /fix calories 39  או  /fix protein 25"
        )
        return

    field = args[0].lower()
    if field not in ("calories", "protein", "carbs", "fats"):
        await update.message.reply_text(
            f"לא הכרתי את השדה \"{field}\".\n"
            "אפשרויות: calories, protein, carbs, fats"
        )
        return

    try:
        value = float(args[1])
    except ValueError:
        await update.message.reply_text("⚠️ הערך חייב להיות מספר.")
        return

    user_id = update.effective_user.id
    updated = sheets.fix_last_food_entry(user_id, field, value)

    if not updated:
        await update.message.reply_text("לא מצאתי רישום אוכל לעדכון — נסה/י לרשום ארוחה קודם.")
        return

    heb_field = {"calories": "קלוריות", "protein": "חלבון", "carbs": "פחמימות", "fats": "שומן"}
    item_name = updated.get("item", "?")
    await update.message.reply_text(
        f"✅ עודכן! {item_name} — {heb_field[field]}: {value:.0f}\n\n"
        f"💡 רוצה שאזכור את הערכים לפעם הבאה? פשוט כתוב/י לי את הפרטים המלאים."
    )


# ============================================================================
# /correct — Save corrected food item to Food_Cache (Rule #3)
# ============================================================================

async def correct_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args or len(args) < 6:
        await update.message.reply_text(
            "אפשר גם לכתוב לי בשפה חופשית — לדוגמה:\n"
            "\"תתקן חלב שקדים 300 מ\"ל — 39 קל, 1.2 חלבון, 1.5 פחמ, 3.3 שומן\"\n\n"
            "או בפורמט מהיר: /correct <שם> <גרמים> <קל> <חלבון> <פחמ> <שומן>"
        )
        return

    item_name = args[0]
    try:
        grams = float(args[1])
        calories = float(args[2])
        protein = float(args[3])
        carbs = float(args[4])
        fats = float(args[5])
    except ValueError:
        await update.message.reply_text("⚠️ כל הערכים חייבים להיות מספרים.")
        return

    user_id = update.effective_user.id

    # Save to user's personal Food_Cache (per-serving)
    sheets.save_food_cache(user_id, item_name, grams, calories, protein, carbs, fats)

    # Save to global Food_Library (per-100g) so all users benefit
    if grams > 0:
        factor = 100.0 / grams
        sheets.save_to_library(
            item_name,
            round(calories * factor, 1),
            round(protein * factor, 1),
            round(carbs * factor, 1),
            round(fats * factor, 1),
        )

    # Update last Food_Log entry with the corrected values
    sheets.update_last_log(user_id, {
        "calories": calories,
        "protein": protein,
        "carbs": carbs,
        "fats": fats,
    })

    await update.message.reply_text(
        f"הבנתי! ✅ עדכנתי את הלוג וגם שמרתי לעצמי במילון "
        f"ש\"{item_name}\" זה {calories:.0f} קלוריות ל-{grams:.0f}g. לא אשאל שוב.\n\n"
        f"📚 {item_name} ({grams:.0f}g):\n"
        f"   🔥 {calories:.0f} קק\"ל | P {protein:.0f}g | C {carbs:.0f}g | F {fats:.0f}g"
    )


# ============================================================================
# /research — Reddit community research with personal analysis
# ============================================================================

async def research_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    if not config.REDDIT_CLIENT_ID:
        await update.message.reply_text("⚠️ Reddit API לא מוגדר. הוסף/י REDDIT_CLIENT_ID ל-.env")
        return

    profile = sheets.get_profile(user_id)
    if not profile:
        await update.message.reply_text("⚠️ לא נמצא פרופיל. הפעל/י /start")
        return

    topic = " ".join(context.args) if context.args else ""
    if not topic:
        await update.message.reply_text(
            "שימוש: /research <נושא>\n"
            "דוגמה: /research creatine\n"
            "דוגמה: /research intermittent fasting\n"
            "דוגמה: /research magnesium supplement"
        )
        return

    # 1. Immediate ACK
    ack_msg = await update.message.reply_text(
        f"🔎 מחפש דיונים על *{topic}* ב-Reddit...",
        parse_mode=ParseMode.MARKDOWN,
    )

    # 2. Typing indicator + slow warning
    typing_task = asyncio.create_task(
        _typing_loop(update.effective_chat.id, context.bot)
    )
    warning_task = asyncio.create_task(_slow_warning(ack_msg))

    try:
        # 3. Fetch Reddit threads (praw is synchronous — run in executor)
        loop = asyncio.get_running_loop()
        threads = await loop.run_in_executor(
            None, reddit_research.search_reddit, topic,
        )

        if not threads:
            typing_task.cancel()
            warning_task.cancel()
            await ack_msg.edit_text(f"לא נמצאו דיונים רלוונטיים על '{topic}' ברדיט.")
            return

        await ack_msg.edit_text(
            f"📚 נמצאו {len(threads)} דיונים. מנתח עם Gemini..."
        )

        # 4. Build personal context + format Reddit data
        user_context = insights.build_user_context(user_id)
        reddit_data = reddit_research.format_reddit_data(threads)

        # 5. Gemini analysis (also synchronous — run in executor)
        analysis = await loop.run_in_executor(
            None,
            gemini_client.analyze_reddit_research,
            topic, reddit_data, user_context,
        )
    except Exception:
        logger.exception("Reddit research failed for topic: %s", topic)
        typing_task.cancel()
        warning_task.cancel()
        await ack_msg.edit_text("⚠️ שגיאה בחיפוש ברדיט. נסה/י שוב מאוחר יותר.")
        return

    # 6. Edit ACK with final answer
    typing_task.cancel()
    warning_task.cancel()
    await _edit_safe(ack_msg, analysis)


# ============================================================================
# NLP dispatch helpers — called by unified free_text_handler
# ============================================================================

async def _process_workout_nlp(
    update: Update, data: dict, ack_msg,
) -> None:
    exercise_type = str(data.get("type") or "functional").lower()
    if exercise_type not in config.CALORIE_RATES:
        exercise_type = "functional"
    try:
        duration = int(data.get("duration_min") or 0)
        intensity = max(1, min(10, int(data.get("intensity") or 6)))
    except (TypeError, ValueError):
        duration, intensity = 0, 6

    if duration <= 0:
        await ack_msg.edit_text("כמה דקות נמשך האימון?")
        return

    user_id = update.effective_user.id
    calculated = insights.calculate_workout_data(user_id, exercise_type, duration, intensity)
    feedback = gemini_client.generate_workout_feedback(calculated)

    msg = (
        f"✅ אימון נרשם: {exercise_type}, {duration} דקות, עצימות {intensity}/10\n"
        f"🔥 {calculated['calories_burned']} קק\"ל | 💧 +{calculated['extra_water_l']}L מים"
    )
    if calculated.get("protein_bump_g", 0) > 0:
        msg += f" | 🥩 +{calculated['protein_bump_g']}g חלבון"
    if feedback:
        msg += f"\n\n🤖 {feedback}"
    await _edit_safe(ack_msg, msg)


async def _process_water_nlp(
    update: Update, data: dict, ack_msg,
) -> None:
    try:
        liters = float(data.get("liters") or 0)
    except (TypeError, ValueError):
        liters = 0.0

    if liters <= 0:
        await ack_msg.edit_text("כמה שתית? (למשל: כוס מים, 500 מ\"ל, ליטר)")
        return

    user_id = update.effective_user.id
    sheets.log_hydration(user_id, liters)
    goal = insights.calculate_hydration_target(
        exercise_entries=sheets.get_exercise(user_id, days=1)
    )
    consumed = sum(float(r.get("liters", 0)) for r in sheets.get_hydration(user_id, days=1))
    remaining = max(0.0, goal - consumed)
    pct = round(consumed / max(goal, 0.1) * 100)

    if remaining <= 0:
        status = f"💧 שתית {consumed:.1f}L — עמדת ביעד ({goal:.1f}L)! 🎉"
    else:
        status = f"💧 {consumed:.1f} / {goal:.1f}L ({pct}%) — נשאר {remaining:.1f}L"

    await ack_msg.edit_text(f"✅ נרשמו {liters:.2g}L מים.\n\n{status}")


async def _process_scale_nlp(
    update: Update, data: dict, ack_msg,
) -> None:
    try:
        weight = float(data.get("weight_kg") or 0)
    except (TypeError, ValueError):
        weight = 0.0

    if weight <= 0:
        await ack_msg.edit_text("כמה שקלת? (למשל: 74.3 ק\"ג)")
        return

    def _f(key):
        try:
            return float(data.get(key) or 0)
        except (TypeError, ValueError):
            return 0.0

    user_id = update.effective_user.id
    calculated = insights.calculate_scale_data(
        user_id, weight, _f("body_fat_pct"), _f("water_pct"),
        _f("bone_mass_kg"), _f("muscle_mass_kg"),
    )
    feedback = gemini_client.generate_scale_feedback(calculated)
    msg = (
        f"✅ נרשם: {weight}kg | BMI {calculated['bmi']} ({calculated['bmi_category']})\n\n"
        f"🤖 {feedback}"
    )
    await _edit_safe(ack_msg, msg)


async def _process_cycle_nlp(
    update: Update, data: dict, ack_msg,
) -> None:
    phase = str(data.get("phase") or "").lower()
    if phase not in config.CYCLE_PHASES:
        await ack_msg.edit_text(
            "באיזה שלב את? זקיק / ביוץ / לוטאלי / מחזור"
        )
        return

    notes = str(data.get("notes") or "")
    user_id = update.effective_user.id
    sheets.log_cycle(user_id, phase, notes)
    adjustments = insights.get_cycle_adjustments(phase)
    feedback = gemini_client.generate_cycle_feedback({"phase": phase, **adjustments})
    msg = (
        f"✅ שלב מחזור: {phase}\n"
        f"🔥 {adjustments['calorie_adjustment']:+d} קק\"ל | 💧 +{adjustments['water_adjustment_l']}L\n\n"
        f"🤖 {feedback}"
    )
    await _edit_safe(ack_msg, msg)


async def _process_sleep_nlp(
    update: Update, data: dict, ack_msg,
) -> None:
    def _i(key, default=0):
        try:
            return int(data.get(key) or default)
        except (TypeError, ValueError):
            return default

    def _f(key, default=0.0):
        try:
            return float(data.get(key) or default)
        except (TypeError, ValueError):
            return default

    steps = _i("steps")
    sleep_hours = _f("sleep_hours")
    quality = str(data.get("sleep_quality") or "fair").lower()
    if quality not in ("good", "fair", "poor"):
        quality = "fair"

    if sleep_hours <= 0 and steps <= 0:
        await ack_msg.edit_text("כמה שעות ישנת? (למשל: 7 שעות, שינה טובה)")
        return

    user_id = update.effective_user.id
    sheets.log_wearable(user_id, steps, sleep_hours, quality)
    calculated = insights.calculate_wearable_insights(sleep_hours, quality, steps)
    feedback = gemini_client.generate_wearable_feedback(calculated)
    msg = (
        f"✅ נרשם: {steps:,} צעדים | {sleep_hours:.1f}h שינה ({quality})\n\n"
        f"🤖 {feedback}"
    )
    await _edit_safe(ack_msg, msg)


async def _process_correction_nlp(
    update: Update, data: dict, ack_msg,
) -> None:
    user_id = update.effective_user.id
    item = str(data.get("item") or "")

    def _val(key):
        v = data.get(key)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    calories = _val("calories")
    protein_g = _val("protein_g")
    carbs_g = _val("carbs_g")
    fats_g = _val("fats_g")
    grams = _val("grams")

    updates: dict = {}
    if calories is not None:
        updates["calories"] = calories
    if protein_g is not None:
        updates["protein"] = protein_g
    if carbs_g is not None:
        updates["carbs"] = carbs_g
    if fats_g is not None:
        updates["fats"] = fats_g

    if not updates:
        await ack_msg.edit_text(
            "לא הצלחתי לחלץ ערכים לתיקון.\n"
            "נסה/י: \"תתקן חלב שקדים 300 מ\"ל — 39 קל, 1.2 חלבון\""
        )
        return

    updated = sheets.update_last_log(user_id, updates)

    # Save to Food_Library only if we have full nutritional profile + grams
    saved_to_library = False
    if (grams and grams > 0 and
            calories is not None and protein_g is not None and
            carbs_g is not None and fats_g is not None):
        factor = 100.0 / grams
        sheets.save_food_cache(user_id, item, grams, calories, protein_g, carbs_g, fats_g)
        sheets.save_to_library(
            item,
            round(calories * factor, 1),
            round(protein_g * factor, 1),
            round(carbs_g * factor, 1),
            round(fats_g * factor, 1),
        )
        saved_to_library = True

    if saved_to_library:
        msg = (
            f"הבנתי! ✅ עדכנתי את הלוג וגם שמרתי לעצמי במילון "
            f"ש\"{item}\" זה {calories:.0f} קלוריות ל-{grams:.0f}g. לא אשאל שוב."
        )
    else:
        fields_heb = {
            "calories": "קלוריות", "protein": "חלבון",
            "carbs": "פחמימות", "fats": "שומן",
        }
        update_str = " | ".join(
            f"{fields_heb.get(k, k)}: {v:.0f}" for k, v in updates.items()
        )
        item_name = (updated.get("item", "") if updated else "") or item or "הרישום האחרון"
        msg = f"✅ עודכן {item_name}:\n{update_str}"

    await ack_msg.edit_text(msg)


# ============================================================================
# Free-text handler — Context Injection (catch-all, must be registered LAST)
# ============================================================================

def _is_not_modified(exc: Exception) -> bool:
    return "message is not modified" in str(exc).lower()


async def _edit_safe(msg, text: str) -> None:
    """Edit a message with Markdown, falling back to plain text.

    Silently ignores Telegram 400 'Message is not modified' — this happens
    when the slow-warning already set the same text, or a double-edit race.
    """
    try:
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    except TgBadRequest as e:
        if _is_not_modified(e):
            return
        plain = text.replace("*", "").replace("_", "")
        try:
            await msg.edit_text(plain)
        except TgBadRequest as e2:
            if not _is_not_modified(e2):
                logger.warning("edit_text failed: %s", e2)
        except Exception:
            pass
    except Exception:
        plain = text.replace("*", "").replace("_", "")
        try:
            await msg.edit_text(plain)
        except Exception:
            pass


async def _typing_loop(chat_id, bot) -> None:
    """Send 'typing...' action every 4s until cancelled."""
    try:
        while True:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass


async def _slow_warning(ack_msg, delay: float = 10.0) -> None:
    """Edit ACK message with a 'still working' notice after *delay* seconds."""
    try:
        await asyncio.sleep(delay)
        await ack_msg.edit_text(
            "⏳ המערכת עמוסה מעט, אבל אני עדיין מעבד את התשובה עבורך..."
        )
    except (asyncio.CancelledError, TgBadRequest):
        pass


async def free_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unified NLP handler — classifies intent, dispatches to the right action."""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    profile = sheets.get_profile(user_id)
    if not profile:
        await update.message.reply_text(
            "👋 היי! נראה שזו פעם ראשונה שלנו.\nהפעל/י /start כדי להגדיר את הפרופיל שלך."
        )
        return

    # Merge with pending follow-up context (e.g. user answered "45 דקות")
    pending = context.user_data.pop("pending_nlp", None)
    if pending:
        text = pending.get("original_text", "") + ". " + text

    # 1. Immediate ACK
    ack_msg = await update.message.reply_text("🔎 מחפש במילון שלי ומנתח...")

    # 2. Typing + slow-warning tasks
    typing_task = asyncio.create_task(
        _typing_loop(update.effective_chat.id, context.bot)
    )
    warning_task = asyncio.create_task(_slow_warning(ack_msg))

    try:
        # 3. Classify intent (fast — Gemini Flash, no user_context)
        intent_result = gemini_client.classify_intent(text)
        intent = intent_result.get("intent", "answer_question")
        data = intent_result.get("data", {})
        missing = intent_result.get("missing_fields", [])
        follow_up = intent_result.get("follow_up")

        typing_task.cancel()
        warning_task.cancel()

        # 4. If required fields are missing, ask a natural follow-up question
        if missing and follow_up:
            context.user_data["pending_nlp"] = {**intent_result, "original_text": text}
            await ack_msg.edit_text(follow_up)
            return

        # 5. Dispatch to the appropriate action
        if intent == "log_food":
            description = data.get("description") or text
            await ack_msg.edit_text("🔍 מזהה פריטי מזון ומחשב...")
            await _process_food_text(update, description, ack_msg=ack_msg)

        elif intent == "log_workout":
            await _process_workout_nlp(update, data, ack_msg)

        elif intent == "log_water":
            await _process_water_nlp(update, data, ack_msg)

        elif intent == "log_scale":
            await _process_scale_nlp(update, data, ack_msg)

        elif intent == "log_cycle":
            await _process_cycle_nlp(update, data, ack_msg)

        elif intent == "log_sleep":
            await _process_sleep_nlp(update, data, ack_msg)

        elif intent == "correct_food":
            await _process_correction_nlp(update, data, ack_msg)

        elif intent == "status":
            calculated = insights.calculate_daily_status(user_id)
            if not calculated:
                await ack_msg.edit_text("⚠️ לא נמצא פרופיל. הפעל/י /start")
                return
            tip = gemini_client.generate_status_feedback(calculated)
            msg = (
                f"📊 סטטוס יומי — {calculated['date']}\n"
                f"🔥 קלוריות: {calculated['total_cal']:.0f} / {calculated['tdee']:.0f} "
                f"(נותרו {calculated['remaining_cal']})\n"
                f"🥩 {calculated['protein_status']}\n"
                f"💧 שתייה: {calculated['hydration_pct']}%\n\n"
                f"💡 {tip}"
            )
            await _edit_safe(ack_msg, msg)

        elif intent == "review":
            calculated = insights.calculate_weekly_review(user_id)
            await ack_msg.edit_text("🤖 Gemini Pro כותב סיכום...")
            review = gemini_client.generate_weekly_review(calculated)
            await _edit_safe(ack_msg, review)

        else:
            # answer_question — full 14-day context
            user_context = insights.build_user_context(user_id)
            answer = gemini_client.answer_with_context(text, user_context)
            await _edit_safe(ack_msg, answer)

    except Exception:
        logger.exception("NLP handler failed for: %s", text)
        typing_task.cancel()
        warning_task.cancel()
        try:
            await ack_msg.edit_text("⚠️ לא הצלחתי לעבד את ההודעה. נסה/י שוב.")
        except Exception:
            pass


# ============================================================================
# Bot wiring
# ============================================================================

def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set. Check your .env file.")
    if not config.GOOGLE_SHEET_ID:
        raise SystemExit("GOOGLE_SHEET_ID is not set. Check your .env file.")
    if not config.GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY is not set. Check your .env file.")

    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()

    # --- Conversation handlers ---

    profile_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_age)],
            GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_gender)],
            HEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_height)],
            WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_weight)],
            ACTIVITY_LEVEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_activity_level)],
            GOAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_goal)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    blood_conv = ConversationHandler(
        entry_points=[
            CommandHandler("upload_blood", upload_blood_command),
            CommandHandler("blood", upload_blood_command),
        ],
        states={
            BLOOD_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, blood_input_handler),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    food_conv = ConversationHandler(
        entry_points=[
            CommandHandler("log_food", log_food_command),
            CommandHandler("food", log_food_command),
        ],
        states={
            FOOD_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, food_input_handler),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(profile_conv)
    app.add_handler(blood_conv)
    app.add_handler(food_conv)

    # --- Simple command handlers (with short aliases) ---

    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("log_water", log_water_command))
    app.add_handler(CommandHandler("water", log_water_command))
    app.add_handler(CommandHandler("log_workout", log_workout_command))
    app.add_handler(CommandHandler("workout", log_workout_command))
    app.add_handler(CommandHandler("log_scale", log_scale_command))
    app.add_handler(CommandHandler("scale", log_scale_command))
    app.add_handler(CommandHandler("log_cycle", log_cycle_command))
    app.add_handler(CommandHandler("cycle", log_cycle_command))
    app.add_handler(CommandHandler("log_wearable", log_wearable_command))
    app.add_handler(CommandHandler("sleep", log_wearable_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("review", review_command))
    app.add_handler(CommandHandler("correct", correct_command))
    app.add_handler(CommandHandler("fix", fix_command))
    app.add_handler(CommandHandler("research", research_command))

    # --- Photo handler (food / blood / scale detection) ---

    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))

    # --- Free-text catch-all (MUST be last — catches unmatched text) ---

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, free_text_handler))

    logger.info("BiteAndByte bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
