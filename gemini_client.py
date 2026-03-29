"""Gemini API client for BiteAndByte.

STRICT ROLE SEPARATION:
  - Gemini EXTRACTS raw data (food items, grams, blood markers from images)
  - Gemini GENERATES verbal Hebrew feedback from PRE-CALCULATED results
  - Gemini NEVER does math — all calculations happen in Python (insights.py)
"""

import io
import json
import logging

import google.generativeai as genai
from PIL import Image

import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Initialization (lazy — models created on first use)
# ---------------------------------------------------------------------------

_flash_model = None
_pro_model = None

_SYSTEM_HEB = "אתה יועץ תזונה ובריאות מקצועי. ענה תמיד בעברית."


def _init_models():
    global _flash_model, _pro_model
    if _flash_model is None:
        genai.configure(api_key=config.GEMINI_API_KEY)
        _flash_model = genai.GenerativeModel(config.GEMINI_FLASH)
        _pro_model = genai.GenerativeModel(config.GEMINI_PRO)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_image(image_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(image_bytes))


def _ask_flash(prompt: str, image: Image.Image | None = None) -> str:
    _init_models()
    parts = [prompt]
    if image:
        parts.insert(0, image)
    try:
        resp = _flash_model.generate_content(parts)
        return resp.text
    except Exception as e:
        logger.error("Gemini Flash error: %s", e)
        return ""


def _ask_pro(prompt: str, image: Image.Image | None = None) -> str:
    _init_models()
    parts = [prompt]
    if image:
        parts.insert(0, image)
    try:
        resp = _pro_model.generate_content(parts)
        return resp.text
    except Exception as e:
        logger.error("Gemini Pro error (falling back to Flash): %s", e)
        # Fallback to Flash if Pro fails
        try:
            resp = _flash_model.generate_content(parts)
            return resp.text
        except Exception as e2:
            logger.error("Gemini Flash fallback also failed: %s", e2)
            return ""


def _parse_json(text: str, fallback: dict) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end])
            except json.JSONDecodeError:
                pass
        logger.warning("Failed to parse Gemini JSON response: %s", text[:200])
        fallback["_raw"] = text[:500]
        return fallback


# ============================================================================
# STEP 1 — EXTRACTION (Gemini identifies what, not how much nutritionally)
# ============================================================================

def extract_food_from_text(description: str) -> list[dict]:
    """Extract food items and estimated grams from a text description.

    Returns list of: {"item": "חזה עוף", "grams": 200}
    Gemini only identifies items and portions — ZERO calorie math.
    """
    prompt = f"""זהה את כל פריטי המזון ואת המשקל המשוער בגרמים מהתיאור הבא.
אם לא צוין משקל, הערך מנה ממוצעת בגרמים.

תיאור: "{description}"

החזר JSON בלבד (בלי markdown):
[{{"item": "שם הפריט בעברית", "grams": 0}}, ...]

דוגמאות למנות ממוצעות:
- חזה עוף: 150g, ביצה: 55g, כוס אורז מבושל: 200g
- פיתה: 80g, סלט: 150g, שניצל: 180g"""

    text = _ask_flash(prompt)
    result = _parse_json(text, fallback={"_list": []})

    # Handle both list and dict responses
    if isinstance(result, list):
        return result
    if "_list" in result:
        return result["_list"]
    # Single item wrapped in dict
    if "item" in result:
        return [result]
    return [{"item": description, "grams": 150}]


def extract_food_from_photo(image_bytes: bytes) -> list[dict]:
    """Extract food items and estimated grams from a photo.

    Returns list of: {"item": "שם המאכל", "grams": 0}
    Gemini only identifies — ZERO calorie math.
    """
    image = _load_image(image_bytes)

    prompt = """זהה את כל פריטי המזון בתמונה והערך את המשקל בגרמים לכל פריט.

החזר JSON בלבד (בלי markdown):
[{"item": "שם הפריט בעברית", "grams": 0}, ...]

אם לא בטוח, הערך מנה ממוצעת."""

    text = _ask_flash(prompt, image=image)
    result = _parse_json(text, fallback={"_list": []})

    if isinstance(result, list):
        return result
    if "_list" in result:
        return result["_list"]
    if "item" in result:
        return [result]
    return [{"item": "ארוחה לא מזוהה", "grams": 200}]


