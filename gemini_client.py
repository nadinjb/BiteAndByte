"""Gemini API client for BiteAndByte — google-genai SDK (2026).

STRICT ROLE SEPARATION:
  - Gemini EXTRACTS raw data (food items, grams, blood markers from images)
  - Gemini GENERATES verbal Hebrew feedback from PRE-CALCULATED results
  - Gemini NEVER does math — all calculations happen in Python (insights.py)
"""

import io
import json
import logging

from google import genai
from google.genai import types
from google.genai.errors import APIError
from PIL import Image
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Client initialization (lazy — created on first use)
# ---------------------------------------------------------------------------

_client: genai.Client | None = None

_SYSTEM_HEB = (
    "אתה מנהל מסד נתונים תזונתי ויועץ בריאות מקצועי. ענה תמיד בעברית. "
    "הדאטה שמורה ב-Food_Library היא האמת המוחלטת — תמיד העדף אותה על פני הערכות. "
    "תיקונים של המשתמש הם עובדות מוחלטות ומחייבות. "
    "אם נדרשים מספר קריאות לפונקציות, בצע את כולן במקביל בתגובה אחת — אל תשלח קריאה אחת ותחכה לתשובה לפני השנייה."
)

# AFC config applied to every generate_content call so the SDK never loops.
# We do not define any tools, so maximum_remote_calls=2 is a safety ceiling only.
_AFC_CFG = types.AutomaticFunctionCallingConfig(maximum_remote_calls=2)


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_image(image_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(image_bytes))


def _is_rate_limit(exc: BaseException) -> bool:
    """Return True for 429 errors from the Gemini API."""
    if isinstance(exc, APIError) and exc.code == 429:
        return True
    return "429" in str(exc)


@retry(
    retry=retry_if_exception(_is_rate_limit),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=6, max=20),
    reraise=True,
)
def _generate(client: genai.Client, model: str, contents, cfg) -> str:
    """Single Gemini generate_content call wrapped for tenacity retry."""
    resp = client.models.generate_content(model=model, contents=contents, config=cfg)
    return resp.text


def _call_with_retry(
    model: str, contents, system: str | None = None,
) -> str:
    """Call Gemini with AFC depth-limited and exponential backoff on 429."""
    client = _get_client()
    cfg = types.GenerateContentConfig(
        system_instruction=system or "",
        automatic_function_calling=_AFC_CFG,
    )
    try:
        return _generate(client, model, contents, cfg)
    except Exception as e:
        logger.error("%s error after retries: %s", model, e)
        return ""


def _ask_flash(prompt: str, image: Image.Image | None = None) -> str:
    contents = [image, prompt] if image else prompt
    return _call_with_retry(config.GEMINI_FLASH, contents)


def _ask_flash_system(prompt: str) -> str:
    """Flash with Hebrew system instruction for feedback generation."""
    return _call_with_retry(config.GEMINI_FLASH, prompt, system=_SYSTEM_HEB)


def _ask_pro(prompt: str, image: Image.Image | None = None) -> str:
    contents = [image, prompt] if image else prompt
    result = _call_with_retry(config.GEMINI_PRO, contents)
    if not result:
        logger.warning("Gemini Pro failed, falling back to Flash")
        result = _call_with_retry(config.GEMINI_FLASH, contents)
    return result


def _ask_pro_system(prompt: str) -> str:
    """Pro with Hebrew system instruction, Flash fallback."""
    result = _call_with_retry(config.GEMINI_PRO, prompt, system=_SYSTEM_HEB)
    if not result:
        logger.warning("Gemini Pro failed, falling back to Flash")
        result = _call_with_retry(config.GEMINI_FLASH, prompt, system=_SYSTEM_HEB)
    return result


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
        # Try array
        arr_start = cleaned.find("[")
        arr_end = cleaned.rfind("]") + 1
        if arr_start != -1 and arr_end > arr_start:
            try:
                return json.loads(cleaned[arr_start:arr_end])
            except json.JSONDecodeError:
                pass
        logger.warning("Failed to parse Gemini JSON response: %s", text[:200])
        fallback["_raw"] = text[:500]
        return fallback


