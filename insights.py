"""Health insights engine — ALL math done in Python, ZERO math in Gemini.

Pipeline: Gemini extracts → Python calculates → Gemini verbalizes.

This module owns every formula: BMR, TDEE, BMI, calorie burn, macro targets,
hydration targets, blood range-checks, cycle adjustments, wearable scoring.
"""

import json

import config
import sheets_handler as sheets
import nutrition_db
import gemini_client


# ============================================================================
# CORE FORMULAS (hardcoded Python — no Gemini)
# ============================================================================

# ---------------------------------------------------------------------------
# BMR — Mifflin-St Jeor
# ---------------------------------------------------------------------------

def calculate_bmr(weight_kg: float, height_cm: float, age: int, gender: str) -> float:
    """Mifflin-St Jeor BMR.

    Male:   10 * weight + 6.25 * height - 5 * age + 5
    Female: 10 * weight + 6.25 * height - 5 * age - 161
    """
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    if gender.lower() in ("female", "f", "נקבה"):
        return round(base - 161, 1)
    return round(base + 5, 1)


def get_bmr_for_user(user_id: int) -> float:
    """BMR using latest weight from biometrics, or initial weight."""
    profile = sheets.get_profile(user_id)
    if not profile:
        return 0.0
    weight = float(profile.get("initial_weight_kg", 70))
    bio = sheets.get_biometrics(user_id, days=30)
    if bio:
        weight = float(bio[-1].get("weight_kg", weight))
    return calculate_bmr(
        weight,
        float(profile.get("height_cm", 170)),
        int(profile.get("age", 30)),
        str(profile.get("gender", "male")),
    )


# ---------------------------------------------------------------------------
# TDEE — BMR * activity factor + exercise
# ---------------------------------------------------------------------------

def calculate_tdee(bmr: float, exercise_kcal_today: float) -> float:
    """TDEE = BMR * 1.2 (sedentary base) + exercise calories."""
    return round(bmr * 1.2 + exercise_kcal_today, 1)


def get_tdee_for_user(user_id: int) -> float:
    bmr = get_bmr_for_user(user_id)
    exercises = sheets.get_exercise(user_id, days=1)
    ex_kcal = sum(float(e.get("estimated_kcal", 0)) for e in exercises
                  if e.get("date") == sheets.today())
    return calculate_tdee(bmr, ex_kcal)


# ---------------------------------------------------------------------------
# BMI
# ---------------------------------------------------------------------------

def calculate_bmi(weight_kg: float, height_cm: float) -> float:
    """BMI = weight / (height_m ^ 2)."""
    height_m = height_cm / 100
    if height_m <= 0:
        return 0.0
    return round(weight_kg / (height_m ** 2), 1)


def bmi_category(bmi: float) -> str:
    if bmi < 18.5:
        return "תת-משקל"
    if bmi < 25:
        return "תקין"
    if bmi < 30:
        return "עודף משקל"
    return "השמנה"


# ---------------------------------------------------------------------------
# Exercise calorie burn
# ---------------------------------------------------------------------------

def calculate_exercise_kcal(exercise_type: str, duration_min: int, intensity: int) -> float:
    """Calorie burn = rate * duration * intensity.

    Rates per minute per intensity unit:
      functional: 0.9, strength: 0.8, cardio: 1.1, default: 0.85
    """
    rate = config.CALORIE_RATES.get(exercise_type.lower(), 0.85)
    return round(rate * duration_min * intensity, 1)


# ---------------------------------------------------------------------------
# Hydration target
# ---------------------------------------------------------------------------

def calculate_hydration_target(
    base_liters: float = 2.5,
    exercise_entries: list[dict] | None = None,
) -> float:
    """Daily water target = base + exercise adjustments.

    Extra ml = 3.0 * duration_min * (intensity / 5) per workout.
    """
    total = base_liters
    for e in (exercise_entries or []):
        dur = float(e.get("duration_min", 0))
        intensity = float(e.get("intensity", 5))
        extra_ml = config.HYDRATION_ML_PER_MIN_INTENSITY * dur * (intensity / 5)
        total += extra_ml / 1000
    return round(total, 2)


