"""Tests for the coordinator's update loop, run against stubbed Home Assistant modules."""

import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1]))

import ha_stubs  # noqa: E402

ha_stubs.install()

from custom_components.blind_pilot import const  # noqa: E402
from custom_components.blind_pilot.coordinator import BlindPilotCoordinator  # noqa: E402

Clock = ha_stubs.Clock

HUB = {
    const.CONF_WEATHER: "weather.home",
    const.CONF_BATTERY_SOC: "sensor.battery",
    const.CONF_START: "10:00:00",
    const.CONF_END: "23:00:00",
}
Q1 = {  # south-west door, raised without waiting for a hand
    const.CONF_NAME: "Q1",
    const.CONF_COVER: "cover.q1",
    const.CONF_AZIMUTH: 225,
    const.CONF_GLASS_HEIGHT: 2.7,
    const.CONF_OVERHANG: 2.0,
    const.CONF_MIN_POSITION: 15,
    const.CONF_DUSK_LOWER: True,
    const.CONF_WAIT_FOR_HAND: False,
    const.CONF_ROOM_TEMP: "sensor.q1_temp",
    const.CONF_DOOR: "binary_sensor.q1_door",
    const.CONF_PV: "sensor.pv2",
    const.CONF_PV_PEAK: 2950,
    const.CONF_PV_AZIMUTH: 250,
    const.CONF_PV_TILT: 20,
}
Q3 = {  # east window, see-through fabric, waits for a hand
    const.CONF_NAME: "Q3",
    const.CONF_COVER: "cover.q3",
    const.CONF_AZIMUTH: 90,
    const.CONF_GLASS_HEIGHT: 2.7,
    const.CONF_MIN_POSITION: 0,
    const.CONF_DUSK_LOWER: False,
    const.CONF_WAIT_FOR_HAND: True,
    const.CONF_ROOM_TEMP: "sensor.q3_temp",
}


def make_entry(options=None):
    subentries = {
        blind_id: SimpleNamespace(
            subentry_id=blind_id, subentry_type=const.SUBENTRY_BLIND, title=data[const.CONF_NAME], data=data
        )
        for blind_id, data in (("q1", Q1), ("q3", Q3))
    }
    return SimpleNamespace(entry_id="hub", data=HUB, options=options or {}, subentries=subentries)


class CoordinatorTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        Clock.set_local(8, 0)
        self.hass = ha_stubs.FakeHass()
        self.states = self.hass.states
        self.states.set("weather.home", "sunny", {"cloud_coverage": 10})
        self.states.set("sensor.battery", 50)
        self.states.set("sensor.q1_temp", 24.5)
        self.states.set("sensor.q3_temp", 24.5)
        self.states.set("binary_sensor.q1_door", "off")
        self.cover("q1", 0)
        self.cover("q3", 0)
        self.sun(30, 120)
        self.coordinator = BlindPilotCoordinator(self.hass, make_entry())
        await self.coordinator.async_load()
        await self.coordinator.async_set_setting(const.SETTING_OBSERVE_ONLY, False)
        # Step past the start-up grace period and into the active hours.
        Clock.set_local(10, 5)

    def cover(self, name, position, state=None):
        if state is None:
            state = "closed" if position == 0 else "open"
        self.states.set(f"cover.{name}", state, {"current_position": position})

    def sun(self, elevation, azimuth):
        self.states.set("sun.sun", "above_horizon", {"elevation": elevation, "azimuth": azimuth})

    async def tick(self, **advance):
        if advance:
            Clock.advance(**advance)
        await self.coordinator.async_refresh()
        await asyncio.sleep(0)  # let the scheduled cover command run

    def moves(self):
        calls = [
            (data["entity_id"], data["position"])
            for domain, service, data in self.hass.services.calls
            if (domain, service) == ("cover", "set_cover_position")
        ]
        self.hass.services.calls.clear()
        return calls

    def status(self, blind_id):
        return self.coordinator.blinds[blind_id].snapshot.status

    async def settle(self, name, position):
        """Let a commanded move finish and the transit window pass."""
        self.cover(name, position)
        await self.tick(minutes=2)

    async def test_nothing_moves_before_the_active_hours(self):
        Clock.set_local(9, 30)
        await self.tick()
        self.assertEqual(self.moves(), [])
        self.assertEqual(self.status("q1"), "outside_hours")

    async def test_start_of_day_raises_only_the_blind_that_does_not_wait(self):
        await self.tick()
        self.assertEqual(self.moves(), [("cover.q1", 100)])
        self.assertEqual(self.status("q3"), "waiting_for_hand_open")

    async def test_own_move_is_not_mistaken_for_a_hand(self):
        await self.tick()
        self.cover("q1", 40, "opening")
        await self.tick(seconds=20)
        await self.settle("q1", 100)
        self.assertEqual(self.status("q1"), "active")
        self.assertIsNone(self.coordinator.blinds["q1"].state.hold_until)

    async def test_hand_raise_arms_then_pauses_then_hands_over(self):
        await self.tick()
        self.cover("q3", 100)
        await self.tick(minutes=1)
        self.assertEqual(self.status("q3"), "manual_hold")
        self.assertTrue(self.coordinator.blinds["q3"].state.armed)

        self.hass.services.forecast_high = 31.0
        self.sun(35, 100)
        await self.tick(minutes=30)
        self.moves()
        await self.tick(hours=1, minutes=45)
        await self.tick()
        self.assertEqual(self.status("q3"), "active")
        self.assertEqual(self.moves(), [("cover.q3", 0)])

    async def test_hand_close_keeps_the_blind_closed(self):
        await self.tick()
        await self.settle("q1", 100)
        self.moves()
        self.cover("q1", 0)
        await self.tick(minutes=1)
        self.assertEqual(self.status("q1"), "manual_hold")
        await self.tick(hours=3)
        await self.tick()
        self.assertEqual(self.status("q1"), "waiting_for_hand_open")
        self.assertEqual(self.moves(), [])

    async def test_observe_only_computes_but_does_not_move(self):
        await self.coordinator.async_set_setting(const.SETTING_OBSERVE_ONLY, True)
        await self.tick()
        await self.tick()
        self.assertEqual(self.moves(), [])
        self.assertEqual(self.status("q1"), "observing")
        self.assertEqual(self.coordinator.blinds["q1"].snapshot.target, 100)

    async def test_open_door_freezes_the_blind(self):
        self.states.set("binary_sensor.q1_door", "on")
        await self.tick()
        await self.tick()
        self.assertEqual(self.status("q1"), "door_open")
        self.assertEqual(self.moves(), [])

    async def test_automatic_switch_off_disables_one_blind(self):
        await self.coordinator.async_set_blind_flag("q1", const.BLIND_AUTOMATIC, False)
        await self.tick()
        self.assertEqual(self.status("q1"), "disabled")
        self.assertEqual(self.moves(), [])

    async def test_unavailable_cover_is_not_read_as_a_hand_move(self):
        await self.tick()
        await self.settle("q1", 100)
        self.states.set("cover.q1", "unavailable")
        await self.tick(minutes=1)
        self.assertEqual(self.status("q1"), "cover_unavailable")
        self.cover("q1", 60)
        await self.tick(minutes=1)
        self.assertIsNone(self.coordinator.blinds["q1"].state.hold_until)

    async def test_resume_ends_the_pause(self):
        await self.tick()
        self.cover("q3", 80)
        await self.tick(minutes=1)
        self.assertEqual(self.status("q3"), "manual_hold")
        await self.coordinator.async_resume("q3")
        self.assertEqual(self.status("q3"), "active")

    async def test_dusk_lowers_only_where_enabled(self):
        await self.tick()
        await self.settle("q1", 100)
        self.cover("q3", 100)
        await self.tick(minutes=1)
        self.moves()
        Clock.set_local(19, 30)
        self.sun(-2, 265)
        await self.tick()
        await self.tick()
        self.assertEqual(self.moves(), [("cover.q1", 0)])

    async def test_throttled_inverter_does_not_turn_a_sunny_day_cloudy(self):
        self.states.set("weather.home", "partlycloudy", {"cloud_coverage": 40})
        self.states.set("sensor.pv2", 2400)
        self.sun(35, 240)
        await self.tick()
        self.assertTrue(self.coordinator.blinds["q1"].snapshot.sunny)
        self.states.set("sensor.battery", 99)
        self.states.set("sensor.pv2", 400)
        await self.tick(minutes=30)
        snapshot = self.coordinator.blinds["q1"].snapshot
        self.assertTrue(snapshot.sunny)
        self.assertEqual(snapshot.sunny_source, "pv_throttled")

    async def test_state_survives_a_restart(self):
        await self.tick()
        self.cover("q3", 100)
        await self.tick(minutes=1)
        restarted = BlindPilotCoordinator(self.hass, make_entry())
        restarted._store.data = self.coordinator._store.data
        await restarted.async_load()
        self.assertFalse(restarted.settings[const.SETTING_OBSERVE_ONLY])
        self.assertTrue(restarted.blinds["q3"].state.armed)
        self.assertIsNotNone(restarted.blinds["q3"].state.hold_until)

    async def test_saved_options_replace_the_original_hub_inputs(self):
        options = {**HUB, const.CONF_START: "12:00:00"}
        coordinator = BlindPilotCoordinator(self.hass, make_entry(options))
        await coordinator.async_load()
        await coordinator.async_refresh()
        self.assertEqual(coordinator.blinds["q1"].snapshot.status, "outside_hours")


if __name__ == "__main__":
    unittest.main()