def extract_blood_markers(image_bytes: bytes) -> dict:
    """Extract blood marker values from a screenshot.

    Returns dict of marker_key: value (numbers only, no analysis).
    Gemini only reads numbers — Python does the range-checking.
    """
    image = _load_image(image_bytes)

    prompt = """חלץ את כל ערכי בדיקת הדם שאתה מזהה בתמונה.

החזר JSON בלבד (בלי markdown):
{
  "glucose_mg_dl": null,
  "hba1c_pct": null,
  "cholesterol_total": null,
  "hdl": null,
  "ldl": null,
  "triglycerides": null,
  "iron": null,
  "ferritin": null,
  "vitamin_d": null,
  "b12": null,
  "tsh": null,
  "crp": null
}

מלא רק ערכים שאתה מזהה. השאר null למה שלא מופיע.
החזר מספרים בלבד, ללא יחידות."""

    text = _ask_pro(prompt, image=image)
    return _parse_json(text, fallback={})


def extract_scale_metrics(image_bytes: bytes) -> dict:
    """Extract body composition numbers from a smart scale screenshot.

    Returns: {"weight_kg": 0, "body_fat_pct": 0, "water_pct": 0,
              "bone_mass_kg": 0, "muscle_mass_kg": 0}
    Gemini only reads numbers — ZERO analysis.
    """
    image = _load_image(image_bytes)

    prompt = """חלץ את נתוני הרכב הגוף מצילום המסך.

החזר JSON בלבד (בלי markdown):
{"weight_kg": 0, "body_fat_pct": 0, "water_pct": 0, "bone_mass_kg": 0, "muscle_mass_kg": 0}

מלא רק ערכים שאתה מזהה. השאר 0 למה שלא מופיע. מספרים בלבד."""

    text = _ask_flash(prompt, image=image)
    return _parse_json(text, fallback={
        "weight_kg": 0, "body_fat_pct": 0, "water_pct": 0,
        "bone_mass_kg": 0, "muscle_mass_kg": 0,
    })


# ============================================================================
# STEP 3 — VERBAL FEEDBACK (Gemini receives pre-calculated numbers)
# ============================================================================

def generate_food_feedback(calculated: dict) -> str:
    """Generate Hebrew feedback for a logged meal.

    `calculated` contains Python-computed values:
      item, grams, calories, protein_g, carbs_g, fats_g,
      daily_total_cal, daily_total_protein, tdee, remaining_cal,
      hydration_status, from_db
    """
    prompt = f"""{_SYSTEM_HEB}

המשתמש אכל/ה ואלה הנתונים שחושבו (כבר מחושב, אל תחשב מחדש!):

פריט: {calculated.get('item', '?')}
כמות: {calculated.get('grams', '?')}g
קלוריות: {calculated.get('calories', 0)} קק"ל
חלבון: {calculated.get('protein_g', 0)}g | פחמימות: {calculated.get('carbs_g', 0)}g | שומן: {calculated.get('fats_g', 0)}g

סיכום יומי (מחושב):
- סה"כ קלוריות היום: {calculated.get('daily_total_cal', 0)} / {calculated.get('tdee', 0)} קק"ל
- נותרו: {calculated.get('remaining_cal', 0)} קק"ל
- חלבון כולל היום: {calculated.get('daily_total_protein', 0)}g
- שתייה: {calculated.get('hydration_status', '')}

תן תגובה קצרה (3-4 משפטים) בעברית:
- אישור הרישום
- תובנה על האיזון התזונתי (מאקרוס)
- המלצה קצרה לשאר היום
אל תציג מספרים שונים מאלה שניתנו לך."""

    return _ask_flash(prompt)