# ============================================================================
# STEP 1 — EXTRACTION (Gemini identifies what, not how much nutritionally)
# ============================================================================

def extract_food_from_text(description: str, cached_items: list[dict] | None = None) -> list[dict]:
    """Extract food items and estimated grams from a text description.

    Returns list of: {"item": "...", "grams": 200, "calories": null, "protein_g": null, ...}
    If the user explicitly stated a nutritional value, it MUST appear in the output.
    """
    cache_ctx = ""
    if cached_items:
        cache_lines = "\n".join(
            f"- {c['item']}: {c['calories']} קק\"ל, {c['protein_g']}g חלבון, "
            f"{c['carbs_g']}g פחמימות, {c['fats_g']}g שומן (ל-{c['grams']}g)"
            for c in cached_items
        )
        cache_ctx = f"""
פריטים שמורים של המשתמש (עדיפות עליונה — השתמש בערכים האלה!):
{cache_lines}
"""

    prompt = f"""אתה מנהל מסד נתונים תזונתי. זהה את פריטי המזון מהתיאור הבא.

כללים קריטיים:
1. עדיפות לנתונים מפורשים: אם המשתמש ציין מספר ספציפי (למשל "25g חלבון", "300 קלוריות"), חלץ אותו במדויק. אל תעריך.
2. מודעות למותגים: אם מוזכר שם מותג (Muller, PRO, Go, דנונה, יוטבתה, Alpro), ציין את שם המותג המלא.
3. אם לא צוין משקל — הערך מנה ממוצעת בגרמים.
4. אל תמציא ערכי תזונה — השאר null לכל מה שלא צוין מפורשות.
{cache_ctx}
תיאור: "{description}"

החזר JSON בלבד (בלי markdown):
[{{"item": "שם הפריט", "grams": 0, "calories": null, "protein_g": null, "carbs_g": null, "fats_g": null}}, ...]

דוגמאות:
- "מולר 25g חלבון" → {{"item": "מולר פרו", "grams": 200, "protein_g": 25}}
- "חזה עוף 200 גרם" → {{"item": "חזה עוף", "grams": 200}}
- "שייק 300 קלוריות 30g חלבון" → {{"item": "שייק חלבון", "grams": 400, "calories": 300, "protein_g": 30}}"""

    text = _ask_flash(prompt)
    result = _parse_json(text, fallback={"_list": []})

    if isinstance(result, list):
        # Filter out invalid entries (must have "item" key)
        valid = [r for r in result if isinstance(r, dict) and r.get("item")]
        return valid if valid else [{"item": description, "grams": 150}]
    if "_list" in result and isinstance(result["_list"], list) and result["_list"]:
        return result["_list"]
    if "item" in result and result["item"]:
        return [result]
    return [{"item": description, "grams": 150}]


def extract_food_from_photo(image_bytes: bytes) -> list[dict]:
    """Extract food items and estimated grams from a photo."""
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


