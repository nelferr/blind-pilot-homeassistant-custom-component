"""Tests for the Blind Pilot decision logic. Run with: python -m unittest discover tests"""

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import unittest

# Loaded by path so the tests do not need Home Assistant installed.
_PATH = Path(__file__).parents[1] / "custom_components" / "blind_pilot" / "engine.py"
_SPEC = importlib.util.spec_from_file_location("blind_pilot_engine", _PATH)
engine = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = engine
_SPEC.loader.exec_module(engine)

NOW = datetime(2026, 10, 3, 14, 0, tzinfo=timezone.utc)
HOLD = timedelta(hours=2)
THRESHOLDS = engine.Thresholds()

# Q1 and Q2: south-west sliding doors, blackout fabric, 2 m overhang
SW_DOOR = engine.BlindGeometry(azimuth=225, glass_height=2.7, overhang=2.0)
# Q3: east window, see-through fabric, no overhang, no dusk lowering
EAST = engine.BlindGeometry(azimuth=90, glass_height=2.7, min_position=0, dusk_lower=False)


def decide(geometry, **kwargs):
    values = {
        "elevation": 40,
        "azimuth": geometry.azimuth,
        "sunny": True,
        "day": engine.DAY_MILD,
        "room_temp": 24.5,
    }
    values.update(kwargs)
    return engine.decide(geometry, THRESHOLDS, **values)


class SunOnGlassTest(unittest.TestCase):
    def test_sun_behind_the_wall(self):
        sun = engine.sun_on_glass(40, 90, SW_DOOR)
        self.assertFalse(sun.on_glass)
        self.assertEqual(sun.blocked_by, "side")

    def test_sun_below_the_horizon(self):
        sun = engine.sun_on_glass(1, 225, SW_DOOR)
        self.assertFalse(sun.on_glass)
        self.assertEqual(sun.blocked_by, "horizon")

    def test_high_summer_sun_is_stopped_by_the_overhang(self):
        # 21 June about 13:00: the sun is at 72 degrees and only just round the corner.
        sun = engine.sun_on_glass(72, 150, SW_DOOR)
        self.assertFalse(sun.on_glass)
        self.assertEqual(sun.blocked_by, "overhang")

    def test_low_winter_sun_gets_under_the_overhang(self):
        # 21 December about 13:30: 26 degrees, roughly square on to the glass.
        sun = engine.sun_on_glass(26, 205, SW_DOOR)
        self.assertTrue(sun.on_glass)
        self.assertAlmostEqual(sun.profile_angle, 27.4, delta=0.5)
        self.assertAlmostEqual(sun.sunlit_height, 1.66, delta=0.05)

    def test_no_overhang_leaves_the_whole_glass_sunlit(self):
        sun = engine.sun_on_glass(30, 90, EAST)
        self.assertTrue(sun.on_glass)
        self.assertAlmostEqual(sun.sunlit_height, 2.7)


class ThermalModeTest(unittest.TestCase):
    def test_day_type(self):
        self.assertEqual(engine.day_type(None, THRESHOLDS), engine.DAY_MILD)
        self.assertEqual(engine.day_type(15, THRESHOLDS), engine.DAY_COOL)
        self.assertEqual(engine.day_type(23, THRESHOLDS), engine.DAY_MILD)
        self.assertEqual(engine.day_type(31, THRESHOLDS), engine.DAY_HOT)

    def test_hot_day_always_shades(self):
        self.assertEqual(engine.thermal_mode(engine.DAY_HOT, 21, THRESHOLDS), engine.MODE_SHADE)

    def test_cool_day_wants_heat_until_the_room_overheats(self):
        self.assertEqual(engine.thermal_mode(engine.DAY_COOL, 24.5, THRESHOLDS), engine.MODE_HEAT)
        self.assertEqual(engine.thermal_mode(engine.DAY_COOL, None, THRESHOLDS), engine.MODE_HEAT)
        self.assertEqual(engine.thermal_mode(engine.DAY_COOL, 26, THRESHOLDS), engine.MODE_SHADE)

    def test_mild_day_follows_the_room(self):
        self.assertEqual(engine.thermal_mode(engine.DAY_MILD, 23, THRESHOLDS), engine.MODE_HEAT)
        self.assertEqual(engine.thermal_mode(engine.DAY_MILD, 24.5, THRESHOLDS), engine.MODE_GLARE)
        self.assertEqual(engine.thermal_mode(engine.DAY_MILD, 25.5, THRESHOLDS), engine.MODE_SHADE)
        self.assertEqual(engine.thermal_mode(engine.DAY_MILD, None, THRESHOLDS), engine.MODE_GLARE)

    def test_cool_outside_makes_a_mild_day_want_heat(self):
        mode = engine.thermal_mode(engine.DAY_MILD, 24.5, THRESHOLDS, cool_outside=True)
        self.assertEqual(mode, engine.MODE_HEAT)
        mode = engine.thermal_mode(engine.DAY_MILD, 26, THRESHOLDS, cool_outside=True)
        self.assertEqual(mode, engine.MODE_SHADE)

    def test_cool_outside_does_not_overrule_a_hot_day(self):
        mode = engine.thermal_mode(engine.DAY_HOT, 22, THRESHOLDS, cool_outside=True)
        self.assertEqual(mode, engine.MODE_SHADE)