def calculate_extra_water_for_workout(duration_min: int, intensity: int) -> float:
    """Extra liters of water recommended after a workout."""
    extra_ml = config.HYDRATION_ML_PER_MIN_INTENSITY * duration_min * (intensity / 5)
    return round(extra_ml / 1000, 2)


# ---------------------------------------------------------------------------
# Macro targets
# ---------------------------------------------------------------------------

def calculate_macro_targets(tdee: float, goal: str = "maintain") -> dict:
    """Split TDEE into macro targets (grams).

    Ratios:
      maintain: 30% protein, 40% carbs, 30% fat
      cut:      35% protein, 35% carbs, 30% fat (deficit of 300 kcal)
      bulk:     30% protein, 45% carbs, 25% fat (surplus of 300 kcal)

    Returns: {calories, protein_g, carbs_g, fats_g}
    """
    if goal == "cut":
        cal = tdee - 300
        p_pct, c_pct, f_pct = 0.35, 0.35, 0.30
    elif goal == "bulk":
        cal = tdee + 300
        p_pct, c_pct, f_pct = 0.30, 0.45, 0.25
    else:
        cal = tdee
        p_pct, c_pct, f_pct = 0.30, 0.40, 0.30

    return {
        "calories": round(cal),
        "protein_g": round(cal * p_pct / 4),   # 4 kcal/g protein
        "carbs_g": round(cal * c_pct / 4),      # 4 kcal/g carbs
        "fats_g": round(cal * f_pct / 9),        # 9 kcal/g fat
    }


# ---------------------------------------------------------------------------
# Protein bump post-workout
# ---------------------------------------------------------------------------

def protein_bump_grams(exercise_type: str) -> int:
    """Extra grams of protein recommended after workout type."""
    if exercise_type.lower() in ("strength", "functional"):
        return config.PROTEIN_BUMP_GRAMS
    return 0


# ---------------------------------------------------------------------------
# Blood work range-checking
# ---------------------------------------------------------------------------

_BLOOD_RANGES = {
    "glucose_mg_dl": (70, 100, "גלוקוז בצום"),
    "hba1c_pct": (4.0, 5.6, "המוגלובין מסוכרר"),
    "cholesterol_total": (0, 200, "כולסטרול כללי"),
    "hdl": (40, 200, "HDL"),
    "ldl": (0, 100, "LDL"),
    "triglycerides": (0, 150, "טריגליצרידים"),
    "iron": (60, 170, "ברזל"),
    "ferritin": (20, 200, "פריטין"),
    "vitamin_d": (30, 100, "ויטמין D"),
    "b12": (200, 900, "ויטמין B12"),
    "tsh": (0.4, 4.0, "TSH"),
    "crp": (0, 3.0, "CRP (דלקת)"),
}


def check_blood_ranges(markers: dict) -> dict:
    """Check blood markers against reference ranges.

    Returns: {date, flags: [...], ok: [...], all_normal: bool}
    """
    flags, ok = [], []
    for key, (lo, hi, heb_name) in _BLOOD_RANGES.items():
        val = markers.get(key, "")
        if val == "" or val is None:
            continue
        val = float(val)
        if val < lo:
            flags.append(f"🔻 {heb_name}: {val} (נמוך, טווח תקין {lo}–{hi})")
        elif val > hi:
            flags.append(f"🔺 {heb_name}: {val} (גבוה, טווח תקין {lo}–{hi})")
        else:
            ok.append(f"✅ {heb_name}: {val}")

    return {
        "date": markers.get("date", sheets.today()),
        "flags": flags,
        "ok": ok,
        "all_normal": len(flags) == 0,
    }


# ---------------------------------------------------------------------------
# Cycle adjustments (hardcoded Python formulas)
# ---------------------------------------------------------------------------

