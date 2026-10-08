# Blind Pilot

A Home Assistant custom component that positions interior roller blinds from the
sun's position, the weather and the room temperature, while leaving people in
charge. Everything lives in this one integration: there are no helper entities,
template sensors or automations to keep in step.

## What it does

For each blind, once a minute:

| Situation | Blind |
|---|---|
| No direct sun on the glass, or cloudy | Open |
| Sun on the glass, cool day | Open, to let the heat in |
| Sun on the glass, hot day | Down to the blind's lowest shading position |
| Sun on the glass, mild day, cool outside right now | Open, to let the heat in |
| Sun on the glass, mild day, otherwise | Follows the room: open when cool, shade when warm. In between, the blind is lowered just enough to keep the sun patch near the window, or stays open if glare limiting is off for that blind |
| Sun has gone down | Lowered, where that is enabled for the blind |

A day is cool, mild or hot from the highest temperature forecast or measured that
day. "Cool outside right now" compares the outdoor temperature with the cool-day
threshold, with a 1 degree margin so it does not flip back and forth. "Sun on the
glass" comes from the sun's position, the direction the window faces and any fixed
overhang above it.

Room thresholds have a 0.5 degree margin: a blind that went into shade because the
room passed its limit stays there until the room is half a degree back under it.

## House rules

- **Active hours.** Blinds are only moved between the start and end time (10:00 to
  23:00 by default). Nothing happens at the end time.
- **Hand-open first.** A blind that is closed at the start of the active hours is
  left alone until someone raises it by hand. A blind that is already open is
  eligible straight away. This can be switched off per blind.
- **Manual moves win.** Any move made by hand, from a wall switch, a dashboard or
  another automation, pauses that blind for two hours.
- **Hand-closed stays closed.** A blind closed fully by hand is not raised again
  that day unless someone raises it.
- **Doors.** A blind with a door contact is not moved while the door is open.
- **Energy saver.** When on, blinds ignore the hand-open rule and the shading
  gap and act purely on heat.
- **Observe only.** On after installation: targets and reasons are calculated
  and shown, but no blind is moved.

## Knowing whether the sun is out

In order of preference:

1. An outdoor light sensor, if one is configured.
2. Solar panel power compared with a clear-sky estimate for the same string.
   If the inverter cannot export, a full battery makes panel power read low; while
   the battery is above the configured charge level a low reading is ignored.
3. The weather entity's condition and cloud cover.

A change has to last 5 minutes (sun appearing) or 15 minutes (sun going) before
it counts.

## Installation

1. In HACS, add this repository as a custom repository of type Integration.
2. Download Blind Pilot and restart Home Assistant.
3. Add the Blind Pilot integration and fill in the shared inputs.
4. On the integration page, use **Add blind** once per blind.
5. Watch the target and status sensors for a few days, then turn off the
   **Observe only** switch.

## Entities

Hub device:

- `switch` Observe only, Energy saver
- `sensor` Day type
- `number` Cool day below, Hot day above, Room wants sun below, Room wants shade above

Each blind device:

- `sensor` Target (with the reason as an attribute), Status
- `binary_sensor` Armed, Sun on glass
- `switch` Automatic control, Wait for hand-open
- `button` Resume (ends a manual pause)

## Development

The rules are in `custom_components/blind_pilot/engine.py`, which has no Home
Assistant imports. Run its tests with:

```bash
python -m unittest discover tests
```
