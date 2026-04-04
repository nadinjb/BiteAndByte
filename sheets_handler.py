"""Google Sheets data layer for BiteAndByte health bot.

Includes TTL caching (60s) and retry with backoff for 429 rate limits.
"""

import logging
import time
from datetime import datetime, timedelta

import gspread
from google.oauth2.service_account import Credentials

import config

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_client: gspread.Client | None = None


def _get_client() -> gspread.Client:
    global _client
    if _client is None:
        creds = Credentials.from_service_account_file(
            config.GOOGLE_CREDENTIALS_FILE, scopes=SCOPES
        )
        _client = gspread.authorize(creds)
    return _client


def _get_sheet() -> gspread.Spreadsheet:
    return _get_client().open_by_key(config.GOOGLE_SHEET_ID)


def _get_or_create_worksheet(
    name: str, headers: list[str]
) -> gspread.Worksheet:
    sheet = _get_sheet()
    try:
        ws = sheet.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=name, rows=1000, cols=len(headers))
        ws.append_row(headers, value_input_option="RAW")
    return ws


# ---------------------------------------------------------------------------
# Retry with exponential backoff for 429 rate limits
# ---------------------------------------------------------------------------

def _retry(func, *args, max_retries: int = 3, **kwargs):
    """Call *func* with retry + exponential backoff on 429 / quota errors."""
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except gspread.exceptions.APIError as e:
            status = e.response.status_code if hasattr(e, "response") else 0
            if status == 429 and attempt < max_retries - 1:
                wait = 2 ** attempt * 5  # 5s, 10s, 20s
                logger.warning("Sheets 429 rate limit, retrying in %ds...", wait)
                time.sleep(wait)
                continue
            raise
    return None  # unreachable, but keeps type checkers happy


# ---------------------------------------------------------------------------
# TTL Cache — avoids repeated get_all_records() calls within 60s
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL = 60  # seconds


def _get_records_cached(ws_fn, ws_name: str) -> list[dict]:
    """Return cached get_all_records() for a worksheet, refreshing every 60s."""
    now = time.time()
    if ws_name in _cache:
        ts, records = _cache[ws_name]
        if now - ts < _CACHE_TTL:
            return records
    ws = ws_fn()
    records = _retry(ws.get_all_records)
    _cache[ws_name] = (now, records)
    return records


def _invalidate_cache(ws_name: str) -> None:
    """Clear cache for a worksheet after a write operation."""
    _cache.pop(ws_name, None)


def invalidate_all_caches() -> None:
    """Clear all cached records (useful after batch operations)."""
    _cache.clear()


# ---------------------------------------------------------------------------
# Worksheet accessors (auto-created on first use)
# ---------------------------------------------------------------------------

def profiles_ws() -> gspread.Worksheet:
    return _get_or_create_worksheet(
        config.WS_PROFILES,
        ["user_id", "name", "age", "gender", "height_cm", "initial_weight_kg",
         "activity_level", "goal"],
    )


def biometrics_ws() -> gspread.Worksheet:
    return _get_or_create_worksheet(
        config.WS_BIOMETRICS,
        [
            "user_id", "date", "weight_kg", "body_fat_pct",
            "water_pct", "bone_mass_kg", "muscle_mass_kg",
        ],
    )


def food_ws() -> gspread.Worksheet:
    return _get_or_create_worksheet(
        config.WS_FOOD,
        ["user_id", "date", "item", "calories", "protein_g", "carbs_g", "fats_g"],
    )


def hydration_ws() -> gspread.Worksheet:
    return _get_or_create_worksheet(
        config.WS_HYDRATION,
        ["user_id", "date", "liters"],
    )


def exercise_ws() -> gspread.Worksheet:
    return _get_or_create_worksheet(
        config.WS_EXERCISE,
        [
            "user_id", "date", "type", "duration_min",
            "intensity", "estimated_kcal",
        ],
    )


def cycle_ws() -> gspread.Worksheet:
    return _get_or_create_worksheet(
        config.WS_CYCLE,
        ["user_id", "date", "phase", "notes"],
    )