_CYCLE_ADJUSTMENTS = {
    "follicular": {
        "calorie_adjustment": 0,
        "iron_note": "רמות ברזל מתחילות להתאושש",
        "water_adjustment_l": 0.0,
        "recommended_intensity": "גבוהה — האנרגיה עולה",
        "weight_fluctuation_note": "ירידת נפיחות צפויה",
    },
    "ovulation": {
        "calorie_adjustment": +100,
        "iron_note": "תקין",
        "water_adjustment_l": 0.2,
        "recommended_intensity": "שיא — אפשר להעמיס",
        "weight_fluctuation_note": "משקל יציב, שיא ביצועים",
    },
    "luteal": {
        "calorie_adjustment": +200,
        "iron_note": "תקין",
        "water_adjustment_l": 0.3,
        "recommended_intensity": "בינונית — ירידה באנרגיה צפויה",
        "weight_fluctuation_note": "עלייה של 0.5-2 ק\"ג מאגירת מים — נורמלי לחלוטין",
    },
    "menstrual": {
        "calorie_adjustment": +100,
        "iron_note": "חשוב להגביר צריכת ברזל (בשר אדום, עדשים, תרד)",
        "water_adjustment_l": 0.2,
        "recommended_intensity": "נמוכה-בינונית — מנוחה חשובה",
        "weight_fluctuation_note": "נפיחות עשויה להתחיל לרדת",
    },
}


def get_cycle_adjustments(phase: str) -> dict:
    """Get phase-specific adjustments. Returns dict with all adjustment fields."""
    return _CYCLE_ADJUSTMENTS.get(phase.lower(), {
        "calorie_adjustment": 0,
        "iron_note": "",
        "water_adjustment_l": 0.0,
        "recommended_intensity": "רגילה",
        "weight_fluctuation_note": "",
    })


# ---------------------------------------------------------------------------
# Wearable math
# ---------------------------------------------------------------------------

def calculate_wearable_insights(sleep_hours: float, sleep_quality: str, steps: int) -> dict:
    """Pre-calculate all wearable-based insights.

    Returns: sleep_deficit, recommended_intensity, calorie_adjustment
    """
    # Sleep deficit (target: 7.5h)
    sleep_deficit = round(max(0, 7.5 - sleep_hours), 1)

    # Recommended workout intensity based on sleep
    if sleep_hours >= 7 and sleep_quality == "good":
        rec_intensity = "גבוהה — שינה טובה, אפשר להעמיס"
    elif sleep_hours >= 6:
        rec_intensity = "בינונית — שינה סבירה"
    else:
        rec_intensity = "נמוכה — מומלץ אימון קל או מנוחה"

    # Calorie adjustment for poor sleep (cortisol = hunger)
    cal_adj = 0
    if sleep_hours < 6:
        cal_adj = +150  # Extra cravings expected
    elif sleep_hours < 7:
        cal_adj = +50

    # Steps bonus
    if steps > 12000:
        cal_adj += 200
    elif steps > 8000:
        cal_adj += 100

    return {
        "sleep_hours": sleep_hours,
        "sleep_quality": sleep_quality,
        "steps": steps,
        "sleep_deficit": sleep_deficit,
        "recommended_intensity": rec_intensity,
        "calorie_adjustment": cal_adj,
    }


# ---------------------------------------------------------------------------
# Composition deltas
# ---------------------------------------------------------------------------

def calculate_composition_deltas(user_id: int, days: int = 30) -> dict:
    """Calculate body composition changes over a period."""
    bio = sheets.get_biometrics(user_id, days=days)
    if len(bio) < 2:
        return {"has_data": False}

    first, last = bio[0], bio[-1]

    def delta(key: str) -> float:
        return round(float(last.get(key, 0)) - float(first.get(key, 0)), 2)

    return {
        "has_data": True,
        "weight_delta": delta("weight_kg"),
        "fat_delta": delta("body_fat_pct"),
        "muscle_delta": delta("muscle_mass_kg"),
        "water_delta": delta("water_pct"),
    }


# ============================================================================
# STEP 2 — CALCULATE (takes Gemini-extracted raw data, returns computed dict)
# ============================================================================