def classify_intent(text: str) -> dict:
    """Classify the user's intent from natural Hebrew text.

    Returns:
    {
        "intent": "log_food|log_workout|log_water|log_scale|log_cycle|log_sleep|correct_food|answer_question|status|review",
        "data": {...},           # extracted fields
        "missing_fields": [...], # required fields not found
        "follow_up": "..."       # natural Hebrew question if fields missing, else null
    }
    """
    prompt = f"""אתה מסווג כוונות של משתמש בוט בריאות עברי. קרא את ההודעה וזהה את הכוונה.

כוונות אפשריות:
• log_food — אכילה/שתיית משקה עם קלוריות (לא מים)
• log_workout — אימון ספורט
• log_water — שתיית מים בלבד
• log_scale — שקילה / מדידת הרכב גוף
• log_cycle — שלב מחזור וסת
• log_sleep — שינה ו/או צעדים
• correct_food — תיקון רישום ("תתקן", "זה לא", "שגוי", "הייתה", "עדכן")
• status — בקשת סטטוס/סיכום יומי
• review — בקשת סיכום שבועי
• answer_question — שאלה / שיחה / כל דבר אחר

---
סכמת ה-data לפי כוונה (null לשדות חסרים):

log_food: {{"description": "<תיאור מלא של הארוחה>"}}

log_workout: {{"type": "functional|strength|cardio", "duration_min": <int|null>, "intensity": <int 1-10|null>}}
  מיפוי: כוח/משקולות→strength | ריצה/אופניים/קרדיו→cardio | פונקציונלי/HIIT/crossfit→functional
  עצימות: "מאוד קשה/מקסימום"→9 | "קשה/חזק"→8 | "בינוני"→6 | "קל"→4

log_water: {{"liters": <float>}}
  המרות: כוס=0.25 | כוסית=0.1 | בקבוק=0.5 | ליטר=1.0

log_scale: {{"weight_kg": <float>, "body_fat_pct": <float|null>, "water_pct": <float|null>, "bone_mass_kg": <float|null>, "muscle_mass_kg": <float|null>}}

log_cycle: {{"phase": "follicular|ovulation|luteal|menstrual", "notes": "<str|null>"}}
  מיפוי: זקיק→follicular | ביוץ→ovulation | לוטאלי→luteal | מחזור/דימום→menstrual

log_sleep: {{"steps": <int|null>, "sleep_hours": <float|null>, "sleep_quality": "good|fair|poor|null"}}
  מיפוי: טוב/נהדר→good | בסדר/רגיל→fair | גרוע/נורא/לא טוב→poor

correct_food: {{"item": "<שם פריט|'האחרון'>", "grams": <float|null>, "calories": <float|null>, "protein_g": <float|null>, "carbs_g": <float|null>, "fats_g": <float|null>}}

status, review, answer_question: {{}}

---
חוקים:
1. missing_fields — רשימת שמות שדות חובה שחסרים
2. follow_up — שאלת המשך טבעית בעברית אם missing_fields אינה ריקה, אחרת null
3. אל תמציא ערכים — אם לא צוין, רשום null

דוגמאות:
"עשיתי אימון כוח 45 דקות עצימות 8" → {{"intent":"log_workout","data":{{"type":"strength","duration_min":45,"intensity":8}},"missing_fields":[],"follow_up":null}}
"היה לי ריצה קלה" → {{"intent":"log_workout","data":{{"type":"cardio","duration_min":null,"intensity":4}},"missing_fields":["duration_min"],"follow_up":"כמה זמן רצת?"}}
"אכלתי יוגורט מולר 165 גרם" → {{"intent":"log_food","data":{{"description":"יוגורט מולר 165 גרם"}},"missing_fields":[],"follow_up":null}}
"שתיתי 2 כוסות מים" → {{"intent":"log_water","data":{{"liters":0.5}},"missing_fields":[],"follow_up":null}}
"תתקן חלב שקדים ל-39 קלוריות ל-300 מ\"ל" → {{"intent":"correct_food","data":{{"item":"חלב שקדים","grams":300,"calories":39}},"missing_fields":[],"follow_up":null}}
"שקלתי 74.3" → {{"intent":"log_scale","data":{{"weight_kg":74.3}},"missing_fields":[],"follow_up":null}}
"ישנתי 7 שעות שינה טובה" → {{"intent":"log_sleep","data":{{"sleep_hours":7,"sleep_quality":"good","steps":null}},"missing_fields":[],"follow_up":null}}
"מה אני אמורה לאכול?" → {{"intent":"answer_question","data":{{}},"missing_fields":[],"follow_up":null}}

הודעה: "{text}"

החזר JSON בלבד (בלי markdown):"""

    raw = _ask_flash(prompt)
    result = _parse_json(raw, fallback={})

    # Ensure all keys exist with safe defaults
    result.setdefault("intent", "answer_question")
    result.setdefault("data", {})
    result.setdefault("missing_fields", [])
    result.setdefault("follow_up", None)

    # Sanitize missing_fields — must be a list
    if not isinstance(result["missing_fields"], list):
        result["missing_fields"] = []

    return result