class CoolOutsideTest(unittest.TestCase):
    def test_below_the_threshold_is_cool(self):
        self.assertTrue(engine.cool_outside_now(19.5, 20, False))

    def test_well_above_the_threshold_is_not(self):
        self.assertFalse(engine.cool_outside_now(21.5, 20, True))

    def test_inside_the_margin_keeps_the_previous_answer(self):
        self.assertTrue(engine.cool_outside_now(20.5, 20, True))
        self.assertFalse(engine.cool_outside_now(20.5, 20, False))

    def test_unknown_temperature_is_not_cool(self):
        self.assertFalse(engine.cool_outside_now(None, 20, True))


class DayHighTest(unittest.TestCase):
    def test_keeps_the_peak_as_the_forecast_shrinks(self):
        high = engine.DayHigh()
        self.assertEqual(high.update("2026-10-06", 22.5, 20.0), 22.5)
        self.assertEqual(high.update("2026-10-06", 21.0, 20.5), 22.5)

    def test_starts_again_each_day(self):
        high = engine.DayHigh("2026-10-06", 28.0)
        self.assertEqual(high.update("2026-10-07", 19.0, None), 19.0)

    def test_no_readings_gives_nothing(self):
        self.assertIsNone(engine.DayHigh().update("2026-10-06", None, None))