def calculate_food_nutrition(extracted_items: list[dict], user_id: int = 0) -> dict:
    """Calculate total nutrition from Gemini-extracted food items.

    Each item: {"item": "...", "grams": 200, "calories": null, "protein_g": null, ...}

    Priority order:
      1. Explicit values from user (non-null fields in extraction)
      2. Food_Cache (learned corrections per user)
      3. Local nutrition_db
      4. Generic estimate fallback

    Returns: {items: [...], total_calories, total_protein, total_carbs, total_fats}
    """
    items = []
    total_cal = 0.0
    total_pro = 0.0
    total_carbs = 0.0
    total_fats = 0.0

    for entry in extracted_items:
        food_name = entry.get("item", "")
        grams = float(entry.get("grams", 150))

        # Check for explicit values from user (Rule #1)
        explicit_cal = entry.get("calories")
        explicit_pro = entry.get("protein_g")
        explicit_carbs = entry.get("carbs_g")
        explicit_fats = entry.get("fats_g")
        has_explicit = any(v is not None for v in [explicit_cal, explicit_pro, explicit_carbs, explicit_fats])

        item_result = None

        if has_explicit:
            # User provided explicit values — use them, fill gaps from DB
            db_result = nutrition_db.calculate_nutrition(food_name, grams)
            item_result = {
                "item": food_name,
                "grams": grams,
                "calories": float(explicit_cal) if explicit_cal is not None else (db_result["calories"] if db_result else round(grams * 1.2, 1)),
                "protein_g": float(explicit_pro) if explicit_pro is not None else (db_result["protein_g"] if db_result else round(grams * 0.08, 1)),
                "carbs_g": float(explicit_carbs) if explicit_carbs is not None else (db_result["carbs_g"] if db_result else round(grams * 0.15, 1)),
                "fats_g": float(explicit_fats) if explicit_fats is not None else (db_result["fats_g"] if db_result else round(grams * 0.05, 1)),
                "from_db": False,
                "explicit": True,
            }

        if not item_result and user_id:
            # Check Food_Cache (Rule #3 — learned corrections)
            cached = sheets.lookup_food_cache(user_id, food_name)
            if cached:
                c = cached[0]
                factor = grams / max(float(c.get("grams", 100)), 1)
                item_result = {
                    "item": food_name,
                    "grams": grams,
                    "calories": round(float(c.get("calories", 0)) * factor, 1),
                    "protein_g": round(float(c.get("protein_g", 0)) * factor, 1),
                    "carbs_g": round(float(c.get("carbs_g", 0)) * factor, 1),
                    "fats_g": round(float(c.get("fats_g", 0)) * factor, 1),
                    "from_db": False,
                    "from_cache": True,
                }

        if not item_result:
            # Try local nutrition_db
            db_result = nutrition_db.calculate_nutrition(food_name, grams)
            if db_result:
                item_result = db_result
            else:
                # Generic estimate fallback
                item_result = {
                    "item": food_name,
                    "grams": grams,
                    "calories": round(grams * 1.2, 1),
                    "protein_g": round(grams * 0.08, 1),
                    "carbs_g": round(grams * 0.15, 1),
                    "fats_g": round(grams * 0.05, 1),
                    "from_db": False,
                }

        items.append(item_result)
        total_cal += item_result["calories"]
        total_pro += item_result["protein_g"]
        total_carbs += item_result["carbs_g"]
        total_fats += item_result["fats_g"]

    return {
        "items": items,
        "total_calories": round(total_cal, 1),
        "total_protein": round(total_pro, 1),
        "total_carbs": round(total_carbs, 1),
        "total_fats": round(total_fats, 1),
    }