def generate_workout_feedback(calculated: dict) -> str:
    """Generate Hebrew post-workout feedback from pre-calculated data.

    `calculated` contains: exercise_type, duration_min, intensity,
      calories_burned, updated_tdee, extra_water_l, protein_bump_g,
      hydration_status, cycle_phase (optional)
    """
    cycle_ctx = ""
    if calculated.get("cycle_phase"):
        cycle_ctx = f"\nשלב מחזור נוכחי: {calculated['cycle_phase']}"

    prompt = f"""{_SYSTEM_HEB}

המשתמש/ת סיים/ה אימון. נתונים מחושבים (אל תחשב מחדש!):

סוג: {calculated.get('exercise_type', '?')}
משך: {calculated.get('duration_min', 0)} דקות
עצימות: {calculated.get('intensity', 0)}/10
קלוריות שנשרפו: {calculated.get('calories_burned', 0)} קק"ל
TDEE מעודכן: {calculated.get('updated_tdee', 0)} קק"ל
מים נוספים מומלצים: {calculated.get('extra_water_l', 0)} ליטר
תוספת חלבון מומלצת: {calculated.get('protein_bump_g', 0)}g
שתייה: {calculated.get('hydration_status', '')}{cycle_ctx}

תן תגובה מעודדת (4-5 משפטים) בעברית:
- אישור וסיכום האימון
- המלצות שתייה ותזונה מבוססות על הנתונים
- עידוד מותאם לעצימות
- אם יש שלב מחזור, התייחס אליו ברגישות
אל תציג מספרים שונים מאלה שניתנו לך."""

    return _ask_flash(prompt)


def generate_blood_feedback(calculated: dict) -> str:
    """Generate Hebrew blood work analysis from pre-calculated range checks.

    `calculated` contains: date, flags (list of out-of-range), ok (list of normal),
      all_normal (bool)
    """
    flags_str = "\n".join(calculated.get("flags", [])) or "אין"
    ok_str = "\n".join(calculated.get("ok", [])) or "אין"

    prompt = f"""{_SYSTEM_HEB}

תוצאות בדיקת דם מתאריך {calculated.get('date', '?')}.
הטווחים כבר נבדקו — הנה הסיכום (אל תחשב מחדש!):

סמנים חריגים:
{flags_str}

סמנים תקינים:
{ok_str}

כל הסמנים תקינים: {'כן' if calculated.get('all_normal') else 'לא'}

כתוב ניתוח מפורט (5-8 משפטים) בעברית:
- התייחס לכל סמן חריג — מה המשמעות ומה מומלץ
- ציין את הסמנים התקינים בקצרה
- תן 2-3 המלצות תזונתיות/אורח חיים ספציפיות
- הדגש שזו אינה תחליף לייעוץ רפואי
אל תציג ערכים שונים מאלה שניתנו לך."""

    return _ask_pro(prompt)


def generate_scale_feedback(calculated: dict) -> str:
    """Generate Hebrew body composition feedback from pre-calculated trends.

    `calculated` contains: weight_kg, body_fat_pct, muscle_mass_kg,
      bmi, bmi_category, weight_delta, fat_delta, muscle_delta,
      cycle_phase (optional), cycle_weight_note (optional)
    """
    cycle_ctx = ""
    if calculated.get("cycle_phase"):
        cycle_ctx = (
            f"\nשלב מחזור: {calculated['cycle_phase']}"
            f"\n{calculated.get('cycle_weight_note', '')}"
        )

    prompt = f"""{_SYSTEM_HEB}

מדידת הרכב גוף חדשה. נתונים מחושבים (אל תחשב מחדש!):

משקל: {calculated.get('weight_kg', 0)} ק"ג
BMI: {calculated.get('bmi', 0)} ({calculated.get('bmi_category', '')})
אחוז שומן: {calculated.get('body_fat_pct', 0)}%
מסת שריר: {calculated.get('muscle_mass_kg', 0)} ק"ג

מגמות (30 יום):
- שינוי משקל: {calculated.get('weight_delta', 0):+.1f} ק"ג
- שינוי שומן: {calculated.get('fat_delta', 0):+.1f}%
- שינוי שריר: {calculated.get('muscle_delta', 0):+.1f} ק"ג{cycle_ctx}

תן תגובה (4-5 משפטים) בעברית:
- פרש את המגמות — האם הכיוון חיובי
- קשר בין שינויי שומן/שריר לאימונים
- אם יש שלב מחזור, הסבר השפעתו על המשקל
- המלצה קצרה
אל תציג מספרים שונים מאלה שניתנו לך."""

    return _ask_flash(prompt)


