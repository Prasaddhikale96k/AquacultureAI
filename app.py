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
fish_file = Path("fish_track_quality_summary_corrected.csv")  # corrected ByteTrack tracking summary

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
    "review_tracking", "review_reasons", "fps_used"
]

if not set(required_water).issubset(water.columns):
    st.error("Water-quality CSV is missing required columns.")
    st.stop()

if not set(required_fish).issubset(fish.columns):
    st.error("Fish-prediction CSV is missing required columns.")
    st.stop()

alerts = int((water["status"] == "REVIEW REQUIRED").sum())
review_tracks = int(fish["review_tracking"].fillna(True).astype(bool).sum())
short_tracks = int(fish["review_reasons"].str.contains("short track").sum())
full_window = int((fish["observations"] >= 60).sum())

# Summary cards
c1, c2, c3, c4 = st.columns(4)
c1.metric("Water records", len(water))
c2.metric("Water records flagged", alerts)
c3.metric("Fish tracks", len(fish))
c4.metric("Tracks needing review", review_tracks)

st.info(
    "Historical dataset results. Water thresholds are provisional. "
    "Fish tab shows tracking quality only: no validated behavior classification or fish-health diagnosis."
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
    f2.metric("Short tracks (< 30 observations)", short_tracks)
    f3.metric("Tracks with >= 60 observations", full_window)

    st.bar_chart(fish["review_reasons"].value_counts())

    st.caption(
        "Track IDs may represent fragmented tracks rather than distinct fish. "
        f"Speeds are px/sec at the video's FPS ({fish['fps_used'].iloc[0]:g}); "
        "gaps longer than 3 frames are excluded from speed."
    )

    st.dataframe(
        fish.assign(speed_reliable=~fish["review_tracking"].astype(bool)),
        use_container_width=True, hide_index=True
    )
    st.caption("Individual track speeds are only reliable where speed_reliable is True (tracking not flagged for review).")

    # ---- School-level movement (identity-free; see school_movement_metrics.py)
    st.divider()
    st.subheader("School-level movement (recorded videos)")
    try:
        import school_movement_metrics as sm
        school_files = sorted(Path(".").glob("school_movement_*.csv"))
        if not school_files:
            st.info("No school-movement files. Run: python school_movement_metrics.py --video <video>")
        else:
            pick = st.selectbox("Video", school_files, format_func=lambda p: p.stem.replace("school_movement_", ""), key="school_video")
            sdf = pd.read_csv(pick)
            sm_sum = sm.summarize(sdf)
            if sm_sum["reliability_reasons"]:
                st.warning("Not reliable for this video: " + "; ".join(sm_sum["reliability_reasons"])
                           + ". Values are shown for transparency and must not be read as fish movement.")
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Mean detections / frame", f"{sm_sum['detections_mean']:.1f}")
            k2.metric("Mean mask area (frame fraction)", f"{sm_sum['mask_area_frac_mean']:.2f}")
            k3.metric("Mean |area change| / frame", f"{sm_sum['abs_delta_mask_area_frac_mean']:.3f}")
            k4.metric("Camera drift (frame diagonals)", f"{sm_sum['camera_path_frac']:.2f}")
            st.line_chart(sdf.set_index("time_sec")[["mask_area_frac", "motion_energy"]])
            st.caption(f"Time uses the video's FPS ({sm_sum['fps']:g}). Motion energy = mean intensity change inside detected "
                       "regions after removing global translation; it excludes frames with camera motion or no detections "
                       "and is not a fish speed.")
    except Exception as exc:
        st.error(f"School-movement section unavailable: {type(exc).__name__}: {exc}")

    # ---- Experimental movement classification (zebrafish-trained; see behavior_live.py)
    st.divider()
    st.subheader("🧪 Experimental movement classification")
    try:
        import behavior_live as bl

        @st.cache_resource
        def _load_behavior_model():
            return bl.load_model()

        st.warning(bl.WARNING)
        bundle, model_error = _load_behavior_model()
        track_file = Path("fish_movement_features_bytetrack_corrected.csv")
        if model_error:
            st.error(f"Classifier unavailable: {model_error}")
        elif not track_file.exists():
            st.info("No tracking observations found for the current video.")
        else:
            obs = pd.read_csv(track_file, usecols=["frame", "track_id", "center_x", "center_y"])
            track_ids = sorted(obs["track_id"].unique())
            chosen = st.selectbox("Track ID", track_ids, key="behavior_track")
            # Latest run of consecutive frames for this track only (a gap restarts the window)
            buf = bl.TrackWindowBuffer()
            for r in obs[obs["track_id"] == chosen].sort_values("frame").itertuples():
                buf.update(chosen, r.frame, r.center_x, r.center_y)
            res = bl.classify_centroid_window(bundle, buf.window_xy(chosen), n_obs=buf.n_obs(chosen))
            m1, m2, m3 = st.columns(3)
            m1.metric("Observations in current window", f"{res['n_obs']} / {bl.WINDOW}")
            m2.metric("Window restarts (tracking gaps)", buf.resets.get(int(chosen), 0))
            m3.metric("Predicted class", res["prediction"] or "— none —")
            if res["status"] == "ok":
                st.bar_chart(pd.Series(res["probabilities"]))
            elif res["status"] == "features_incompatible":
                st.info(
                    "No prediction: live ByteTrack provides one box centre per fish, but the model needs "
                    f"{len(bl.KEYPOINT_ONLY_FEATURES)} of its {len(bl.EXPECTED_FEATURES)} features from 8 pose keypoints. "
                    "Class probabilities are unavailable."
                )
            else:
                st.info(f"No prediction ({res['status']}): {res['message']}")
    except Exception as exc:  # never break the rest of the dashboard
        st.error(f"Experimental classifier section unavailable: {type(exc).__name__}: {exc}")

with data_tab:
    st.subheader("Download analysis results")

    st.download_button(
        "Download water-quality CSV",
        water.to_csv(index=False).encode("utf-8"),
        file_name="water_quality_analysis.csv",
        mime="text/csv"
    )

    st.download_button(
        "Download track quality summary CSV",
        fish.to_csv(index=False).encode("utf-8"),
        file_name="fish_track_quality_summary_corrected.csv",
        mime="text/csv"
    )

    st.write("Water-quality data")
    st.dataframe(water, use_container_width=True, hide_index=True)

st.caption("AquacultureAI • Current data comes from saved CSV files, not live sensors.")