def calculate_workout_data(
    user_id: int, exercise_type: str, duration_min: int, intensity: int,
) -> dict:
    """Pre-calculate all workout-related data for Gemini feedback."""
    kcal = calculate_exercise_kcal(exercise_type, duration_min, intensity)
    extra_water = calculate_extra_water_for_workout(duration_min, intensity)
    protein_extra = protein_bump_grams(exercise_type)

    # Save first, then compute updated TDEE
    sheets.log_exercise(user_id, exercise_type, duration_min, intensity, kcal)
    updated_tdee = get_tdee_for_user(user_id)

    # Hydration status
    goal = calculate_hydration_target(
        exercise_entries=sheets.get_exercise(user_id, days=1)
    )
    today_water = sheets.get_hydration(user_id, days=1)
    consumed = sum(float(r.get("liters", 0)) for r in today_water)
    h_status = f"{consumed:.1f} / {goal:.1f} ליטר"

    # Cycle phase
    phase = sheets.get_current_phase(user_id)

    return {
        "exercise_type": exercise_type,
        "duration_min": duration_min,
        "intensity": intensity,
        "calories_burned": kcal,
        "updated_tdee": updated_tdee,
        "extra_water_l": extra_water,
        "protein_bump_g": protein_extra,
        "hydration_status": h_status,
        "cycle_phase": phase,
    }


def calculate_blood_analysis(user_id: int, markers: dict) -> dict:
    """Save blood markers and run range checks."""
    sheets.log_blood_work(user_id, markers)
    records = sheets.get_blood_work(user_id)
    if not records:
        return {"date": sheets.today(), "flags": [], "ok": [], "all_normal": True}
    return check_blood_ranges(records[-1])


def calculate_scale_data(
    user_id: int, weight: float, fat: float,
    water: float, bone: float, muscle: float,
) -> dict:
    """Save biometrics and pre-calculate all scale feedback data."""
    sheets.log_biometrics(user_id, weight, fat, water, bone, muscle)

    profile = sheets.get_profile(user_id)
    height = float(profile.get("height_cm", 170)) if profile else 170

    bmi = calculate_bmi(weight, height)
    deltas = calculate_composition_deltas(user_id, days=30)

    result = {
        "weight_kg": weight,
        "body_fat_pct": fat,
        "muscle_mass_kg": muscle,
        "bmi": bmi,
        "bmi_category": bmi_category(bmi),
        "weight_delta": deltas.get("weight_delta", 0),
        "fat_delta": deltas.get("fat_delta", 0),
        "muscle_delta": deltas.get("muscle_delta", 0),
    }

    # Cycle-aware weight context
    phase = sheets.get_current_phase(user_id)
    if phase:
        adj = get_cycle_adjustments(phase)
        result["cycle_phase"] = phase
        result["cycle_weight_note"] = adj["weight_fluctuation_note"]

    return result


def calculate_daily_status(user_id: int) -> dict:
    """Pre-calculate complete daily status for Gemini feedback."""
    profile = sheets.get_profile(user_id)
    if not profile:
        return {}

    bmr = get_bmr_for_user(user_id)
    tdee = get_tdee_for_user(user_id)

    # Food
    food = [f for f in sheets.get_food(user_id, days=1) if f.get("date") == sheets.today()]
    total_cal = sum(float(f.get("calories", 0)) for f in food)
    total_pro = sum(float(f.get("protein_g", 0)) for f in food)
    remaining_cal = round(max(0, tdee - total_cal))

    # Macro target
    targets = calculate_macro_targets(tdee)
    protein_pct = round(total_pro / max(targets["protein_g"], 1) * 100)
    protein_status = f"{total_pro:.0f}g / {targets['protein_g']}g ({protein_pct}%)"

    # Hydration
    h_goal = calculate_hydration_target(
        exercise_entries=sheets.get_exercise(user_id, days=1)
    )
    h_consumed = sum(
        float(r.get("liters", 0))
        for r in sheets.get_hydration(user_id, days=1)
    )
    h_pct = round(h_consumed / max(h_goal, 0.1) * 100)

    # Exercise
    today_ex = [
        e for e in sheets.get_exercise(user_id, days=1)
        if e.get("date") == sheets.today()
    ]
    if today_ex:
        ex_kcal = sum(float(e.get("estimated_kcal", 0)) for e in today_ex)
        exercise_today = f"{len(today_ex)} אימונים ({ex_kcal:.0f} קק\"ל)"
    else:
        exercise_today = "לא"

    # Sleep
    wearable = sheets.get_latest_wearable(user_id)
    sleep_note = "אין נתון"
    if wearable:
        sleep_note = f"{wearable.get('sleep_hours', '?')} שעות ({wearable.get('sleep_quality', '?')})"

    # Cycle
    phase = sheets.get_current_phase(user_id)
    cycle_note = "לא רלוונטי"
    if phase:
        adj = get_cycle_adjustments(phase)
        cycle_note = f"{phase} — {adj['recommended_intensity']}"

    return {
        "name": profile.get("name", ""),
        "date": sheets.today(),
        "bmr": bmr,
        "tdee": tdee,
        "total_cal": total_cal,
        "remaining_cal": remaining_cal,
        "protein_status": protein_status,
        "hydration_pct": h_pct,
        "exercise_today": exercise_today,
        "sleep_note": sleep_note,
        "cycle_note": cycle_note,
    }