def generate_wearable_feedback(calculated: dict) -> str:
    """Generate Hebrew morning insight from pre-calculated wearable data.

    `calculated` contains: sleep_hours, sleep_quality, steps,
      sleep_deficit, recommended_intensity, calorie_adjustment
    """
    prompt = f"""{_SYSTEM_HEB}

נתוני שעון חכם (מחושב, אל תחשב מחדש!):

שינה: {calculated.get('sleep_hours', 0)} שעות ({calculated.get('sleep_quality', '?')})
גירעון שינה: {calculated.get('sleep_deficit', 0)} שעות
צעדים אתמול: {calculated.get('steps', 0)}
עצימות אימון מומלצת: {calculated.get('recommended_intensity', '?')}
התאמת קלוריות: {calculated.get('calorie_adjustment', 0):+.0f} קק"ל

תן תובנת בוקר קצרה (3-4 משפטים) בעברית:
- איך השינה משפיעה על היום
- המלצת אימון מותאמת
- טיפ תזונתי
אל תציג מספרים שונים מאלה שניתנו לך."""

    return _ask_flash(prompt)


def generate_cycle_feedback(calculated: dict) -> str:
    """Generate Hebrew cycle-phase advice from pre-calculated adjustments.

    `calculated` contains: phase, calorie_adjustment, iron_note,
      water_adjustment_l, recommended_intensity, weight_fluctuation_note
    """
    prompt = f"""{_SYSTEM_HEB}

המשתמשת בשלב ה-{calculated.get('phase', '?')} של המחזור.

התאמות מחושבות (אל תחשבי מחדש!):
- התאמת קלוריות: {calculated.get('calorie_adjustment', 0):+.0f} קק"ל
- ברזל: {calculated.get('iron_note', '')}
- מים נוספים: {calculated.get('water_adjustment_l', 0)} ליטר
- עצימות אימון מומלצת: {calculated.get('recommended_intensity', '')}
- תנודת משקל צפויה: {calculated.get('weight_fluctuation_note', '')}

כתבי תגובה מעודדת (4-5 משפטים) בעברית:
- הסבירי מה קורה בגוף בשלב הזה
- שלבי את ההמלצות הנ"ל בצורה טבעית
- תני הרגשה תומכת ואמפתית
אל תציגי מספרים שונים מאלה שניתנו."""

    return _ask_flash(prompt)


def generate_weekly_review(calculated: dict) -> str:
    """Generate comprehensive Hebrew weekly review from pre-calculated data.

    `calculated` contains ALL Python-computed metrics:
      profile, bmr, tdee, bmi, bmi_category,
      weight_trend, composition_trend, avg_daily_cal, macro_split,
      macro_targets, hydration_avg, hydration_target,
      exercise_summary, sleep_summary, cycle_info, blood_summary,
      calorie_balance, protein_adherence
    """
    import json

    prompt = f"""{_SYSTEM_HEB}

כתוב סיכום שבועי מקיף. כל הנתונים כבר חושבו — אל תחשב מחדש!

{json.dumps(calculated, ensure_ascii=False, indent=2, default=str)}

מבנה הסיכום:
1. 📊 מגמות משקל והרכב גוף (השתמש בנתוני weight_trend ו-composition_trend)
2. 🍽️ תזונה — קלוריות בפועל מול יעד, חלוקת מאקרוס מול יעד
3. 💧 שתייה — ממוצע מול יעד
4. 🏋️ אימונים — סיכום ושריפת קלוריות
5. 😴 שינה וצעדים (אם יש)
6. 🔄 מחזור (אם רלוונטי)
7. 🩸 בדיקת דם (אם יש)
8. 💡 3 המלצות ספציפיות ומבוססות-נתונים לשבוע הבא

השתמש באימוג'ים ופורמט ברור. הצג את המספרים שניתנו לך, לא אחרים."""

    return _ask_pro(prompt)


def generate_status_feedback(calculated: dict) -> str:
    """Generate short Hebrew daily status feedback from pre-calculated snapshot.

    `calculated` contains: remaining_cal, protein_status, hydration_pct,
      exercise_today, sleep_note, cycle_note
    """
    prompt = f"""{_SYSTEM_HEB}

סטטוס יומי מחושב (אל תחשב מחדש!):

קלוריות נותרו: {calculated.get('remaining_cal', 0)} קק"ל
חלבון: {calculated.get('protein_status', '')}
שתייה: {calculated.get('hydration_pct', 0):.0f}% מהיעד
אימון היום: {calculated.get('exercise_today', 'לא')}
שינה: {calculated.get('sleep_note', 'אין נתון')}
מחזור: {calculated.get('cycle_note', 'לא רלוונטי')}

תן טיפ יומי קצר (2-3 משפטים) בעברית — מה כדאי לעשות עד סוף היום.
אל תציג מספרים שונים מאלה שניתנו לך."""

    return _ask_flash(prompt)
