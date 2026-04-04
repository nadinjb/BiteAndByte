"""Local nutrition database — per 100g values for common foods.

Used by the Python math layer so Gemini never does calorie calculations.
Gemini extracts the food item + grams, Python multiplies from this table.
"""
from rapidfuzz import process, fuzz as _fuzz

# Format: "food_key": (calories, protein_g, carbs_g, fats_g)  per 100g
FOODS: dict[str, tuple[float, float, float, float]] = {
    # --- Proteins ---
    "chicken_breast": (165, 31.0, 0.0, 3.6),
    "חזה עוף": (165, 31.0, 0.0, 3.6),
    "chicken_thigh": (209, 26.0, 0.0, 10.9),
    "שוק עוף": (209, 26.0, 0.0, 10.9),
    "turkey_breast": (135, 30.0, 0.0, 1.0),
    "חזה הודו": (135, 30.0, 0.0, 1.0),
    "beef_lean": (250, 26.0, 0.0, 15.0),
    "בקר רזה": (250, 26.0, 0.0, 15.0),
    "ground_beef": (254, 17.2, 0.0, 20.0),
    "בשר טחון": (254, 17.2, 0.0, 20.0),
    "salmon": (208, 20.0, 0.0, 13.0),
    "סלמון": (208, 20.0, 0.0, 13.0),
    "tuna": (130, 28.0, 0.0, 1.0),
    "טונה": (130, 28.0, 0.0, 1.0),
    "tilapia": (96, 20.0, 0.0, 1.7),
    "טילאפיה": (96, 20.0, 0.0, 1.7),
    "shrimp": (99, 24.0, 0.2, 0.3),
    "שרימפס": (99, 24.0, 0.2, 0.3),
    "tofu": (76, 8.0, 1.9, 4.8),
    "טופו": (76, 8.0, 1.9, 4.8),
    "tempeh": (192, 20.0, 7.6, 11.0),

    # --- Eggs & Dairy ---
    "egg": (155, 13.0, 1.1, 11.0),
    "ביצה": (155, 13.0, 1.1, 11.0),
    "egg_white": (52, 11.0, 0.7, 0.2),
    "חלבון ביצה": (52, 11.0, 0.7, 0.2),
    "cottage_cheese": (98, 11.0, 3.4, 4.3),
    "קוטג": (98, 11.0, 3.4, 4.3),
    "greek_yogurt": (59, 10.0, 3.6, 0.4),
    "יוגורט יווני": (59, 10.0, 3.6, 0.4),
    "yogurt": (61, 3.5, 4.7, 3.3),
    "יוגורט": (61, 3.5, 4.7, 3.3),
    "milk": (42, 3.4, 5.0, 1.0),
    "חלב": (42, 3.4, 5.0, 1.0),
    "cheese_yellow": (402, 25.0, 1.3, 33.0),
    "גבינה צהובה": (402, 25.0, 1.3, 33.0),
    "cream_cheese": (342, 6.0, 4.0, 34.0),
    "גבינת שמנת": (342, 6.0, 4.0, 34.0),
    "feta": (264, 14.0, 4.1, 21.0),
    "פטה": (264, 14.0, 4.1, 21.0),
    "labane": (159, 6.0, 4.0, 13.0),
    "לבנה": (159, 6.0, 4.0, 13.0),
    "whey_protein": (400, 80.0, 10.0, 5.0),
    "אבקת חלבון": (400, 80.0, 10.0, 5.0),

    # --- Grains & Carbs ---
    "rice_white": (130, 2.7, 28.0, 0.3),
    "אורז לבן": (130, 2.7, 28.0, 0.3),
    "אורז": (130, 2.7, 28.0, 0.3),
    "rice_brown": (123, 2.6, 25.6, 1.0),
    "אורז מלא": (123, 2.6, 25.6, 1.0),
    "pasta": (131, 5.0, 25.0, 1.1),
    "פסטה": (131, 5.0, 25.0, 1.1),
    "bread_white": (265, 9.0, 49.0, 3.2),
    "לחם לבן": (265, 9.0, 49.0, 3.2),
    "לחם": (265, 9.0, 49.0, 3.2),
    "bread_whole": (247, 13.0, 41.0, 3.4),
    "לחם מלא": (247, 13.0, 41.0, 3.4),
    "oats": (389, 16.9, 66.3, 6.9),
    "שיבולת שועל": (389, 16.9, 66.3, 6.9),
    "quinoa": (120, 4.4, 21.3, 1.9),
    "קינואה": (120, 4.4, 21.3, 1.9),
    "potato": (77, 2.0, 17.0, 0.1),
    "תפוח אדמה": (77, 2.0, 17.0, 0.1),
    "תפוא": (77, 2.0, 17.0, 0.1),
    "sweet_potato": (86, 1.6, 20.0, 0.1),
    "בטטה": (86, 1.6, 20.0, 0.1),
    "corn": (86, 3.3, 19.0, 1.2),
    "תירס": (86, 3.3, 19.0, 1.2),
    "pita": (275, 9.0, 55.0, 1.2),
    "פיתה": (275, 9.0, 55.0, 1.2),
    "tortilla": (312, 8.0, 52.0, 8.0),
    "טורטיה": (312, 8.0, 52.0, 8.0),
    "couscous": (112, 3.8, 23.0, 0.2),
    "קוסקוס": (112, 3.8, 23.0, 0.2),
    "bulgur": (83, 3.1, 18.6, 0.2),
    "בורגול": (83, 3.1, 18.6, 0.2),

    # --- Legumes ---
    "lentils": (116, 9.0, 20.0, 0.4),
    "עדשים": (116, 9.0, 20.0, 0.4),
    "chickpeas": (164, 8.9, 27.4, 2.6),
    "חומוס": (164, 8.9, 27.4, 2.6),
    "hummus": (166, 7.9, 14.3, 9.6),
    "beans_black": (132, 8.9, 23.7, 0.5),
    "שעועית שחורה": (132, 8.9, 23.7, 0.5),
    "beans_white": (139, 9.7, 25.0, 0.5),
    "שעועית לבנה": (139, 9.7, 25.0, 0.5),
    "edamame": (121, 11.9, 8.9, 5.2),
    "אדממה": (121, 11.9, 8.9, 5.2),

    # --- Vegetables ---
    "salad_mixed": (20, 1.5, 3.0, 0.3),
    "סלט": (20, 1.5, 3.0, 0.3),
    "tomato": (18, 0.9, 3.9, 0.2),
    "עגבנייה": (18, 0.9, 3.9, 0.2),
    "cucumber": (15, 0.7, 3.6, 0.1),
    "מלפפון": (15, 0.7, 3.6, 0.1),
    "broccoli": (34, 2.8, 7.0, 0.4),
    "ברוקולי": (34, 2.8, 7.0, 0.4),
    "spinach": (23, 2.9, 3.6, 0.4),
    "תרד": (23, 2.9, 3.6, 0.4),
    "carrot": (41, 0.9, 9.6, 0.2),
    "גזר": (41, 0.9, 9.6, 0.2),
    "pepper": (31, 1.0, 6.0, 0.3),
    "פלפל": (31, 1.0, 6.0, 0.3),
    "onion": (40, 1.1, 9.3, 0.1),
    "בצל": (40, 1.1, 9.3, 0.1),
    "zucchini": (17, 1.2, 3.1, 0.3),
    "קישוא": (17, 1.2, 3.1, 0.3),
    "eggplant": (25, 1.0, 6.0, 0.2),
    "חציל": (25, 1.0, 6.0, 0.2),
    "cabbage": (25, 1.3, 5.8, 0.1),
    "כרוב": (25, 1.3, 5.8, 0.1),
    "cauliflower": (25, 1.9, 5.0, 0.3),
    "כרובית": (25, 1.9, 5.0, 0.3),
    "mushrooms": (22, 3.1, 3.3, 0.3),
    "פטריות": (22, 3.1, 3.3, 0.3),
    "avocado": (160, 2.0, 8.5, 14.7),
    "אבוקדו": (160, 2.0, 8.5, 14.7),

    # --- Fruits ---
    "banana": (89, 1.1, 22.8, 0.3),
    "בננה": (89, 1.1, 22.8, 0.3),
    "apple": (52, 0.3, 13.8, 0.2),
    "תפוח": (52, 0.3, 13.8, 0.2),
    "orange": (47, 0.9, 11.8, 0.1),
    "תפוז": (47, 0.9, 11.8, 0.1),
    "strawberries": (32, 0.7, 7.7, 0.3),
    "תותים": (32, 0.7, 7.7, 0.3),
    "blueberries": (57, 0.7, 14.5, 0.3),
    "אוכמניות": (57, 0.7, 14.5, 0.3),
    "watermelon": (30, 0.6, 7.6, 0.2),
    "אבטיח": (30, 0.6, 7.6, 0.2),
    "melon": (34, 0.8, 8.2, 0.2),
    "מלון": (34, 0.8, 8.2, 0.2),
    "grapes": (69, 0.7, 18.1, 0.2),
    "ענבים": (69, 0.7, 18.1, 0.2),
    "mango": (60, 0.8, 15.0, 0.4),
    "מנגו": (60, 0.8, 15.0, 0.4),
    "dates": (277, 1.8, 75.0, 0.2),
    "תמרים": (277, 1.8, 75.0, 0.2),
    "peach": (39, 0.9, 9.5, 0.3),
    "אפרסק": (39, 0.9, 9.5, 0.3),

    # --- Nuts & Seeds ---
    "almonds": (579, 21.0, 22.0, 49.9),
    "שקדים": (579, 21.0, 22.0, 49.9),
    "walnuts": (654, 15.0, 14.0, 65.2),
    "אגוזי מלך": (654, 15.0, 14.0, 65.2),
    "peanuts": (567, 25.8, 16.1, 49.2),
    "בוטנים": (567, 25.8, 16.1, 49.2),
    "cashews": (553, 18.2, 30.2, 43.9),
    "קשיו": (553, 18.2, 30.2, 43.9),
    "tahini": (595, 17.0, 21.2, 53.8),
    "טחינה": (595, 17.0, 21.2, 53.8),
    "peanut_butter": (588, 25.0, 20.0, 50.0),
    "חמאת בוטנים": (588, 25.0, 20.0, 50.0),
    "chia_seeds": (486, 17.0, 42.0, 31.0),
    "צ'יה": (486, 17.0, 42.0, 31.0),
    "flax_seeds": (534, 18.0, 29.0, 42.0),
    "זרעי פשתן": (534, 18.0, 29.0, 42.0),
    "sunflower_seeds": (584, 21.0, 20.0, 51.0),
    "גרעיני חמנייה": (584, 21.0, 20.0, 51.0),

    # --- Fats & Oils ---
    "olive_oil": (884, 0.0, 0.0, 100.0),
    "שמן זית": (884, 0.0, 0.0, 100.0),
    "coconut_oil": (862, 0.0, 0.0, 100.0),
    "שמן קוקוס": (862, 0.0, 0.0, 100.0),
    "butter": (717, 0.9, 0.1, 81.0),
    "חמאה": (717, 0.9, 0.1, 81.0),

    # --- Prepared / Common Israeli foods ---
    "schnitzel": (297, 18.0, 15.0, 18.0),
    "שניצל": (297, 18.0, 15.0, 18.0),
    "falafel": (333, 13.3, 31.8, 17.8),
    "פלאפל": (333, 13.3, 31.8, 17.8),
    "shawarma": (215, 19.0, 3.0, 14.0),
    "שווארמה": (215, 19.0, 3.0, 14.0),
    "shakshuka": (150, 9.0, 8.0, 9.0),
    "שקשוקה": (150, 9.0, 8.0, 9.0),
    "sabich": (450, 15.0, 40.0, 25.0),
    "סביח": (450, 15.0, 40.0, 25.0),
    "burekas": (350, 8.0, 30.0, 22.0),
    "בורקס": (350, 8.0, 30.0, 22.0),
    "jachnun": (380, 8.0, 45.0, 18.0),
    "ג'חנון": (380, 8.0, 45.0, 18.0),
    "malawach": (360, 7.0, 42.0, 18.0),
    "מלאווח": (360, 7.0, 42.0, 18.0),

    # --- Snacks & Sweets ---
    "granola_bar": (471, 10.0, 64.0, 20.0),
    "חטיף גרנולה": (471, 10.0, 64.0, 20.0),
    "dark_chocolate": (546, 5.0, 60.0, 31.0),
    "שוקולד מריר": (546, 5.0, 60.0, 31.0),
    "ice_cream": (207, 3.5, 24.0, 11.0),
    "גלידה": (207, 3.5, 24.0, 11.0),
    "rice_cakes": (387, 8.0, 81.0, 2.8),
    "פריכיות אורז": (387, 8.0, 81.0, 2.8),

    # --- Drinks ---
    "coffee_black": (2, 0.3, 0.0, 0.0),
    "קפה שחור": (2, 0.3, 0.0, 0.0),
    "latte": (67, 3.4, 5.3, 3.6),
    "לאטה": (67, 3.4, 5.3, 3.6),
    "orange_juice": (45, 0.7, 10.4, 0.2),
    "מיץ תפוזים": (45, 0.7, 10.4, 0.2),
    "smoothie": (68, 2.0, 13.0, 1.0),
    "סמוזי": (68, 2.0, 13.0, 1.0),
    "beer": (43, 0.5, 3.6, 0.0),
    "בירה": (43, 0.5, 3.6, 0.0),
    "wine": (83, 0.1, 2.6, 0.0),
    "יין": (83, 0.1, 2.6, 0.0),

    # --- Plant-based milks (per 100ml) ---
    "almond_milk": (13, 0.4, 0.5, 1.1),
    "חלב שקדים": (13, 0.4, 0.5, 1.1),
    "oat_milk": (46, 1.0, 6.6, 1.5),
    "חלב שיבולת שועל": (46, 1.0, 6.6, 1.5),
    "soy_milk": (33, 3.3, 0.5, 1.8),
    "חלב סויה": (33, 3.3, 0.5, 1.8),
}