def calculate_weekly_review(user_id: int) -> dict:
    """Pre-calculate ALL weekly review data for Gemini verbalization."""
    profile = sheets.get_profile(user_id)
    if not profile:
        return {}

    bmr = get_bmr_for_user(user_id)
    tdee = get_tdee_for_user(user_id)

    # Weight & composition
    bio = sheets.get_biometrics(user_id, days=7)
    weight_trend = {}
    if bio:
        latest = bio[-1]
        weight_trend = {
            "latest_weight": float(latest.get("weight_kg", 0)),
            "latest_fat": float(latest.get("body_fat_pct", 0)),
            "latest_muscle": float(latest.get("muscle_mass_kg", 0)),
        }
        if len(bio) >= 2:
            first = bio[0]
            weight_trend["weight_change"] = round(
                float(latest.get("weight_kg", 0)) - float(first.get("weight_kg", 0)), 1
            )

    bmi_val = 0.0
    if weight_trend.get("latest_weight"):
        bmi_val = calculate_bmi(
            weight_trend["latest_weight"],
            float(profile.get("height_cm", 170)),
        )

    composition = calculate_composition_deltas(user_id, days=30)

    # Nutrition
    food = sheets.get_food(user_id, days=7)
    days_logged = len({f.get("date") for f in food}) if food else 0
    total_cal = sum(float(f.get("calories", 0)) for f in food)
    total_pro = sum(float(f.get("protein_g", 0)) for f in food)
    total_carbs = sum(float(f.get("carbs_g", 0)) for f in food)
    total_fats = sum(float(f.get("fats_g", 0)) for f in food)
    avg_cal = round(total_cal / max(days_logged, 1))

    macro_targets = calculate_macro_targets(tdee)

    # Hydration
    hydration = sheets.get_hydration(user_id, days=7)
    h_days = len(hydration) if hydration else 0
    h_total = sum(float(h.get("liters", 0)) for h in hydration)
    h_avg = round(h_total / max(h_days, 1), 1)
    h_target = calculate_hydration_target(
        exercise_entries=sheets.get_exercise(user_id, days=1)
    )

    # Exercise
    exercises = sheets.get_exercise(user_id, days=7)
    ex_total_kcal = sum(float(e.get("estimated_kcal", 0)) for e in exercises)
    ex_total_min = sum(float(e.get("duration_min", 0)) for e in exercises)
    ex_types = {}
    for e in exercises:
        t = e.get("type", "?")
        ex_types[t] = ex_types.get(t, 0) + 1

    # Wearable
    wearable = sheets.get_wearable(user_id, days=7)
    sleep_summary = {}
    if wearable:
        avg_sleep = round(
            sum(float(w.get("sleep_hours", 0)) for w in wearable) / len(wearable), 1
        )
        avg_steps = round(
            sum(float(w.get("steps", 0)) for w in wearable) / len(wearable)
        )
        sleep_summary = {"avg_sleep_hours": avg_sleep, "avg_steps": avg_steps}

    # Cycle
    cycle_info = {}
    phase = sheets.get_current_phase(user_id)
    if phase:
        adj = get_cycle_adjustments(phase)
        cycle_info = {"phase": phase, **adj}

    # Blood
    blood = sheets.get_blood_work(user_id)
    blood_summary = {}
    if blood:
        blood_summary = check_blood_ranges(blood[-1])

    # Calorie balance
    calorie_balance = round(avg_cal - tdee)

    return {
        "profile": {
            "name": profile.get("name", ""),
            "age": profile.get("age"),
            "gender": profile.get("gender"),
        },
        "bmr": bmr,
        "tdee": tdee,
        "bmi": bmi_val,
        "bmi_category": bmi_category(bmi_val) if bmi_val else "",
        "weight_trend": weight_trend,
        "composition_trend": composition,
        "avg_daily_cal": avg_cal,
        "macro_split": {
            "protein_g": round(total_pro / max(days_logged, 1)),
            "carbs_g": round(total_carbs / max(days_logged, 1)),
            "fats_g": round(total_fats / max(days_logged, 1)),
        },
        "macro_targets": macro_targets,
        "days_logged": days_logged,
        "hydration_avg": h_avg,
        "hydration_target": h_target,
        "exercise_summary": {
            "sessions": len(exercises),
            "total_kcal": round(ex_total_kcal),
            "total_min": round(ex_total_min),
            "types": ex_types,
        },
        "sleep_summary": sleep_summary,
        "cycle_info": cycle_info,
        "blood_summary": blood_summary,
        "calorie_balance": calorie_balance,
    }