def estimate_nutrition(food_name: str, grams: float) -> dict | None:
    """Ask Gemini to estimate nutrition for an item not found in any local DB.

    Returns dict with calories, protein_g, carbs_g, fats_g for the given grams,
    or None if Gemini fails. Values are conservative (lower-bound).
    """
    prompt = f"""אתה מנהל מסד נתונים תזונתי. הפריט הבא אינו ברשימתי — הערך ערכים תזונתיים שמרניים (גבול תחתון).

פריט: {food_name}
כמות: {grams:.0f} גרם

החזר JSON בלבד (בלי markdown):
{{"calories": 0, "protein_g": 0, "carbs_g": 0, "fats_g": 0}}

חשוב: הערכים הם עבור {grams:.0f} גרם בדיוק. השתמש בהערכה שמרנית. מספרים בלבד."""

    text = _ask_flash(prompt)
    result = _parse_json(text, fallback={})
    if not result or "calories" not in result:
        return None
    try:
        return {
            "calories": round(float(result.get("calories", 0)), 1),
            "protein_g": round(float(result.get("protein_g", 0)), 1),
            "carbs_g": round(float(result.get("carbs_g", 0)), 1),
            "fats_g": round(float(result.get("fats_g", 0)), 1),
        }
    except (ValueError, TypeError):
        return None


def extract_blood_markers(image_bytes: bytes) -> dict:
    """Extract blood marker values from a screenshot (numbers only)."""
    image = _load_image(image_bytes)

    prompt = """חלץ את כל ערכי בדיקת הדם שאתה מזהה בתמונה.

החזר JSON בלבד (בלי markdown):
{
  "glucose_mg_dl": null, "hba1c_pct": null, "cholesterol_total": null,
  "hdl": null, "ldl": null, "triglycerides": null,
  "iron": null, "ferritin": null, "vitamin_d": null,
  "b12": null, "tsh": null, "crp": null
}

מלא רק ערכים שאתה מזהה. השאר null למה שלא מופיע.
החזר מספרים בלבד, ללא יחידות."""

    text = _ask_pro(prompt, image=image)
    return _parse_json(text, fallback={})


def extract_scale_metrics(image_bytes: bytes) -> dict:
    """Extract body composition numbers from a smart scale screenshot."""
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
    prompt = f"""המשתמש אכל/ה ואלה הנתונים שחושבו (כבר מחושב, אל תחשב מחדש!):

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
    return _ask_flash_system(prompt)


def generate_workout_feedback(calculated: dict) -> str:
    cycle_ctx = ""
    if calculated.get("cycle_phase"):
        cycle_ctx = f"\nשלב מחזור נוכחי: {calculated['cycle_phase']}"

    prompt = f"""המשתמש/ת סיים/ה אימון. נתונים מחושבים (אל תחשב מחדש!):

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
    return _ask_flash_system(prompt)


def generate_blood_feedback(calculated: dict) -> str:
    flags_str = "\n".join(calculated.get("flags", [])) or "אין"
    ok_str = "\n".join(calculated.get("ok", [])) or "אין"

    prompt = f"""תוצאות בדיקת דם מתאריך {calculated.get('date', '?')}.
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
    return _ask_pro_system(prompt)


def generate_scale_feedback(calculated: dict) -> str:
    cycle_ctx = ""
    if calculated.get("cycle_phase"):
        cycle_ctx = (
            f"\nשלב מחזור: {calculated['cycle_phase']}"
            f"\n{calculated.get('cycle_weight_note', '')}"
        )

    prompt = f"""מדידת הרכב גוף חדשה. נתונים מחושבים (אל תחשב מחדש!):

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
    return _ask_flash_system(prompt)


def generate_wearable_feedback(calculated: dict) -> str:
    prompt = f"""נתוני שעון חכם (מחושב, אל תחשב מחדש!):

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
    return _ask_flash_system(prompt)


def generate_cycle_feedback(calculated: dict) -> str:
    prompt = f"""המשתמשת בשלב ה-{calculated.get('phase', '?')} של המחזור.

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
    return _ask_flash_system(prompt)


