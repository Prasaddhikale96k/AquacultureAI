# Roadmap — after v1

## Hardware (prices indicative, India)
| Item | Why | Cost |
|---|---|---|
| Optical DO sensor, RS485/Modbus, 0-20 mg/L, temp-compensated | Enables real DO alarms and dawn-crash validation; highest ROI | Rs 2,000-5,000 |
| Spare Android phone + charger + SIM with unlimited SMS | SMSGate/textbee gateway; zero SMS cost on prepaid | Rs 0-1,000 (spare) |
| Optional USB GSM dongle (SIM800/SIM900) | Gammu fallback when phone is unavailable | Rs 1,000-2,000 |
| Turbidity calibration kit (formazin or owner NTU reference) | Convert RAW ADC to NTU | Rs 500-1,500 |
| Submersible/air pump timer or DO relay (NOT controlled by v1) | Human-operated aeration; future fail-safe control only after DO validation | Rs 1,000-3,000 |

## P0 (blocking acceptance)
1. Confirm the owner phone is signed in/verified via OTP (recipient `***771` is registered), then press Test SMS until one real Hinglish SMS arrives. SMSGate device must remain online.
2. Restore the ThingSpeak uplink (last entry 2026-10-15); confirm `/api/sensors` stale < 20 min and rule R1/R2/R3 behave on fresh data.
3. Owner: 30 s live-camera observation (smooth interpolation, 4 s cadence) + dashboard screenshot.

## P0.1 (SMS retention)
1. Keep the SMSGate Android phone powered and online; monitor its last-seen time weekly.
2. Decide whether to keep `AQUA_ALERT_PHONES` as an owner fallback or rely only on OTP-verified numbers.

## P1 (data collection, 2-4 weeks)
1. Run the camera continuously; collect behaviour windows until baseline has >= 12 samples/hour for the main daylight hours.
2. Perform one tap-tank drill; record whether activity/spread/surface react, tune `SUSTAIN_WINDOWS`.
3. Keep a simple log of true alarms vs false alarms in the dashboard; use `false_alarm_ids` as the v2 label set.
4. Recalibrate turbidity RAW -> NTU per pond; update `AQUA_TURB_RISE_RAW`.

## P2 (model quality)
1. Fine-tune or replace the Florence prompt/detector to remove duplicates and context junk (geometry cannot reach <=15% junk without losing real fish).
2. Collect ~300-500 labelled frames from the owner's tank; re-measure F1 and count error.
3. Calibrate alert thresholds against observed events (temperature/behaviour), not literature defaults.
4. Add dissolved-oxygen sensor; then `scripts/predict_do_lstm.py` becomes usable after 30 days of history.

## P3 (product)
1. WhatsApp/SMS digest preferences per farmer; multi-pond support.
2. Camera calibration wizard (rotation/crop already exist; add guided horizon check).
3. Optional farm-level solar/energy estimation once DO data exists.