# ============================================================================
# CONTEXT INJECTION — 14-day user snapshot for conversational AI
# ============================================================================

def build_user_context(user_id: int) -> str:
    """Fetch 14 days of data from ALL tabs and return a structured text block.

    This context is injected into Gemini for free-form questions, analysis,
    planning, education, and proactive insights.
    """
    profile = sheets.get_profile(user_id)
    if not profile:
        return ""

    # --- Computed baselines ---
    bmr = get_bmr_for_user(user_id)
    tdee = get_tdee_for_user(user_id)
    bmi_val = 0.0

    # --- Food (14 days) ---
    food = sheets.get_food(user_id, days=14)
    today_food = [f for f in food if f.get("date") == sheets.today()]
    today_cal = sum(float(f.get("calories", 0)) for f in today_food)
    today_pro = sum(float(f.get("protein_g", 0)) for f in today_food)
    today_carbs = sum(float(f.get("carbs_g", 0)) for f in today_food)
    today_fats = sum(float(f.get("fats_g", 0)) for f in today_food)
    remaining_cal = round(max(0, tdee - today_cal))
    macro_targets = calculate_macro_targets(tdee)
    remaining_pro = round(max(0, macro_targets["protein_g"] - today_pro))

    days_with_food = {f.get("date") for f in food}
    avg_cal_14d = round(
        sum(float(f.get("calories", 0)) for f in food) / max(len(days_with_food), 1)
    )

    # --- Biometrics / Weight (14 days) ---
    bio = sheets.get_biometrics(user_id, days=14)
    weight_section = "אין מדידות אחרונות"
    if bio:
        latest = bio[-1]
        w = float(latest.get("weight_kg", 0))
        bmi_val = calculate_bmi(w, float(profile.get("height_cm", 170)))
        weight_section = (
            f"משקל אחרון: {w} ק\"ג | BMI: {bmi_val} ({bmi_category(bmi_val)})\n"
            f"שומן: {latest.get('body_fat_pct', '?')}% | שריר: {latest.get('muscle_mass_kg', '?')} ק\"ג"
        )
        if len(bio) >= 2:
            delta = round(float(bio[-1].get("weight_kg", 0)) - float(bio[0].get("weight_kg", 0)), 1)
            weight_section += f"\nשינוי ב-14 יום: {delta:+.1f} ק\"ג"

    # --- Hydration ---
    hydration = sheets.get_hydration(user_id, days=14)
    today_water = sum(
        float(h.get("liters", 0)) for h in hydration if h.get("date") == sheets.today()
    )
    h_target = calculate_hydration_target(
        exercise_entries=sheets.get_exercise(user_id, days=1)
    )

    # --- Exercise (14 days) ---
    exercises = sheets.get_exercise(user_id, days=14)
    today_ex = [e for e in exercises if e.get("date") == sheets.today()]
    today_ex_kcal = sum(float(e.get("estimated_kcal", 0)) for e in today_ex)
    ex_summary_lines = []
    for e in exercises[-7:]:
        ex_summary_lines.append(
            f"  {e.get('date')}: {e.get('type')} {e.get('duration_min')}דק׳ "
            f"עצימות {e.get('intensity')}/10 → {e.get('estimated_kcal')} קק\"ל"
        )

    # --- Sleep / Wearable (14 days) ---
    wearable = sheets.get_wearable(user_id, days=14)
    sleep_section = "אין נתוני שינה"
    if wearable:
        latest_w = wearable[-1]
        avg_sleep = round(
            sum(float(w.get("sleep_hours", 0)) for w in wearable) / len(wearable), 1
        )
        avg_steps = round(
            sum(float(w.get("steps", 0)) for w in wearable) / len(wearable)
        )
        sleep_section = (
            f"שינה אחרונה: {latest_w.get('sleep_hours')}h ({latest_w.get('sleep_quality')})\n"
            f"ממוצע 14 יום: {avg_sleep}h שינה | {avg_steps} צעדים"
        )

    # --- Cycle ---
    phase = sheets.get_current_phase(user_id)
    cycle_section = "לא רלוונטי"
    if phase:
        adj = get_cycle_adjustments(phase)
        cycle_section = (
            f"שלב נוכחי: {phase}\n"
            f"התאמת קלוריות: {adj['calorie_adjustment']:+d} | "
            f"עצימות מומלצת: {adj['recommended_intensity']}\n"
            f"{adj['weight_fluctuation_note']}\n"
            f"ברזל: {adj['iron_note']}"
        )

    # --- Blood Work ---
    blood = sheets.get_blood_work(user_id)
    blood_section = "אין בדיקות דם"
    if blood:
        latest_blood = blood[-1]
        ranges = check_blood_ranges(latest_blood)
        flags = ranges.get("flags", [])
        blood_section = f"בדיקה אחרונה: {latest_blood.get('date', '?')}\n"
        if flags:
            blood_section += "חריגים:\n" + "\n".join(f"  {f}" for f in flags)
        else:
            blood_section += "כל הסמנים תקינים"

    # --- Assemble context ---
    return f"""=== פרופיל ===
{profile.get('name', '?')}, גיל {profile.get('age', '?')}, {profile.get('gender', '?')}
גובה: {profile.get('height_cm', '?')}cm
BMR: {bmr:.0f} | TDEE: {tdee:.0f} קק"ל

=== משקל והרכב גוף ===
{weight_section}

=== תזונה היום ===
קלוריות: {today_cal:.0f} / {tdee:.0f} (נותרו {remaining_cal})
חלבון: {today_pro:.0f}g / {macro_targets['protein_g']}g (נותרו {remaining_pro}g)
פחמימות: {today_carbs:.0f}g | שומן: {today_fats:.0f}g
ממוצע 14 יום: {avg_cal_14d} קק"ל/יום

=== שתייה ===
היום: {today_water:.1f} / {h_target:.1f} ליטר

=== אימונים (אחרונים) ===
אימון היום: {today_ex_kcal:.0f} קק"ל ({len(today_ex)} אימונים)
{chr(10).join(ex_summary_lines) if ex_summary_lines else "אין אימונים אחרונים"}

=== שינה וצעדים ===
{sleep_section}

=== מחזור ===
{cycle_section}

=== בדיקות דם ===
{blood_section}

=== יעדי מאקרו יומיים ===
חלבון: {macro_targets['protein_g']}g | פחמימות: {macro_targets['carbs_g']}g | שומן: {macro_targets['fats_g']}g
"""