def generate_weekly_review(calculated: dict) -> str:
    prompt = f"""כתוב סיכום שבועי מקיף. כל הנתונים כבר חושבו — אל תחשב מחדש!

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
    return _ask_pro_system(prompt)


def generate_status_feedback(calculated: dict) -> str:
    prompt = f"""סטטוס יומי מחושב (אל תחשב מחדש!):

קלוריות נותרו: {calculated.get('remaining_cal', 0)} קק"ל
חלבון: {calculated.get('protein_status', '')}
שתייה: {calculated.get('hydration_pct', 0):.0f}% מהיעד
אימון היום: {calculated.get('exercise_today', 'לא')}
שינה: {calculated.get('sleep_note', 'אין נתון')}
מחזור: {calculated.get('cycle_note', 'לא רלוונטי')}

תן טיפ יומי קצר (2-3 משפטים) בעברית — מה כדאי לעשות עד סוף היום.
אל תציג מספרים שונים מאלה שניתנו לך."""
    return _ask_flash_system(prompt)


# ---------------------------------------------------------------------------
# Context-aware free-text answering
# ---------------------------------------------------------------------------

def answer_with_context(question: str, user_context: str) -> str:
    """Answer a free-text question using 14-day user data as context."""
    prompt = f"""אתה יועץ תזונה ובריאות מקצועי וחכם. ענה תמיד בעברית.
להלן כל הנתונים של המשתמש/ת מ-14 הימים האחרונים:
{user_context}
---
הוראות:
- ענה על השאלה/הודעה של המשתמש/ת בהתבסס על הנתונים למעלה.
- אם שואל "למה אני עייפ/ה?" — בדוק שינה, ברזל, פחמימות, מחזור
- אם מבקש תכנון ארוחה — חשב לפי קלוריות/חלבון שנותרו
- אם שואל על בדיקות דם — הסבר בשפה פשוטה
- אם אומר "בוקר טוב" — תדרוך בוקר (שינה, מחזור, יעדים, אימון, שתייה)
- השתמש רק במספרים מהנתונים. אל תמציא.
- 4-8 משפטים, עברית, אימוג'ים.
הודעת המשתמש/ת: "{question}"
"""
    return _call_with_retry(config.GEMINI_FLASH, prompt, system=_SYSTEM_HEB)


# ---------------------------------------------------------------------------
# Reddit research analysis
# ---------------------------------------------------------------------------

def analyze_reddit_research(topic: str, reddit_data: str, user_context: str) -> str:
    """Compare Reddit community advice to user's personal health data."""
    prompt = f"""אתה יועץ תזונה ובריאות מקצועי. קיבלת נושא מחקר מהמשתמש/ת ונתוני קהילה מרדיט.

נושא: "{topic}"

=== דיונים מרדיט ===
{reddit_data}

=== הנתונים האישיים של המשתמש/ת ===
{user_context}

=== הוראות ===
נתח את המידע מרדיט והשווה אותו לפרופיל האישי של המשתמש/ת.

כתוב בעברית במבנה הבא:

🔬 *נושא: {topic}*

✅ *יתרונות (לפי הקהילה):*
- 3-5 נקודות מרכזיות שעלו בדיונים

⚠️ *חסרונות וסיכונים:*
- 3-5 נקודות אזהרה שעלו בדיונים

📊 *קונצנזוס הקהילה:*
- מה רוב האנשים מסכימים עליו?
- האם יש מחלוקות?

🎯 *ההמלצה האישית שלך:*
- התאם/י את המסקנות לנתונים האישיים (משקל, בדיקות דם, אימונים, מחזור אם רלוונטי)
- ציין/י אם זה מתאים או לא מתאים למצב הספציפי של המשתמש/ת
- 2-3 המלצות קונקרטיות

⚕️ *הערה:* זוהי סקירת קהילה ולא ייעוץ רפואי מקצועי.

השתמש רק במספרים מהנתונים. אל תמציא."""
    return _call_with_retry(config.GEMINI_FLASH, prompt, system=_SYSTEM_HEB)