# Brand-specific products with exact per-100g nutritional values.
# Checked BEFORE the generic FOODS dict — takes priority over substring matches.
BRANDS: dict[str, tuple[float, float, float, float]] = {
    # Alpro & plant-based milks (per 100ml)
    "alpro almond": (13, 0.4, 0.5, 1.1),
    "alpro oat": (46, 1.0, 6.6, 1.5),
    "alpro soy": (33, 3.3, 0.5, 1.8),
    "alpro": (13, 0.4, 0.5, 1.1),       # default to almond if unspecified
    "almond milk": (13, 0.4, 0.5, 1.1),
    "oat milk": (46, 1.0, 6.6, 1.5),
    "soy milk": (33, 3.3, 0.5, 1.8),
    "plant milk": (13, 0.4, 0.5, 1.1),

    # Muller (per 100g)
    "muller pro": (85, 11.5, 6.7, 1.2),
    "מולר פרו": (85, 11.5, 6.7, 1.2),
    "muller corner": (135, 4.0, 20.0, 4.0),
    "מולר קורנר": (135, 4.0, 20.0, 4.0),
    "muller": (85, 11.5, 6.7, 1.2),     # default to Pro
    "מולר": (85, 11.5, 6.7, 1.2),

    # Optimum Nutrition Gold Standard Whey (per 100g powder)
    "double rich chocolate": (390, 77.0, 9.0, 5.0),
    "gold standard whey": (390, 77.0, 9.0, 5.0),
    "on whey": (390, 77.0, 9.0, 5.0),
    "optimum nutrition": (390, 77.0, 9.0, 5.0),

    # Hebrew transliterations — cross-script fuzzy won't work, so aliases are explicit
    "דאבל ריץ": (390, 77.0, 9.0, 5.0),
    "דאבל ריץ שוקולד": (390, 77.0, 9.0, 5.0),
    "דאבל ריץ' שוקולט": (390, 77.0, 9.0, 5.0),
    "גולד סטנדרד": (390, 77.0, 9.0, 5.0),
    "גולד סטנדרט": (390, 77.0, 9.0, 5.0),
    "אופטימום ניוטרישן": (390, 77.0, 9.0, 5.0),
    "ON חלבון": (390, 77.0, 9.0, 5.0),
    "אלפרו": (13, 0.4, 0.5, 1.1),
    "אלפרו שקדים": (13, 0.4, 0.5, 1.1),
    "אלפרו שיבולת שועל": (46, 1.0, 6.6, 1.5),
    "אלפרו סויה": (33, 3.3, 0.5, 1.8),
}


