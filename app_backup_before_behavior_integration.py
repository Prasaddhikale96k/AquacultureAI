import streamlit as st
import pandas as pd
from pathlib import Path

st.set_page_config(
    page_title="AquacultureAI",
    page_icon="🐟",
    layout="wide"
)

st.title("🐟 AquacultureAI")
st.caption("Fish movement monitoring and water-quality screening")

water_file = Path("water_quality_analysis.csv")
fish_file = Path("fish_behavior_predictions.csv")

if not water_file.exists() or not fish_file.exists():
    st.error("Required CSV files are missing. Run the analysis scripts first.")
    st.stop()

water = pd.read_csv(water_file)
fish = pd.read_csv(fish_file)

required_water = [
    "temperature_C", "pH", "DO_mgL", "turbidity_NTU",
    "water_quality_alerts", "status"
]
required_fish = [
    "track_id", "observations", "mean_speed_px_sec",
    "predicted_behavior", "review_tracking"
]

if not set(required_water).issubset(water.columns):
    st.error("Water-quality CSV is missing required columns.")
    st.stop()

if not set(required_fish).issubset(fish.columns):
    st.error("Fish-prediction CSV is missing required columns.")
    st.stop()

alerts = int((water["status"] == "REVIEW REQUIRED").sum())
review_tracks = int(fish["review_tracking"].fillna(True).astype(bool).sum())
insufficient = int(
    (fish["predicted_behavior"] == "insufficient_data").sum()
)

# Summary cards
c1, c2, c3, c4 = st.columns(4)
c1.metric("Water records", len(water))
c2.metric("Water records flagged", alerts)
c3.metric("Fish tracks", len(fish))
c4.metric("Tracks needing review", review_tracks)

st.info(
    "Historical dataset results. Water thresholds are provisional; "
    "behavior labels are not validated fish-health diagnoses."
)

water_tab, fish_tab, data_tab = st.tabs([
    "💧 Water Quality",
    "🐠 Fish Behavior",
    "📄 Data Tables"
])

with water_tab:
    st.subheader("Water-quality measurements")

    a, b = st.columns(2)
    with a:
        st.line_chart(water["temperature_C"], height=250)
        st.caption("Temperature (°C)")
        st.line_chart(water["DO_mgL"], height=250)
        st.caption("Dissolved oxygen (mg/L)")

    with b:
        st.line_chart(water["pH"], height=250)
        st.caption("pH")
        st.line_chart(water["turbidity_NTU"], height=250)
        st.caption("Turbidity (NTU)")

    st.subheader("Records requiring review")
    flagged = water[water["status"] == "REVIEW REQUIRED"]
    st.dataframe(
        flagged[[
            "clip_id", "tank_id", "temperature_C", "pH",
            "DO_mgL", "turbidity_NTU", "water_quality_alerts"
        ]],
        use_container_width=True,
        hide_index=True
    )

with fish_tab:
    st.subheader("Fish tracking summary")
    f1, f2, f3 = st.columns(3)
    f1.metric("Tracks needing review", review_tracks)
    f2.metric("Insufficient data", insufficient)
    f3.metric(
        "Provisional predictions",
        int((fish["predicted_behavior"] != "insufficient_data").sum())
    )

    st.bar_chart(fish["predicted_behavior"].value_counts())

    st.caption(
        "Track IDs may represent fragmented tracks rather than distinct fish. "
        "Predictions are provisional and must be visually validated."
    )

    st.dataframe(fish, use_container_width=True, hide_index=True)

with data_tab:
    st.subheader("Download analysis results")

    st.download_button(
        "Download water-quality CSV",
        water.to_csv(index=False).encode("utf-8"),
        file_name="water_quality_analysis.csv",
        mime="text/csv"
    )

    st.download_button(
        "Download fish predictions CSV",
        fish.to_csv(index=False).encode("utf-8"),
        file_name="fish_behavior_predictions.csv",
        mime="text/csv"
    )

    st.write("Water-quality data")
    st.dataframe(water, use_container_width=True, hide_index=True)

st.caption("AquacultureAI • Current data comes from saved CSV files, not live sensors.")