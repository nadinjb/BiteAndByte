"""Google Sheets data layer for BiteAndByte health bot."""

from datetime import datetime, timedelta

import gspread
from google.oauth2.service_account import Credentials

import config

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
# Worksheet accessors (auto-created on first use)
# ---------------------------------------------------------------------------

def profiles_ws() -> gspread.Worksheet:
    return _get_or_create_worksheet(
        config.WS_PROFILES,
        ["user_id", "name", "age", "gender", "height_cm", "initial_weight_kg"],
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _records_for_user(ws_fn, user_id: int, days: int) -> list[dict]:
    ws = ws_fn()
    records = ws.get_all_records()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return [
        r for r in records
        if str(r.get("user_id")) == str(user_id) and r.get("date", "") >= cutoff
    ]


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

def get_profile(user_id: int) -> dict | None:
    ws = profiles_ws()
    records = ws.get_all_records()
    for r in records:
        if str(r.get("user_id")) == str(user_id):
            return r
    return None


def save_profile(
    user_id: int, name: str, age: int, gender: str,
    height_cm: float, initial_weight_kg: float,
) -> None:
    ws = profiles_ws()
    records = ws.get_all_records()
    for idx, r in enumerate(records):
        if str(r.get("user_id")) == str(user_id):
            row_num = idx + 2
            ws.update(f"A{row_num}:F{row_num}", [[
                str(user_id), name, age, gender, height_cm, initial_weight_kg,
            ]])
            return
    ws.append_row(
        [str(user_id), name, age, gender, height_cm, initial_weight_kg],
        value_input_option="RAW",
    )


# ---------------------------------------------------------------------------
# Biometrics
# ---------------------------------------------------------------------------

def log_biometrics(
    user_id: int, weight: float, body_fat: float,
    water: float, bone_mass: float, muscle_mass: float,
) -> None:
    ws = biometrics_ws()
    ws.append_row(
        [str(user_id), today(), weight, body_fat, water, bone_mass, muscle_mass],
        value_input_option="RAW",
    )


def get_biometrics(user_id: int, days: int = 7) -> list[dict]:
    return _records_for_user(biometrics_ws, user_id, days)


# ---------------------------------------------------------------------------
# Food (with local cache for Gemini token savings)
# ---------------------------------------------------------------------------

def log_food(
    user_id: int, item: str, calories: float,
    protein: float, carbs: float, fats: float,
) -> None:
    ws = food_ws()
    ws.append_row(
        [str(user_id), today(), item, calories, protein, carbs, fats],
        value_input_option="RAW",
    )


def get_food(user_id: int, days: int = 7) -> list[dict]:
    return _records_for_user(food_ws, user_id, days)


def find_cached_food(user_id: int, search_term: str) -> list[dict]:
    """Search previous food entries for a matching item (local cache).

    Returns matching entries so Gemini can use them as reference instead of
    re-analyzing from scratch — saves API tokens.
    """
    ws = food_ws()
    records = ws.get_all_records()
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
    records = ws.get_all_records()
    for idx, r in enumerate(records):
        if str(r.get("user_id")) == str(user_id) and r.get("date") == today():
            row_num = idx + 2
            new_total = float(r.get("liters", 0)) + liters
            ws.update_cell(row_num, 3, new_total)
            return
    ws.append_row(
        [str(user_id), today(), liters],
        value_input_option="RAW",
    )


def get_hydration(user_id: int, days: int = 7) -> list[dict]:
    return _records_for_user(hydration_ws, user_id, days)


# ---------------------------------------------------------------------------
# Exercise
# ---------------------------------------------------------------------------

def log_exercise(
    user_id: int, exercise_type: str, duration_min: int,
    intensity: int, estimated_kcal: float,
) -> None:
    ws = exercise_ws()
    ws.append_row(
        [str(user_id), today(), exercise_type, duration_min, intensity, estimated_kcal],
        value_input_option="RAW",
    )


def get_exercise(user_id: int, days: int = 7) -> list[dict]:
    return _records_for_user(exercise_ws, user_id, days)


# ---------------------------------------------------------------------------
# Cycle Tracking
# ---------------------------------------------------------------------------

def log_cycle(user_id: int, phase: str, notes: str = "") -> None:
    ws = cycle_ws()
    ws.append_row(
        [str(user_id), today(), phase, notes],
        value_input_option="RAW",
    )


def get_cycle(user_id: int, days: int = 30) -> list[dict]:
    return _records_for_user(cycle_ws, user_id, days)


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
    ws.append_row(row, value_input_option="RAW")


def get_blood_work(user_id: int) -> list[dict]:
    ws = blood_ws()
    records = ws.get_all_records()
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
    ws.append_row(
        [str(user_id), today(), steps, sleep_hours, sleep_quality],
        value_input_option="RAW",
    )


def get_wearable(user_id: int, days: int = 7) -> list[dict]:
    return _records_for_user(wearable_ws, user_id, days)


def get_latest_wearable(user_id: int) -> dict | None:
    entries = get_wearable(user_id, days=2)
    return entries[-1] if entries else None