def lookup(food_key: str) -> tuple[float, float, float, float] | None:
    """Look up per-100g nutrition values: (cal, protein, carbs, fats).

    Priority:
      1. BRANDS exact match
      2. BRANDS substring match (key ≥ 4 chars)
      3. FOODS exact match
      4. FOODS substring match (key ≥ 4 chars, prefers longest/most-specific)
      5. rapidfuzz fuzzy match across BRANDS + FOODS (same script, threshold 75)

    Step 5 catches typos and partial same-language matches.
    Cross-script matches (Hebrew input vs English DB key) rely on the explicit
    Hebrew aliases in BRANDS — rapidfuzz edit-distance cannot cross character sets.
    """
    key = food_key.strip().lower()

    # 1. Brand exact match
    if key in BRANDS:
        return BRANDS[key]

    # 2. Brand substring match
    for brand_key, values in BRANDS.items():
        if len(brand_key) >= 4 and (brand_key in key or key in brand_key):
            return values

    # 3. FOODS exact match
    if key in FOODS:
        return FOODS[key]

    # 4. FOODS substring match — require db_key >= 4 chars to avoid false positives
    #    (e.g., "milk" must not match "almond milk")
    best_match: tuple[float, float, float, float] | None = None
    best_len = 0
    for db_key, values in FOODS.items():
        if len(db_key) < 4:
            continue
        if db_key in key or key in db_key:
            if len(db_key) > best_len:
                best_match = values
                best_len = len(db_key)

    if best_match:
        return best_match

    # 5. Fuzzy match — handles typos and partial names within the same script.
    #    Merge BRANDS + FOODS; BRANDS keys take priority on equal scores.
    combined: dict[str, tuple[float, float, float, float]] = {**FOODS, **BRANDS}
    result = process.extractOne(
        key,
        combined.keys(),
        scorer=_fuzz.WRatio,
        score_cutoff=75,
    )
    if result:
        return combined[result[0]]

    return None


def calculate_nutrition(food_key: str, grams: float) -> dict:
    """Calculate nutrition for a given food and weight in grams.

    Returns dict with: item, grams, calories, protein_g, carbs_g, fats_g, from_db.
    If not found in DB, returns None (caller should use Gemini fallback values).
    """
    per100 = lookup(food_key)
    if per100 is None:
        return None

    cal, pro, carbs, fats = per100
    factor = grams / 100.0

    return {
        "item": food_key,
        "grams": grams,
        "calories": round(cal * factor, 1),
        "protein_g": round(pro * factor, 1),
        "carbs_g": round(carbs * factor, 1),
        "fats_g": round(fats * factor, 1),
        "from_db": True,
    }
