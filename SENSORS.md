# Sensor catalog — AquacultureAI live pipeline (ESP32 → ThingSpeak → dashboard)

All live values are read-only from ThingSpeak. Nothing is invented in the
browser: unmapped fields show "Not Configured", empty fields show "No Data".

| Sensor | Hardware | ThingSpeak field | Raw value | Displayed unit | Conversion | Calibration status | Valid range | Freshness |
|---|---|---|---|---|---|---|---|---|
| Water temperature | DS18B20 (ESP32) | Field 1 (explicit, `VITE_THINGSPEAK_FIELD_TEMPERATURE`) | °C float from probe | °C | None (probe-native) | Factory probe accuracy; bus-error sentinels `-127` and `85` rejected, never shown | −10…50 °C plausible window (rule range 25–32 °C provisional) | Stale after `VITE_THINGSPEAK_STALE_MINUTES` (default 5 min) |
| Turbidity | Turbidity sensor (ESP32 ADC) | Field 2 (explicit, `VITE_THINGSPEAK_FIELD_TURBIDITY`) | Raw ADC count | **ADC (raw, uncalibrated)** | **None verified — do NOT read as NTU** | **UNCALIBRATED.** No formazin/NTU calibration curve exists. Deliberately has no alert threshold. | ADC 0–4095 (12-bit) | Same staleness rule |
| pH | None installed | Unmapped | — | pH | — | No sensor. Rule range 6.5–8.5 exists but stays **inactive** until a field is mapped and returns data. | — | — |
| Dissolved oxygen | None installed | Unmapped | — | mg/L | — | No sensor. Rule minimum 5 mg/L exists but stays **inactive** until mapped. | — | — |

## Turbidity calibration procedure (required before any NTU claim)

1. Prepare formazin (or certified) standards, e.g. 0 / 10 / 100 / 400 NTU.
2. Record the sensor's raw ADC value at each standard (same supply voltage, same ambient light, clean vial).
3. Fit ADC→NTU (usually linear or log-linear in the working range); record the formula, R² and date.
4. Enter the verified formula in code review (a new `calibrateTurbidity()` in
   `frontend/src/services/thingspeak.ts`) — never relabel the raw card as NTU.
5. Until then, the dashboard card reads "Raw Turbidity (ADC)" + "raw, uncalibrated — not NTU".

## Missing sensors

A missing sensor is reported (`not_configured` / `no_data` / stale warning),
never treated as normal and never back-filled. Manual water readings
(`POST /api/water-readings`) accept pH/DO in verified lab units and go through
the same rule engine with plausibility checks.
