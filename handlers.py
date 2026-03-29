"""Telegram bot handlers — 3-step pipeline:
  1. Gemini EXTRACTS raw data (food items, grams, markers)
  2. Python CALCULATES (BMR, TDEE, calories, macros, ranges)
  3. Gemini VERBALIZES (Hebrew feedback from pre-calculated results)
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

import config
import sheets
import insights
import gemini_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conversation states
# ---------------------------------------------------------------------------

NAME, AGE, GENDER, HEIGHT, WEIGHT = range(5)
BLOOD_INPUT = 10


# ---------------------------------------------------------------------------
# Safe reply helper — falls back to plain text if Markdown fails
# ---------------------------------------------------------------------------

async def _safe_reply(message, text: str) -> None:
    """Send with Markdown, fallback to plain text if parsing fails."""
    try:
        await message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        # Strip Markdown markers and send plain
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

    user_id = update.effective_user.id
    d = context.user_data
    sheets.save_profile(
        user_id=user_id, name=d["name"], age=d["age"], gender=d["gender"],
        height_cm=d["height_cm"], initial_weight_kg=weight,
    )

    # Python-calculated BMR & TDEE
    bmr = insights.calculate_bmr(weight, d["height_cm"], d["age"], d["gender"])
    tdee = insights.calculate_tdee(bmr, 0)
    bmi = insights.calculate_bmi(weight, d["height_cm"])
    macros = insights.calculate_macro_targets(tdee)

    await update.message.reply_text(
        f"✅ הפרופיל נשמר!\n"
        f"👤 {d['name']}, גיל {d['age']}, {d['height_cm']}cm, {weight}kg\n\n"
        f"📊 הנתונים שחושבו:\n"
        f"🔥 BMR: {bmr:.0f} קק\"ל | TDEE: {tdee:.0f} קק\"ל\n"
        f"📏 BMI: {bmi} ({insights.bmi_category(bmi)})\n"
        f"🎯 יעדי מאקרו יומיים:\n"
        f"   חלבון: {macros['protein_g']}g | פחמימות: {macros['carbs_g']}g | שומן: {macros['fats_g']}g\n\n"
        "פקודות:\n"
        "/log\\_food — רישום ארוחה (טקסט או תמונה)\n"
        "/log\\_water — רישום שתייה\n"
        "/log\\_workout — רישום אימון\n"
        "/log\\_scale — מדידת משקל (טקסט או תמונה)\n"
        "/log\\_cycle — מחזור\n"
        "/upload\\_blood — בדיקת דם (טקסט או תמונה)\n"
        "/log\\_wearable — שינה וצעדים\n"
        "/status — סטטוס יומי\n"
        "/review — סיכום שבועי AI",
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ בוטל.")
    return ConversationHandler.END


# ============================================================================
# /log_food — 3-step: Gemini extracts → Python calculates → Gemini verbalizes
# ============================================================================

async def log_food_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text(
            "🍽️ רישום אוכל\n\n"
            "טקסט: /log_food חזה עוף 200 גרם עם אורז\n"
            "תמונה: שלח/י תמונה עם הכיתוב 'אוכל'\n\n"
            "Gemini מזהה → Python מחשב → Gemini נותן פידבק!",
        )
        return

    user_id = update.effective_user.id
    description = " ".join(args)
    await update.message.reply_text("🔍 מזהה פריטי מזון...")

    # STEP 1: Gemini EXTRACTS items + grams
    extracted = gemini_client.extract_food_from_text(description)

    # STEP 2: Python CALCULATES nutrition from local DB
    nutrition = insights.calculate_food_nutrition(extracted)

    # Save to sheets
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

    # Build items detail
    items_text = ""
    for item in nutrition["items"]:
        src = "📗 DB" if item.get("from_db") else "📙 הערכה"
        items_text += (
            f"  • {item['item']} ({item['grams']:.0f}g) — "
            f"{item['calories']:.0f} קק\"ל [{src}]\n"
        )

    # Hydration status
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
        "grams": sum(i.get("grams", 0) for i in nutrition["items"]),
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
        f"🥩 חלבון: {daily_pro:.0f}g\n\n"
        f"🤖 {feedback}"
    )
    await _safe_reply(update.message, msg)


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

    # STEP 1: Gemini EXTRACTS items + grams from photo
    extracted = gemini_client.extract_food_from_photo(image_bytes)

    await update.message.reply_text("🔢 שלב 2/3: מחשב ערכים תזונתיים...")

    # STEP 2: Python CALCULATES from local DB
    nutrition = insights.calculate_food_nutrition(extracted)

    item_names = ", ".join(i.get("item", "?") for i in nutrition["items"])
    sheets.log_food(
        user_id, item_names,
        nutrition["total_calories"], nutrition["total_protein"],
        nutrition["total_carbs"], nutrition["total_fats"],
    )

    # Daily totals
    today_food = [f for f in sheets.get_food(user_id, days=1) if f.get("date") == sheets.today()]
    daily_cal = sum(float(f.get("calories", 0)) for f in today_food)
    tdee = insights.get_tdee_for_user(user_id)

    # STEP 3: Gemini VERBALIZES
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
        f"📈 יומי: {daily_cal:.0f} / {tdee:.0f} קק\"ל\n\n"
        f"🤖 {feedback}"
    )
    await _safe_reply(update.message, msg)


async def _handle_blood_photo(update: Update, user_id: int, image_bytes: bytes) -> None:
    await update.message.reply_text("🩸 שלב 1/3: מחלץ סמנים מהתמונה (Gemini Pro)...")

    # STEP 1: Gemini EXTRACTS marker numbers
    markers = gemini_client.extract_blood_markers(image_bytes)

    # STEP 2: Python CALCULATES range checks
    clean = {k: v for k, v in markers.items() if v is not None and k != "_raw"}
    calculated = insights.calculate_blood_analysis(user_id, clean)

    # STEP 3: Gemini VERBALIZES from pre-calculated ranges
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

    # STEP 1: Gemini EXTRACTS numbers
    raw = gemini_client.extract_scale_metrics(image_bytes)

    weight = float(raw.get("weight_kg", 0))
    if weight <= 0:
        await update.message.reply_text(
            "⚠️ לא זוהו ערכים.\nנסה/י: /log_scale 75.2 18.5 55.3 3.1 35.8"
        )
        return

    # STEP 2: Python CALCULATES BMI, deltas, cycle adjustments
    calculated = insights.calculate_scale_data(
        user_id, weight,
        float(raw.get("body_fat_pct", 0)),
        float(raw.get("water_pct", 0)),
        float(raw.get("bone_mass_kg", 0)),
        float(raw.get("muscle_mass_kg", 0)),
    )

    # STEP 3: Gemini VERBALIZES
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

    # Python-calculated status
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
# /log_workout — Gemini verbalizes pre-calculated workout data
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

    # STEP 2: Python CALCULATES everything
    calculated = insights.calculate_workout_data(user_id, exercise_type, duration, intensity)

    # STEP 3: Gemini VERBALIZES
    feedback = gemini_client.generate_workout_feedback(calculated)

    msg = (
        f"✅ אימון נרשם: {exercise_type}, {duration} דקות, עצימות {intensity}/10\n\n"
        f"🔥 קלוריות: {calculated['calories_burned']} קק\"ל\n"
        f"📊 TDEE מעודכן: {calculated['updated_tdee']:.0f} קק\"ל\n"
        f"💧 מים נוספים: +{calculated['extra_water_l']}L\n"
    )
    if calculated["protein_bump_g"] > 0:
        msg += f"🥩 חלבון נוסף: +{calculated['protein_bump_g']}g\n"
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

    # STEP 2: Python CALCULATES
    calculated = insights.calculate_scale_data(user_id, weight, fat, water, bone, muscle)

    # STEP 3: Gemini VERBALIZES
    feedback = gemini_client.generate_scale_feedback(calculated)

    msg = (
        f"✅ נרשם: {weight}kg | שומן {fat}% | שריר {muscle}kg\n"
        f"📏 BMI: {calculated['bmi']} ({calculated['bmi_category']})\n\n"
        f"🤖 {feedback}"
    )
    await _safe_reply(update.message, msg)


# ============================================================================
# /log_cycle — Python calculates adjustments → Gemini verbalizes
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

    # STEP 2: Python CALCULATES cycle adjustments
    adjustments = insights.get_cycle_adjustments(phase)
    calculated = {"phase": phase, **adjustments}

    # STEP 3: Gemini VERBALIZES
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

    # STEP 2: Python CALCULATES ranges
    calculated = insights.calculate_blood_analysis(user_id, markers)

    # STEP 3: Gemini VERBALIZES
    feedback = gemini_client.generate_blood_feedback(calculated)

    flags_text = "\n".join(calculated.get("flags", [])) or "🎉 הכל תקין!"
    msg = f"🩸 בדיקת דם נשמרה\n\n{flags_text}\n\n🤖 ניתוח:\n{feedback}"
    await _safe_reply(update.message, msg)
    return ConversationHandler.END


# ============================================================================
# /log_wearable — Python calculates → Gemini verbalizes
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

    # STEP 2: Python CALCULATES
    calculated = insights.calculate_wearable_insights(sleep_hours, sleep_quality, steps)

    # STEP 3: Gemini VERBALIZES
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
# /status — Python calculates → Gemini gives daily tip
# ============================================================================

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    calculated = insights.calculate_daily_status(user_id)

    if not calculated:
        await update.message.reply_text("⚠️ לא נמצא פרופיל. הפעל/י /start")
        return

    # Gemini daily tip from pre-calculated data
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
# /review — Python pre-calculates everything → Gemini Pro writes review
# ============================================================================

async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    profile = sheets.get_profile(user_id)
    if not profile:
        await update.message.reply_text("⚠️ לא נמצא פרופיל. הפעל/י /start")
        return

    await update.message.reply_text("🔢 מחשב נתונים שבועיים...")

    # STEP 2: Python CALCULATES everything
    calculated = insights.calculate_weekly_review(user_id)

    await update.message.reply_text("🤖 Gemini Pro כותב סיכום...")

    # STEP 3: Gemini Pro VERBALIZES
    review = gemini_client.generate_weekly_review(calculated)

    await _safe_reply(update.message, review)