class DecideTest(unittest.TestCase):
    def test_unknown_sun_position_changes_nothing(self):
        self.assertIsNone(decide(EAST, elevation=None).target)

    def test_dusk_lowers_only_where_enabled(self):
        self.assertEqual(decide(SW_DOOR, elevation=-3).target, 0)
        self.assertIsNone(decide(EAST, elevation=-3).target)

    def test_last_light_counts_as_dusk_so_the_blind_does_not_bounce_open(self):
        self.assertEqual(decide(SW_DOOR, elevation=1.5, day=engine.DAY_HOT).target, 0)

    def test_no_sun_on_the_glass_opens(self):
        self.assertEqual(decide(EAST, azimuth=250).target, 100)

    def test_cloudy_opens_even_on_a_hot_day(self):
        self.assertEqual(decide(EAST, sunny=False, day=engine.DAY_HOT).target, 100)

    def test_unknown_sky_is_treated_as_sunny(self):
        self.assertEqual(decide(EAST, sunny=None, day=engine.DAY_HOT).target, 0)

    def test_cool_day_opens_fully_for_heat(self):
        decision = decide(SW_DOOR, elevation=26, azimuth=205, day=engine.DAY_COOL, room_temp=22)
        self.assertEqual(decision.target, 100)
        self.assertEqual(decision.mode, engine.MODE_HEAT)

    def test_hot_day_shades_down_to_the_gap(self):
        decision = decide(SW_DOOR, elevation=20, day=engine.DAY_HOT)
        self.assertEqual(decision.target, 15)
        self.assertEqual(decision.mode, engine.MODE_SHADE)

    def test_see_through_blind_goes_fully_down_on_a_hot_day(self):
        self.assertEqual(decide(EAST, elevation=30, day=engine.DAY_HOT).target, 0)

    def test_hot_day_leaves_the_blind_up_when_the_overhang_covers_all_but_the_gap(self):
        # Profile angle 50 degrees: only the bottom 0.32 m is sunlit, inside the 0.4 m gap.
        decision = decide(SW_DOOR, elevation=50, day=engine.DAY_HOT)
        self.assertEqual(decision.target, 100)

    def test_glare_position_limits_the_sun_patch(self):
        # 30 degrees square on: 1 m of reach allows 0.58 m of opening, 21 % of 2.7 m.
        self.assertEqual(decide(EAST, elevation=30).target, 20)

    def test_glare_position_respects_the_gap(self):
        geometry = engine.BlindGeometry(azimuth=225, glass_height=2.7)
        self.assertEqual(decide(geometry, elevation=5).target, 15)

    def test_glare_leaves_the_blind_up_when_the_overhang_keeps_the_patch_short(self):
        # Profile angle 50 degrees: 0.32 m of sunlit glass reaches 0.27 m into the room.
        self.assertEqual(decide(SW_DOOR, elevation=50).target, 100)

    def test_low_evening_sun_drives_glare_limiting_to_the_gap(self):
        # 6 October, 18:00: the behaviour that prompted the two tests below.
        self.assertEqual(decide(SW_DOOR, elevation=13, azimuth=252, room_temp=24.2).target, 15)

    def test_cool_outside_opens_instead_of_limiting_glare(self):
        decision = decide(SW_DOOR, elevation=13, azimuth=252, room_temp=24.2, cool_outside=True)
        self.assertEqual(decision.target, 100)
        self.assertEqual(decision.mode, engine.MODE_HEAT)

    def test_glare_limiting_can_be_switched_off(self):
        geometry = engine.BlindGeometry(azimuth=225, glass_height=2.7, overhang=2.0, limit_glare=False)
        self.assertEqual(decide(geometry, elevation=13, azimuth=252).target, 100)
        self.assertEqual(decide(geometry, elevation=13, azimuth=252, room_temp=25.5).target, 15)
        self.assertEqual(decide(geometry, elevation=13, azimuth=252, day=engine.DAY_HOT).target, 15)

    def test_energy_saver_ignores_the_gap(self):
        decision = decide(SW_DOOR, elevation=20, day=engine.DAY_HOT, energy_saver=True)
        self.assertEqual(decision.target, 0)

    def test_energy_saver_without_sun(self):
        self.assertEqual(decide(EAST, azimuth=250, day=engine.DAY_COOL, energy_saver=True).target, 0)
        self.assertEqual(decide(EAST, azimuth=250, day=engine.DAY_HOT, energy_saver=True).target, 0)
        self.assertIsNone(decide(EAST, azimuth=250, energy_saver=True).target)

    def test_energy_saver_lowers_at_night_everywhere(self):
        self.assertEqual(decide(EAST, elevation=-3, energy_saver=True).target, 0)


class ArmingTest(unittest.TestCase):
    def test_closed_blind_waits_for_a_hand(self):
        state = engine.BlindState()
        engine.refresh_arming(state, "2026-10-03", True, 0, wait_for_hand=True)
        self.assertFalse(state.armed)

    def test_blind_already_open_at_the_start_is_armed(self):
        state = engine.BlindState()
        engine.refresh_arming(state, "2026-10-03", True, 60, wait_for_hand=True)
        self.assertTrue(state.armed)

    def test_blind_that_does_not_wait_is_armed_even_when_closed(self):
        state = engine.BlindState()
        engine.refresh_arming(state, "2026-10-03", True, 0, wait_for_hand=False)
        self.assertTrue(state.armed)

    def test_rule_runs_once_a_day(self):
        state = engine.BlindState()
        engine.refresh_arming(state, "2026-10-03", True, 60, wait_for_hand=True)
        engine.apply_manual_move(state, 60, 0, NOW, HOLD)
        engine.refresh_arming(state, "2026-10-03", True, 0, wait_for_hand=False)
        self.assertFalse(state.armed)

    def test_arming_is_dropped_outside_the_hours(self):
        state = engine.BlindState(armed=True, armed_day="2026-10-03")
        engine.refresh_arming(state, "2026-10-03", False, 60, wait_for_hand=True)
        self.assertFalse(state.armed)
        engine.refresh_arming(state, "2026-10-04", True, 60, wait_for_hand=True)
        self.assertTrue(state.armed)

    def test_unknown_position_is_retried(self):
        state = engine.BlindState()
        engine.refresh_arming(state, "2026-10-03", True, None, wait_for_hand=True)
        self.assertIsNone(state.armed_day)


