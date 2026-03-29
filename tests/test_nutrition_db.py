"""Tests for nutrition_db.py — local food database and calculations."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nutrition_db


# ============================================================================
# Database lookup
# ============================================================================

class TestLookup:
    def test_exact_english(self):
        result = nutrition_db.lookup("chicken_breast")
        assert result is not None
        assert result[0] == 165  # calories per 100g

    def test_exact_hebrew(self):
        result = nutrition_db.lookup("חזה עוף")
        assert result is not None
        assert result[0] == 165

    def test_substring_match(self):
        result = nutrition_db.lookup("chicken")
        assert result is not None

    def test_not_found(self):
        result = nutrition_db.lookup("xyzzyfood")
        assert result is None

    def test_case_insensitive(self):
        result = nutrition_db.lookup("Salmon")
        assert result is not None
        assert result[0] == 208

    def test_rice(self):
        result = nutrition_db.lookup("אורז")
        assert result is not None

    def test_egg(self):
        result = nutrition_db.lookup("egg")
        assert result is not None
        assert result[1] == 13.0  # protein per 100g

    def test_olive_oil(self):
        result = nutrition_db.lookup("שמן זית")
        assert result is not None
        assert result[0] == 884  # highest calorie food

    def test_schnitzel(self):
        result = nutrition_db.lookup("שניצל")
        assert result is not None

    def test_falafel(self):
        result = nutrition_db.lookup("פלאפל")
        assert result is not None


# ============================================================================
# Nutrition calculation
# ============================================================================

class TestCalculateNutrition:
    def test_chicken_200g(self):
        result = nutrition_db.calculate_nutrition("chicken_breast", 200)
        assert result is not None
        assert result["from_db"] is True
        assert result["calories"] == 330.0   # 165 * 2
        assert result["protein_g"] == 62.0   # 31 * 2
        assert result["grams"] == 200

    def test_rice_150g(self):
        result = nutrition_db.calculate_nutrition("אורז", 150)
        assert result is not None
        assert result["calories"] == 195.0   # 130 * 1.5

    def test_unknown_food_returns_none(self):
        result = nutrition_db.calculate_nutrition("xyzzyfood", 200)
        assert result is None

    def test_zero_grams(self):
        result = nutrition_db.calculate_nutrition("chicken_breast", 0)
        assert result is not None
        assert result["calories"] == 0.0

    def test_small_portion(self):
        result = nutrition_db.calculate_nutrition("egg", 55)  # one egg
        assert result is not None
        assert result["calories"] == 85.2  # 155 * 0.55
        assert result["protein_g"] == 7.2  # 13 * 0.55

    def test_hebrew_food_calculation(self):
        result = nutrition_db.calculate_nutrition("סלמון", 150)
        assert result is not None
        assert result["calories"] == 312.0  # 208 * 1.5
        assert result["protein_g"] == 30.0  # 20 * 1.5


# ============================================================================
# Data integrity — ensure per-100g values are reasonable
# ============================================================================

class TestDataIntegrity:
    def test_all_calories_positive(self):
        for key, (cal, pro, carbs, fats) in nutrition_db.FOODS.items():
            assert cal >= 0, f"{key} has negative calories"

    def test_all_macros_non_negative(self):
        for key, (cal, pro, carbs, fats) in nutrition_db.FOODS.items():
            assert pro >= 0, f"{key} has negative protein"
            assert carbs >= 0, f"{key} has negative carbs"
            assert fats >= 0, f"{key} has negative fats"

    def test_macros_dont_exceed_calories(self):
        """Macro-derived calories shouldn't wildly exceed stated calories."""
        for key, (cal, pro, carbs, fats) in nutrition_db.FOODS.items():
            macro_cal = pro * 4 + carbs * 4 + fats * 9
            # Allow 30% tolerance for rounding and fiber
            assert macro_cal <= cal * 1.3 + 10, (
                f"{key}: macro calories {macro_cal:.0f} >> stated {cal}"
            )

    def test_hebrew_english_pairs_match(self):
        """Spot check that Hebrew/English pairs have same values."""
        pairs = [
            ("chicken_breast", "חזה עוף"),
            ("salmon", "סלמון"),
            ("egg", "ביצה"),
            ("rice_white", "אורז לבן"),
            ("banana", "בננה"),
        ]
        for eng, heb in pairs:
            assert nutrition_db.FOODS[eng] == nutrition_db.FOODS[heb], (
                f"Mismatch: {eng} vs {heb}"
            )

    def test_database_has_minimum_entries(self):
        assert len(nutrition_db.FOODS) >= 100
