"""Tests for insights.py — all Python math formulas."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import insights


# ============================================================================
# BMR — Mifflin-St Jeor
# ============================================================================

class TestBMR:
    def test_male_bmr(self):
        # 80kg, 180cm, 30yo male → 10*80 + 6.25*180 - 5*30 + 5 = 1780
        result = insights.calculate_bmr(80, 180, 30, "male")
        assert result == 1780.0

    def test_female_bmr(self):
        # 60kg, 165cm, 25yo female → 10*60 + 6.25*165 - 5*25 - 161 = 1345.25
        result = insights.calculate_bmr(60, 165, 25, "female")
        assert result == 1345.2

    def test_female_hebrew_gender(self):
        result = insights.calculate_bmr(60, 165, 25, "נקבה")
        assert result == 1345.2

    def test_female_f_shorthand(self):
        result = insights.calculate_bmr(60, 165, 25, "f")
        assert result == 1345.2

    def test_bmr_different_weight(self):
        light = insights.calculate_bmr(50, 170, 30, "male")
        heavy = insights.calculate_bmr(100, 170, 30, "male")
        assert heavy > light

    def test_bmr_age_effect(self):
        young = insights.calculate_bmr(70, 175, 20, "male")
        old = insights.calculate_bmr(70, 175, 50, "male")
        assert young > old


# ============================================================================
# TDEE
# ============================================================================

class TestTDEE:
    def test_sedentary_tdee(self):
        # TDEE = BMR * 1.2 + exercise
        result = insights.calculate_tdee(1780, 0)
        assert result == 2136.0  # 1780 * 1.2

    def test_tdee_with_exercise(self):
        result = insights.calculate_tdee(1780, 300)
        assert result == 2436.0  # 1780 * 1.2 + 300

    def test_tdee_zero_bmr(self):
        result = insights.calculate_tdee(0, 0)
        assert result == 0.0


# ============================================================================
# BMI
# ============================================================================

class TestBMI:
    def test_normal_bmi(self):
        # 70kg, 175cm → 70 / 1.75^2 = 22.9
        result = insights.calculate_bmi(70, 175)
        assert result == 22.9

    def test_overweight_bmi(self):
        result = insights.calculate_bmi(90, 175)
        assert result == 29.4

    def test_underweight_bmi(self):
        result = insights.calculate_bmi(45, 170)
        assert result == 15.6

    def test_obese_bmi(self):
        result = insights.calculate_bmi(120, 175)
        assert result == 39.2

    def test_zero_height(self):
        result = insights.calculate_bmi(70, 0)
        assert result == 0.0

    def test_bmi_category_underweight(self):
        assert insights.bmi_category(17.0) == "תת-משקל"

    def test_bmi_category_normal(self):
        assert insights.bmi_category(22.0) == "תקין"

    def test_bmi_category_overweight(self):
        assert insights.bmi_category(27.0) == "עודף משקל"

    def test_bmi_category_obese(self):
        assert insights.bmi_category(32.0) == "השמנה"


# ============================================================================
# Exercise calorie burn
# ============================================================================

class TestExerciseCalories:
    def test_functional(self):
        # 0.9 * 45 * 7 = 283.5
        result = insights.calculate_exercise_kcal("functional", 45, 7)
        assert result == 283.5

    def test_strength(self):
        # 0.8 * 60 * 8 = 384.0
        result = insights.calculate_exercise_kcal("strength", 60, 8)
        assert result == 384.0

    def test_cardio(self):
        # 1.1 * 30 * 6 = 198.0
        result = insights.calculate_exercise_kcal("cardio", 30, 6)
        assert result == 198.0

    def test_unknown_type_uses_default(self):
        # default rate 0.85 * 30 * 5 = 127.5
        result = insights.calculate_exercise_kcal("yoga", 30, 5)
        assert result == 127.5

    def test_zero_duration(self):
        result = insights.calculate_exercise_kcal("cardio", 0, 10)
        assert result == 0.0

    def test_intensity_scaling(self):
        low = insights.calculate_exercise_kcal("cardio", 30, 3)
        high = insights.calculate_exercise_kcal("cardio", 30, 9)
        assert high == low * 3  # 9/3 = 3x


# ============================================================================
# Hydration targets
# ============================================================================

class TestHydration:
    def test_base_hydration(self):
        result = insights.calculate_hydration_target()
        assert result == 2.5

    def test_hydration_with_exercise(self):
        exercises = [{"duration_min": 60, "intensity": 5}]
        result = insights.calculate_hydration_target(exercise_entries=exercises)
        # base 2.5 + (3.0 * 60 * 1.0) / 1000 = 2.5 + 0.18 = 2.68
        assert result == 2.68

    def test_hydration_high_intensity(self):
        exercises = [{"duration_min": 60, "intensity": 10}]
        result = insights.calculate_hydration_target(exercise_entries=exercises)
        # 2.5 + (3.0 * 60 * 2.0) / 1000 = 2.5 + 0.36 = 2.86
        assert result == 2.86

    def test_hydration_multiple_workouts(self):
        exercises = [
            {"duration_min": 30, "intensity": 5},
            {"duration_min": 30, "intensity": 5},
        ]
        result = insights.calculate_hydration_target(exercise_entries=exercises)
        single = insights.calculate_hydration_target(
            exercise_entries=[{"duration_min": 30, "intensity": 5}]
        )
        assert result > single

    def test_extra_water_for_workout(self):
        result = insights.calculate_extra_water_for_workout(60, 5)
        # 3.0 * 60 * (5/5) / 1000 = 0.18
        assert result == 0.18


# ============================================================================
# Macro targets
# ============================================================================

class TestMacros:
    def test_maintain_macros(self):
        result = insights.calculate_macro_targets(2000, "maintain")
        assert result["calories"] == 2000
        assert result["protein_g"] == 150   # 2000 * 0.30 / 4
        assert result["carbs_g"] == 200     # 2000 * 0.40 / 4
        assert result["fats_g"] == 67       # 2000 * 0.30 / 9

    def test_cut_macros(self):
        result = insights.calculate_macro_targets(2000, "cut")
        assert result["calories"] == 1700   # 2000 - 300
        assert result["protein_g"] == 149   # 1700 * 0.35 / 4

    def test_bulk_macros(self):
        result = insights.calculate_macro_targets(2000, "bulk")
        assert result["calories"] == 2300   # 2000 + 300
        assert result["protein_g"] == 172   # int(2300 * 0.30 / 4)

    def test_protein_always_positive(self):
        result = insights.calculate_macro_targets(500, "cut")
        assert result["protein_g"] > 0
        assert result["carbs_g"] > 0
        assert result["fats_g"] > 0


# ============================================================================
# Protein bump
# ============================================================================

class TestProteinBump:
    def test_strength_bump(self):
        assert insights.protein_bump_grams("strength") == 10

    def test_functional_bump(self):
        assert insights.protein_bump_grams("functional") == 10

    def test_cardio_no_bump(self):
        assert insights.protein_bump_grams("cardio") == 0


# ============================================================================
# Blood work range checking
# ============================================================================

class TestBloodRanges:
    def test_all_normal(self):
        markers = {"glucose_mg_dl": 90, "hdl": 55, "ldl": 80}
        result = insights.check_blood_ranges(markers)
        assert result["all_normal"] is True
        assert len(result["flags"]) == 0
        assert len(result["ok"]) == 3

    def test_high_glucose(self):
        markers = {"glucose_mg_dl": 130}
        result = insights.check_blood_ranges(markers)
        assert result["all_normal"] is False
        assert len(result["flags"]) == 1
        assert "גבוה" in result["flags"][0]

    def test_low_iron(self):
        markers = {"iron": 40}
        result = insights.check_blood_ranges(markers)
        assert result["all_normal"] is False
        assert "נמוך" in result["flags"][0]

    def test_empty_markers(self):
        result = insights.check_blood_ranges({})
        assert result["all_normal"] is True

    def test_none_values_skipped(self):
        markers = {"glucose_mg_dl": None, "hdl": 55}
        result = insights.check_blood_ranges(markers)
        assert len(result["ok"]) == 1

    def test_mixed_results(self):
        markers = {"glucose_mg_dl": 90, "ldl": 150, "vitamin_d": 15}
        result = insights.check_blood_ranges(markers)
        assert result["all_normal"] is False
        assert len(result["flags"]) == 2  # ldl high, vitamin_d low
        assert len(result["ok"]) == 1     # glucose ok


# ============================================================================
# Cycle adjustments
# ============================================================================

class TestCycleAdjustments:
    def test_luteal_adjustments(self):
        adj = insights.get_cycle_adjustments("luteal")
        assert adj["calorie_adjustment"] == 200
        assert adj["water_adjustment_l"] == 0.3
        assert "בינונית" in adj["recommended_intensity"]

    def test_menstrual_iron_note(self):
        adj = insights.get_cycle_adjustments("menstrual")
        assert "ברזל" in adj["iron_note"]

    def test_follicular_energy(self):
        adj = insights.get_cycle_adjustments("follicular")
        assert adj["calorie_adjustment"] == 0
        assert "גבוהה" in adj["recommended_intensity"]

    def test_ovulation_peak(self):
        adj = insights.get_cycle_adjustments("ovulation")
        assert adj["calorie_adjustment"] == 100

    def test_unknown_phase(self):
        adj = insights.get_cycle_adjustments("unknown")
        assert adj["calorie_adjustment"] == 0


# ============================================================================
# Wearable insights
# ============================================================================

class TestWearableInsights:
    def test_good_sleep(self):
        result = insights.calculate_wearable_insights(8, "good", 10000)
        assert result["sleep_deficit"] == 0.0
        assert "גבוהה" in result["recommended_intensity"]

    def test_poor_sleep(self):
        result = insights.calculate_wearable_insights(4.5, "poor", 3000)
        assert result["sleep_deficit"] == 3.0
        assert "נמוכה" in result["recommended_intensity"]
        assert result["calorie_adjustment"] >= 150  # poor sleep + low steps

    def test_high_steps_bonus(self):
        low_steps = insights.calculate_wearable_insights(7.5, "good", 5000)
        high_steps = insights.calculate_wearable_insights(7.5, "good", 13000)
        assert high_steps["calorie_adjustment"] > low_steps["calorie_adjustment"]

    def test_moderate_sleep(self):
        result = insights.calculate_wearable_insights(6.5, "fair", 8000)
        assert result["sleep_deficit"] == 1.0
        assert "בינונית" in result["recommended_intensity"]