class ManualMoveTest(unittest.TestCase):
    def test_raising_by_hand_arms_and_holds(self):
        state = engine.BlindState()
        kind = engine.apply_manual_move(state, 0, 70, NOW, HOLD)
        self.assertEqual(kind, engine.MOVE_RAISED)
        self.assertTrue(state.armed)
        self.assertEqual(state.hold_until, NOW + HOLD)
        self.assertEqual(state.expected_position, 70)

    def test_closing_by_hand_disarms(self):
        state = engine.BlindState(armed=True)
        self.assertEqual(engine.apply_manual_move(state, 80, 0, NOW, HOLD), engine.MOVE_CLOSED)
        self.assertFalse(state.armed)

    def test_lowering_part_way_keeps_the_arming(self):
        state = engine.BlindState(armed=True)
        self.assertEqual(engine.apply_manual_move(state, 80, 40, NOW, HOLD), engine.MOVE_LOWERED)
        self.assertTrue(state.armed)


class ControlStatusTest(unittest.TestCase):
    def status(self, state=None, **kwargs):
        values = {
            "automatic": True,
            "in_window": True,
            "door_open": False,
            "state": state or engine.BlindState(armed=True),
            "now": NOW,
            "energy_saver": False,
        }
        values.update(kwargs)
        return engine.control_status(**values)

    def test_active(self):
        self.assertEqual(self.status(), engine.STATUS_ACTIVE)

    def test_order_of_reasons(self):
        self.assertEqual(self.status(automatic=False, in_window=False), engine.STATUS_DISABLED)
        self.assertEqual(self.status(in_window=False, door_open=True), engine.STATUS_OUTSIDE_HOURS)
        self.assertEqual(self.status(door_open=True), engine.STATUS_DOOR_OPEN)

    def test_hold_runs_out(self):
        state = engine.BlindState(armed=True, hold_until=NOW + timedelta(minutes=1))
        self.assertEqual(self.status(state), engine.STATUS_HOLD)
        self.assertEqual(self.status(state, now=NOW + timedelta(minutes=2)), engine.STATUS_ACTIVE)

    def test_unarmed_waits_unless_energy_saver(self):
        state = engine.BlindState()
        self.assertEqual(self.status(state), engine.STATUS_WAITING)
        self.assertEqual(self.status(state, energy_saver=True), engine.STATUS_ACTIVE)


class ShouldMoveTest(unittest.TestCase):
    INTERVAL = timedelta(minutes=10)

    def move(self, target, position, state=None):
        return engine.should_move(target, position, state or engine.BlindState(), NOW, 10, self.INTERVAL)

    def test_nothing_to_do(self):
        self.assertFalse(self.move(None, 50))
        self.assertFalse(self.move(50, None))
        self.assertFalse(self.move(50, 52))

    def test_small_changes_are_skipped_unless_they_finish_the_travel(self):
        self.assertFalse(self.move(55, 50))
        self.assertTrue(self.move(100, 94))
        self.assertTrue(self.move(0, 6))

    def test_large_change_moves(self):
        self.assertTrue(self.move(15, 100))

    def test_recent_move_blocks_another(self):
        state = engine.BlindState(last_move=NOW - timedelta(minutes=3))
        self.assertFalse(self.move(15, 100, state))
        state.last_move = NOW - timedelta(minutes=11)
        self.assertTrue(self.move(15, 100, state))