def blood_ws() -> gspread.Worksheet:
    return _get_or_create_worksheet(
        config.WS_BLOOD,
        [
            "user_id", "date", "glucose_mg_dl", "hba1c_pct",
            "cholesterol_total", "hdl", "ldl", "triglycerides",
            "iron", "ferritin", "vitamin_d", "b12", "tsh",
            "crp", "notes",
        ],
    )


def wearable_ws() -> gspread.Worksheet:
    return _get_or_create_worksheet(
        config.WS_WEARABLE,
        ["user_id", "date", "steps", "sleep_hours", "sleep_quality"],
    )


def food_cache_ws() -> gspread.Worksheet:
    return _get_or_create_worksheet(
        "Food_Cache",
        ["user_id", "item", "grams", "calories", "protein_g", "carbs_g", "fats_g"],
    )


def food_library_ws() -> gspread.Worksheet:
    """Global shared Food_Library — per-100g values, no user_id."""
    return _get_or_create_worksheet(
        config.WS_FOOD_LIBRARY,
        ["item", "calories", "protein_g", "carbs_g", "fats_g", "date"],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _records_for_user(ws_fn, ws_name: str, user_id: int, days: int) -> list[dict]:
    """Get recent records for a user from cache."""
    records = _get_records_cached(ws_fn, ws_name)
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return [
        r for r in records
        if str(r.get("user_id")) == str(user_id) and r.get("date", "") >= cutoff
    ]


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

def get_profile(user_id: int) -> dict | None:
    records = _get_records_cached(profiles_ws, config.WS_PROFILES)
    for r in records:
        if str(r.get("user_id")) == str(user_id):
            return r
    return None


def save_profile(
    user_id: int, name: str, age: int, gender: str,
    height_cm: float, initial_weight_kg: float,
    activity_level: str = "sedentary",
    goal: str = "maintain",
) -> None:
    ws = profiles_ws()
    records = _retry(ws.get_all_records)
    row_data = [str(user_id), name, age, gender, height_cm, initial_weight_kg,
                activity_level, goal]
    for idx, r in enumerate(records):
        if str(r.get("user_id")) == str(user_id):
            row_num = idx + 2
            _retry(ws.update, f"A{row_num}:H{row_num}", [row_data])
            _invalidate_cache(config.WS_PROFILES)
            return
    _retry(ws.append_row, row_data, value_input_option="RAW")
    _invalidate_cache(config.WS_PROFILES)


# ---------------------------------------------------------------------------
# Biometrics
# ---------------------------------------------------------------------------

def log_biometrics(
    user_id: int, weight: float, body_fat: float,
    water: float, bone_mass: float, muscle_mass: float,
) -> None:
    ws = biometrics_ws()
    _retry(
        ws.append_row,
        [str(user_id), today(), weight, body_fat, water, bone_mass, muscle_mass],
        value_input_option="RAW",
    )
    _invalidate_cache(config.WS_BIOMETRICS)


def get_biometrics(user_id: int, days: int = 7) -> list[dict]:
    return _records_for_user(biometrics_ws, config.WS_BIOMETRICS, user_id, days)


# ---------------------------------------------------------------------------
# Food (with local cache for Gemini token savings)
# ---------------------------------------------------------------------------

def log_food(
    user_id: int, item: str, calories: float,
    protein: float, carbs: float, fats: float,
) -> None:
    ws = food_ws()
    _retry(
        ws.append_row,
        [str(user_id), today(), item, calories, protein, carbs, fats],
        value_input_option="RAW",
    )
    _invalidate_cache(config.WS_FOOD)


def get_food(user_id: int, days: int = 7) -> list[dict]:
    return _records_for_user(food_ws, config.WS_FOOD, user_id, days)


# Column indices in Food_Log: A=user_id, B=date, C=item, D=calories, E=protein, F=carbs, G=fats
_FOOD_COL = {"calories": 4, "protein": 5, "carbs": 6, "fats": 7}


def fix_last_food_entry(user_id: int, field: str, value: float) -> dict | None:
    """Update a single field in the user's most recent Food_Log row.

    Returns the updated row as a dict, or None if no entry found.
    """
    col = _FOOD_COL.get(field)
    if col is None:
        return None
    ws = food_ws()
    records = _retry(ws.get_all_records)
    # Find last row for this user
    last_idx = None
    for idx, r in enumerate(records):
        if str(r.get("user_id")) == str(user_id):
            last_idx = idx
    if last_idx is None:
        return None
    row_num = last_idx + 2  # +1 header, +1 zero-index
    _retry(ws.update_cell, row_num, col, value)
    _invalidate_cache(config.WS_FOOD)
    # Return updated record
    records[last_idx][field + ("_g" if field != "calories" else "")] = value
    return records[last_idx]


def find_cached_food(user_id: int, search_term: str) -> list[dict]:
    """Search previous food entries for a matching item (local cache)."""
    records = _get_records_cached(food_ws, config.WS_FOOD)
    term = search_term.lower()
    return [
        r for r in records
        if str(r.get("user_id")) == str(user_id)
        and term in str(r.get("item", "")).lower()
    ][:5]


# ---------------------------------------------------------------------------
# Hydration
# ---------------------------------------------------------------------------

def log_hydration(user_id: int, liters: float) -> None:
    ws = hydration_ws()
    records = _get_records_cached(hydration_ws, config.WS_HYDRATION)
    for idx, r in enumerate(records):
        if str(r.get("user_id")) == str(user_id) and r.get("date") == today():
            row_num = idx + 2
            new_total = float(r.get("liters", 0)) + liters
            _retry(ws.update_cell, row_num, 3, new_total)
            _invalidate_cache(config.WS_HYDRATION)
            return
    _retry(ws.append_row, [str(user_id), today(), liters], value_input_option="RAW")
    _invalidate_cache(config.WS_HYDRATION)


def get_hydration(user_id: int, days: int = 7) -> list[dict]:
    return _records_for_user(hydration_ws, config.WS_HYDRATION, user_id, days)


# ---------------------------------------------------------------------------
# Exercise
# ---------------------------------------------------------------------------

def log_exercise(
    user_id: int, exercise_type: str, duration_min: int,
    intensity: int, estimated_kcal: float,
) -> None:
    ws = exercise_ws()
    _retry(
        ws.append_row,
        [str(user_id), today(), exercise_type, duration_min, intensity, estimated_kcal],
        value_input_option="RAW",
    )
    _invalidate_cache(config.WS_EXERCISE)


def get_exercise(user_id: int, days: int = 7) -> list[dict]:
    return _records_for_user(exercise_ws, config.WS_EXERCISE, user_id, days)


# ---------------------------------------------------------------------------
# Cycle Tracking
# ---------------------------------------------------------------------------

def log_cycle(user_id: int, phase: str, notes: str = "") -> None:
    ws = cycle_ws()
    _retry(
        ws.append_row,
        [str(user_id), today(), phase, notes],
        value_input_option="RAW",
    )
    _invalidate_cache(config.WS_CYCLE)


def get_cycle(user_id: int, days: int = 30) -> list[dict]:
    return _records_for_user(cycle_ws, config.WS_CYCLE, user_id, days)


def get_current_phase(user_id: int) -> str | None:
    entries = get_cycle(user_id, days=7)
    if entries:
        return entries[-1].get("phase")
    return None


# ---------------------------------------------------------------------------
# Blood Work
# ---------------------------------------------------------------------------

def log_blood_work(user_id: int, markers: dict) -> None:
    ws = blood_ws()
    row = [str(user_id), today()]
    for col in [
        "glucose_mg_dl", "hba1c_pct", "cholesterol_total", "hdl", "ldl",
        "triglycerides", "iron", "ferritin", "vitamin_d", "b12", "tsh",
        "crp", "notes",
    ]:
        row.append(markers.get(col, ""))
    _retry(ws.append_row, row, value_input_option="RAW")
    _invalidate_cache(config.WS_BLOOD)


def get_blood_work(user_id: int) -> list[dict]:
    records = _get_records_cached(blood_ws, config.WS_BLOOD)
    return [
        r for r in records
        if str(r.get("user_id")) == str(user_id)
    ]


# ---------------------------------------------------------------------------
# Wearable Sync (Steps & Sleep)
# ---------------------------------------------------------------------------

def log_wearable(
    user_id: int, steps: int, sleep_hours: float, sleep_quality: str,
) -> None:
    ws = wearable_ws()
    _retry(
        ws.append_row,
        [str(user_id), today(), steps, sleep_hours, sleep_quality],
        value_input_option="RAW",
    )
    _invalidate_cache(config.WS_WEARABLE)


def get_wearable(user_id: int, days: int = 7) -> list[dict]:
    return _records_for_user(wearable_ws, config.WS_WEARABLE, user_id, days)


def get_latest_wearable(user_id: int) -> dict | None:
    entries = get_wearable(user_id, days=2)
    return entries[-1] if entries else None


# ---------------------------------------------------------------------------
# Food Cache — learned corrections (Rule #3)
# ---------------------------------------------------------------------------

def save_food_cache(
    user_id: int, item: str, grams: float,
    calories: float, protein: float, carbs: float, fats: float,
) -> None:
    """Save or update a cached food item for a user."""
    ws = food_cache_ws()
    records = _retry(ws.get_all_records)
    term = item.strip().lower()
    row_data = [str(user_id), item, grams, calories, protein, carbs, fats]
    for idx, r in enumerate(records):
        if str(r.get("user_id")) == str(user_id) and str(r.get("item", "")).lower() == term:
            row_num = idx + 2
            _retry(ws.update, f"A{row_num}:G{row_num}", [row_data])
            _invalidate_cache("Food_Cache")
            return
    _retry(ws.append_row, row_data, value_input_option="RAW")
    _invalidate_cache("Food_Cache")


def lookup_food_cache(user_id: int, search_term: str) -> list[dict]:
    """Search Food_Cache for matching items. Returns best matches."""
    records = _get_records_cached(food_cache_ws, "Food_Cache")
    term = search_term.strip().lower()
    return [
        r for r in records
        if str(r.get("user_id")) == str(user_id)
        and (term in str(r.get("item", "")).lower()
             or str(r.get("item", "")).lower() in term)
    ][:5]


# ---------------------------------------------------------------------------
# Food_Library — global fuzzy-learning database
# ---------------------------------------------------------------------------

def find_food_fuzzy(
    item_name: str, user_id: int = 0, threshold: int = 85,
) -> dict | None:
    """Fuzzy-match item_name against Food_Cache (user) and Food_Library (global).

    Returns a normalized per-100g dict or None if no match >= threshold.
    User-specific Food_Cache entries are checked first and take priority.
    """
    from rapidfuzz import process, fuzz  # lazy import — only when called

    query = item_name.strip()
    if not query:
        return None

    # 1. User's personal Food_Cache (per-serving values → normalize to per-100g)
    if user_id:
        cache_recs = _get_records_cached(food_cache_ws, "Food_Cache")
        user_recs = [r for r in cache_recs if str(r.get("user_id")) == str(user_id)]
        if user_recs:
            names = [str(r.get("item", "")) for r in user_recs]
            match = process.extractOne(query, names, scorer=fuzz.WRatio)
            if match and match[1] >= threshold:
                r = user_recs[match[2]]
                try:
                    ref_g = float(r.get("grams") or 100)
                    factor = 100.0 / max(ref_g, 1)
                    return {
                        "calories_per_100": round(float(r.get("calories", 0)) * factor, 1),
                        "protein_per_100": round(float(r.get("protein_g", 0)) * factor, 1),
                        "carbs_per_100": round(float(r.get("carbs_g", 0)) * factor, 1),
                        "fats_per_100": round(float(r.get("fats_g", 0)) * factor, 1),
                        "match_name": r.get("item"),
                        "match_score": round(match[1]),
                        "source": "cache",
                    }
                except (ValueError, TypeError):
                    pass

    # 2. Global Food_Library (already stored per-100g)
    lib_recs = _get_records_cached(food_library_ws, config.WS_FOOD_LIBRARY)
    if lib_recs:
        names = [str(r.get("item", "")) for r in lib_recs]
        match = process.extractOne(query, names, scorer=fuzz.WRatio)
        if match and match[1] >= threshold:
            r = lib_recs[match[2]]
            try:
                return {
                    "calories_per_100": round(float(r.get("calories", 0)), 1),
                    "protein_per_100": round(float(r.get("protein_g", 0)), 1),
                    "carbs_per_100": round(float(r.get("carbs_g", 0)), 1),
                    "fats_per_100": round(float(r.get("fats_g", 0)), 1),
                    "match_name": r.get("item"),
                    "match_score": round(match[1]),
                    "source": "library",
                }
            except (ValueError, TypeError):
                pass

    return None


def save_to_library(
    item: str,
    calories_per_100: float,
    protein_per_100: float,
    carbs_per_100: float,
    fats_per_100: float,
) -> None:
    """Save or update a food item in the global Food_Library (per-100g values).

    Called after /correct so the bot learns the item for all future users.
    """
    ws = food_library_ws()
    records = _retry(ws.get_all_records)
    term = item.strip().lower()
    row_data = [
        item,
        round(calories_per_100, 1),
        round(protein_per_100, 1),
        round(carbs_per_100, 1),
        round(fats_per_100, 1),
        today(),
    ]
    for idx, r in enumerate(records):
        if str(r.get("item", "")).lower() == term:
            row_num = idx + 2
            _retry(ws.update, f"A{row_num}:F{row_num}", [row_data])
            _invalidate_cache(config.WS_FOOD_LIBRARY)
            return
    _retry(ws.append_row, row_data, value_input_option="RAW")
    _invalidate_cache(config.WS_FOOD_LIBRARY)


def update_last_log(user_id: int, new_values: dict) -> dict | None:
    """Update multiple nutrition fields in the user's most recent Food_Log row.

    new_values keys: "calories", "protein", "carbs", "fats" (any subset).
    Returns the updated row dict or None if no entry found.
    """
    ws = food_ws()
    records = _retry(ws.get_all_records)
    last_idx = None
    for idx, r in enumerate(records):
        if str(r.get("user_id")) == str(user_id):
            last_idx = idx
    if last_idx is None:
        return None
    row_num = last_idx + 2  # +1 header, +1 zero-index
    for field, value in new_values.items():
        col = _FOOD_COL.get(field)
        if col and value is not None:
            _retry(ws.update_cell, row_num, col, float(value))
    _invalidate_cache(config.WS_FOOD)
    # Return updated record
    record = dict(records[last_idx])
    for field, value in new_values.items():
        key = field + ("_g" if field != "calories" else "")
        record[key] = value
    return record


# ---------------------------------------------------------------------------
# Bulk data fetch — single API call per worksheet for heavy operations
# ---------------------------------------------------------------------------

def get_all_user_data(user_id: int, days: int = 14) -> dict:
    """Fetch all data for a user across all tabs in one pass.

    Returns a dict with keys: profile, food, biometrics, hydration,
    exercise, cycle, wearable, blood. Each is filtered for user_id
    and date range (except profile and blood which return all).

    This replaces 10+ individual API calls with cached reads.
    """
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    uid = str(user_id)

    def _user_recent(ws_fn, ws_name):
        return [
            r for r in _get_records_cached(ws_fn, ws_name)
            if str(r.get("user_id")) == uid and r.get("date", "") >= cutoff
        ]

    profile = get_profile(user_id)

    return {
        "profile": profile,
        "food": _user_recent(food_ws, config.WS_FOOD),
        "biometrics": _user_recent(biometrics_ws, config.WS_BIOMETRICS),
        "hydration": _user_recent(hydration_ws, config.WS_HYDRATION),
        "exercise": _user_recent(exercise_ws, config.WS_EXERCISE),
        "cycle": _user_recent(cycle_ws, config.WS_CYCLE),
        "wearable": _user_recent(wearable_ws, config.WS_WEARABLE),
        "blood": [
            r for r in _get_records_cached(blood_ws, config.WS_BLOOD)
            if str(r.get("user_id")) == uid
        ],
    }