class SunnyTest(unittest.TestCase):
    PV = {"pv_peak": 2800, "pv_azimuth": 200, "pv_tilt": 25}

    def sunny(self, **kwargs):
        values = {"elevation": 45, "azimuth": 180}
        values.update(kwargs)
        return engine.assess_sunny(**values)

    def test_clear_sky_fraction_peaks_facing_the_sun(self):
        facing = engine.clear_sky_fraction(45, 200, 200, 25)
        away = engine.clear_sky_fraction(45, 20, 200, 25)
        self.assertGreater(facing, 0.8)
        self.assertLess(away, facing / 2)
        self.assertEqual(engine.clear_sky_fraction(-1, 200, 200, 25), 0.0)

    def test_lux_wins_when_present(self):
        self.assertEqual(self.sunny(lux=60000, pv_power=0, **self.PV), (True, engine.SOURCE_LUX))
        self.assertEqual(self.sunny(lux=5000), (False, engine.SOURCE_LUX))

    def test_lux_between_thresholds_keeps_the_previous_answer(self):
        self.assertEqual(self.sunny(lux=24000, previous=True), (True, engine.SOURCE_LUX))
        self.assertEqual(self.sunny(lux=24000, previous=False), (False, engine.SOURCE_LUX))

    def test_pv_high_and_low(self):
        self.assertEqual(self.sunny(pv_power=2300, **self.PV), (True, engine.SOURCE_PV))
        self.assertEqual(self.sunny(pv_power=300, **self.PV), (False, engine.SOURCE_PV))

    def test_throttled_pv_proves_nothing_when_low(self):
        result = self.sunny(pv_power=300, throttled=True, condition="partlycloudy", **self.PV)
        self.assertEqual(result, (None, engine.SOURCE_PV_THROTTLED))

    def test_throttled_pv_still_counts_when_high(self):
        result = self.sunny(pv_power=2300, throttled=True, **self.PV)
        self.assertEqual(result, (True, engine.SOURCE_PV))

    def test_bad_weather_overrules_throttled_pv(self):
        result = self.sunny(pv_power=300, throttled=True, condition="rainy", **self.PV)
        self.assertEqual(result, (False, engine.SOURCE_PV_THROTTLED))

    def test_low_sun_falls_back_to_weather(self):
        result = self.sunny(elevation=5, pv_power=50, condition="sunny", **self.PV)
        self.assertEqual(result, (True, engine.SOURCE_WEATHER))

    def test_weather_fallback(self):
        self.assertEqual(self.sunny(condition="cloudy"), (False, engine.SOURCE_WEATHER))
        self.assertEqual(self.sunny(condition="partlycloudy", cloud_coverage=40), (True, engine.SOURCE_WEATHER))
        self.assertEqual(self.sunny(condition="partlycloudy", cloud_coverage=95), (False, engine.SOURCE_WEATHER))
        self.assertEqual(self.sunny(), (None, engine.SOURCE_WEATHER))


class DebouncerTest(unittest.TestCase):
    def setUp(self):
        self.debouncer = engine.Debouncer(timedelta(minutes=5), timedelta(minutes=15))

    def test_first_reading_is_taken_at_once(self):
        self.assertTrue(self.debouncer.update(True, NOW))

    def test_no_evidence_keeps_the_last_value(self):
        self.debouncer.update(True, NOW)
        self.assertTrue(self.debouncer.update(None, NOW + timedelta(hours=1)))

    def test_cloud_must_last_before_it_counts(self):
        self.debouncer.update(True, NOW)
        self.assertTrue(self.debouncer.update(False, NOW + timedelta(minutes=1)))
        self.assertTrue(self.debouncer.update(False, NOW + timedelta(minutes=10)))
        self.assertFalse(self.debouncer.update(False, NOW + timedelta(minutes=17)))

    def test_passing_cloud_resets_the_wait(self):
        self.debouncer.update(True, NOW)
        self.debouncer.update(False, NOW + timedelta(minutes=1))
        self.debouncer.update(True, NOW + timedelta(minutes=5))
        self.assertTrue(self.debouncer.update(False, NOW + timedelta(minutes=17)))

    def test_sun_returns_faster_than_it_leaves(self):
        self.debouncer.update(False, NOW)
        self.debouncer.update(True, NOW + timedelta(minutes=1))
        self.assertTrue(self.debouncer.update(True, NOW + timedelta(minutes=7)))


if __name__ == "__main__":
    unittest.main()
