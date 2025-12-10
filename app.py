import os
import random
import time
from typing import Optional, Tuple, Dict, List
import requests
import streamlit as st
import folium
from folium.plugins import HeatMap
from datetime import datetime
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as colors
import io
import pandas as pd
import streamlit.components.v1 as components
from PIL import Image
import base64

# --------------------------
# Page config
# --------------------------
st.set_page_config(page_title="AeroSyn", layout="wide")

# ---------------------------------------------------
# (Splash screen removed as per user request)
# ---------------------------------------------------
if "splash_shown" not in st.session_state:
    st.session_state.splash_shown = False

if not st.session_state.splash_shown:
    st.markdown(
        """
        <style>
        .splash-container {
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            background: black;
            margin: 0;
        }
        .splash-logo {
            width: 320px;
            animation: fadeIn 1.0s ease-in-out;
        }
        @keyframes fadeIn {
            from {opacity: 0; transform: scale(0.95);} 
            to {opacity: 1; transform: scale(1);} 
        }
        </style>

        <div class="splash-container">
            <img src="logo.png" class="splash-logo">
        </div>
        """,
        unsafe_allow_html=True,
    )

    # short pause then rerun
    time.sleep(1.6)
    st.session_state.splash_shown = True
    st.rerun()

# ---------------------------------------------------
#             BACKGROUND IMAGE SETTINGS
# ---------------------------------------------------
DEFAULT_IMAGE_PATH = "default_farm_image.jpg"


def get_base64_image(image_path: str) -> Tuple[Optional[str], Optional[str]]:
    """Encodes a local image to base64 and returns (base64string, mime_type)"""
    try:
        mime_type = "image/jpeg" if image_path.lower().endswith((".jpg", ".jpeg")) else "image/png"
        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()
            return encoded, mime_type
    except Exception:
        return None, None


if os.path.exists(DEFAULT_IMAGE_PATH):
    base64_img, mime_type = get_base64_image(DEFAULT_IMAGE_PATH)
    if base64_img:
        st.markdown(
            f"""
            <style>
            .stApp {{
                background: url("data:{mime_type};base64,{base64_img}");
                background-size: cover;
                background-position: center;
                background-repeat: no-repeat;
                background-attachment: fixed;

                /* rendering hints */
                image-rendering: -webkit-optimize-contrast;
                image-rendering: crisp-edges;
                image-rendering: high-quality;
            }}

            .main {{
                background: rgba(255,255,255,0.16);
                padding: 12px;
                border-radius: 10px;
            }}

            h1, h2, h3 {{ color: #fff; text-shadow: 0 0 10px rgba(0,0,0,0.8); }}
            </style>
            """,
            unsafe_allow_html=True,
        )


# ---------------------------------------------------
#        UTILITY FUNCTIONS
# ---------------------------------------------------

def safe_float(val) -> Optional[float]:
    try:
        if val is None or val == "" or str(val).lower() == "nan":
            return None
        return float(val)
    except Exception:
        return None


@st.cache_data(ttl=900)
def get_coordinates(city_name: str) -> Optional[Tuple[float, float]]:
    try:
        url = f"https://geocoding-api.open-meteo.com/v1/search?name={requests.utils.quote(city_name)}"
        res = requests.get(url, timeout=10).json()
        if isinstance(res, dict) and res.get("results"):
            lat = float(res["results"][0]["latitude"])
            lon = float(res["results"][0]["longitude"])
            return lat, lon

        fallback = f"https://nominatim.openstreetmap.org/search?q={requests.utils.quote(city_name)}&format=json&limit=1"
        res = requests.get(fallback, headers={"User-Agent": "AeroSynApp"}, timeout=8).json()
        if res:
            return float(res[0]["lat"]), float(res[0]["lon"])
        return None
    except Exception:
        return None


@st.cache_data(ttl=600)
def get_open_meteo(lat: float, lon: float) -> Optional[dict]:
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}"
            "&hourly=temperature_2m,relative_humidity_2m"
            "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,uv_index_max,sunrise,sunset"
            "&current_weather=true&timezone=auto"
        )
        return requests.get(url, timeout=12).json()
    except Exception:
        return None


def get_current_month() -> int:
    return datetime.now().month


def is_crop_in_season(crop: str, current_month: int) -> Tuple[bool, str]:
    crop_l = (crop or "").lower()
    kharif = range(6, 10)  # Jun-Sep
    rabi = range(10, 4 + 13)  # Oct-Feb (wrap handled below)

    # simple logic
    if "paddy" in crop_l or "rice" in crop_l:
        return (current_month in kharif), "Kharif season — ideal for rice planting."
    if "wheat" in crop_l:
        # rabi months Oct-Feb
        if current_month in (10, 11, 12, 1, 2):
            return True, "Perfect Rabi season — go for wheat now."
        return False, "Not ideal time for wheat planting."
    return True, "Check local extension services for exact timing."


def recommend_fertilizer(crop: str) -> str:
    crop_l = (crop or "").lower()
    if "paddy" in crop_l or "rice" in crop_l:
        return "NPK 75:30:30 kg/ha — split top dressings recommended."
    if "wheat" in crop_l:
        return "NPK 100:40:20 kg/ha — ensure nitrogen at tillering."
    if "tomato" in crop_l:
        return "NPK 100:60:100 + calcium spray to prevent BER."
    return "Follow soil test recommendations."


def pest_risk_advice_advanced(crop: str, hourly_data: Dict[str, List]) -> str:
    if not hourly_data or not isinstance(hourly_data, dict):
        return "Not enough detailed hourly data for a reliable pest risk assessment."

    temps = hourly_data.get("temperature_2m", [])
    hums = hourly_data.get("relative_humidity_2m", [])
    if len(temps) < 1 or len(hums) < 1:
        return "Not enough detailed hourly data for a reliable pest risk assessment."

    # use last 24 values where available
    temp_24 = [t for t in temps[-24:] if t is not None]
    hum_24 = [h for h in hums[-24:] if h is not None]

    avg_temp = sum(temp_24) / len(temp_24) if temp_24 else None
    high_humidity_hours = sum(1 for h in hum_24 if h > 90) if hum_24 else 0

    msg = []
    crop_l = (crop or "").lower()

    if ("paddy" in crop_l or "rice" in crop_l) and avg_temp is not None:
        if avg_temp >= 24 and high_humidity_hours >= 8:
            msg.append(f"🍚 HIGH RISK: Sustained {high_humidity_hours}h of high humidity detected.")

    if "tomato" in crop_l and avg_temp is not None:
        if avg_temp < 28 and high_humidity_hours >= 10:
            msg.append(f"🍅 BLIGHT RISK: Mild temp and {high_humidity_hours}h high humidity — consider protective measures.")

    return " ".join(msg) if msg else "🟢 Low pest/disease risk based on recent weather conditions."


def calculate_vari_from_file(uploaded_file) -> Tuple[Optional[float], Optional[plt.Figure]]:
    try:
        img = Image.open(uploaded_file).convert("RGB")
        arr = np.array(img).astype(np.float32)
        if arr.ndim < 3 or arr.shape[2] < 3:
            return None, None

        R = arr[:, :, 0] / 255.0
        G = arr[:, :, 1] / 255.0
        B = arr[:, :, 2] / 255.0

        eps = 1e-6
        denom = (G + R - B) + eps
        vari = (G - R) / denom

        valid = vari[np.isfinite(vari)]
        valid = valid[(valid >= -1) & (valid <= 1)]
        avg_vari = float(np.mean(valid)) if valid.size else 0.0

        fig, ax = plt.subplots(figsize=(6, 6))
        cmap = colors.ListedColormap(["#d73027", "#fee08b", "#91cf60", "#1a9850"])
        bounds = [-1, -0.1, 0.1, 0.2, 1.0]
        norm = colors.BoundaryNorm(bounds, cmap.N)
        im = ax.imshow(vari, cmap=cmap, norm=norm)
        ax.set_title("Field Health Map (VARI)")
        ax.axis("off")
        fig.colorbar(im, ax=ax, orientation="horizontal", fraction=0.04, pad=0.04).set_label("VARI Value")

        return avg_vari, fig
    except Exception:
        return None, None


# ---------------------------------------------------
#                  MAIN APP UI
# ---------------------------------------------------

st.title("AeroSyn — Smart Farm Assistant")

with st.sidebar:
    st.header("Controls")
    city = st.text_input("Enter your city:", value="Usilampatti")
    crops = ["Paddy (Rice)", "Wheat", "Cotton", "Tomato", "Sugarcane", "Other"]
    selected_crop = st.selectbox("Select your crop", crops)
    show_forecast = st.checkbox("Show 7-day forecast", value=True)
    st.markdown("---")

coords = get_coordinates(city)
open_data = {}
weather_card = {}
temperatures = []
hourly_full_data = {}
lat = lon = None

if coords:
    lat, lon = coords
    open_data = get_open_meteo(lat, lon) or {}
    if open_data and "current_weather" in open_data:
        cw = open_data.get("current_weather", {})
        weather_card["temperature"] = safe_float(cw.get("temperature"))
        weather_card["windspeed"] = safe_float(cw.get("windspeed"))
        hourly_full_data = open_data.get("hourly", {})
        temperatures = (hourly_full_data.get("temperature_2m", []) or [])[-24:]
    else:
        st.warning("Could not fetch real-time weather data.")
else:
    st.info("Enter a valid city in the sidebar to fetch data.")


col1, col2, col3 = st.columns([2, 1.5, 2])

with col1:
    if coords:
        st.markdown("## 🗺 Location & Heatmap")
        st.write(f"📍 **{city}** — {lat:.4f}, {lon:.4f}")
        st.markdown("### 🔥 Temperature Heatmap (approx last 24h)")

        if "heat_points" not in st.session_state or st.session_state.get("last_city") != city:
            st.session_state.heat_points = []
            st.session_state.last_city = city
            temps = [float(t) for t in temperatures if t is not None]
            if not temps:
                current_temp = weather_card.get("temperature", 28)
                temps = [float(current_temp) + random.uniform(-2, 2) for _ in range(12)]

            for _ in range(50):
                t = random.choice(temps)
                st.session_state.heat_points.append([
                    float(lat) + random.uniform(-0.05, 0.05),
                    float(lon) + random.uniform(-0.05, 0.05),
                    float(t),
                ])

        if st.session_state.heat_points:
            m = folium.Map(location=[float(lat), float(lon)], zoom_start=10)
            HeatMap(st.session_state.heat_points, radius=25, blur=15, min_opacity=0.6).add_to(m)
            map_html = m._repr_html_()
            components.html(map_html, width=col1.width, height=500, scrolling=False)
        else:
            st.info("Heatmap data unavailable.")
    else:
        st.error("Invalid city — try correcting spelling.")

with col2:
    st.markdown("## 📊 Current Conditions & Guidance")
    col_t, col_w = st.columns(2)
    with col_t:
        st.metric("Temperature (°C)", weather_card.get("temperature", "N/A"))
    with col_w:
        st.metric("Wind Speed (km/h)", weather_card.get("windspeed", "N/A"))

    st.markdown("---")

    if show_forecast and open_data and "daily" in open_data:
        st.markdown("### 📅 7-Day Summary")
        daily = open_data.get("daily", {})
        df = pd.DataFrame({
            "Date": daily.get("time", [])[:7],
            "Max T (°C)": daily.get("temperature_2m_max", [])[:7],
            "Rain (mm)": daily.get("precipitation_sum", [])[:7],
        })
        st.dataframe(df, width="stretch")
    elif show_forecast:
        st.info("Forecast not available.")

    st.markdown("---")
    st.markdown("## 🌾 Traditional Agronomy")
    current_month = get_current_month()
    ok, msg = is_crop_in_season(selected_crop, current_month)
    if ok:
        st.success(f"🌱 {selected_crop} planting is recommended.")
    else:
        st.warning(f"❌ Not ideal time for {selected_crop}.")
    st.caption(msg)

    st.write("**Fertilizer:**", recommend_fertilizer(selected_crop))

    temp = weather_card.get("temperature")
    wind = weather_card.get("windspeed")
    if temp is not None and wind is not None and wind < 8 and 18 <= temp <= 35:
        st.success("🧴 Safe to spray pesticides now.")
    elif wind is not None and wind >= 8:
        st.warning("⚠️ Wind too high — avoid spraying.")
    else:
        st.info("Spray advice unavailable.")

with col3:
    st.markdown("## 🔬 Advanced Land Analysis")
    st.markdown("---")

    st.subheader("🦠 Predictive Pest & Disease Risk")
    pest_risk_result = pest_risk_advice_advanced(selected_crop, hourly_full_data)
    if "HIGH" in pest_risk_result or "BLIGHT" in pest_risk_result or "RISK" in pest_risk_result:
        st.error(pest_risk_result)
    else:
        st.success(pest_risk_result)

    st.markdown("---")
    st.subheader("🛰 Greenery Tracking (VARI)")

    uploaded_file = st.file_uploader(
        "Upload a **standard color image (PNG/JPEG)** of your field:", type=["png", "jpg", "jpeg"]
    )

    if uploaded_file is not None:
        with st.spinner("Processing image... Calculating VARI."):
            avg_vari, fig = calculate_vari_from_file(uploaded_file)
        if avg_vari is not None and fig is not None:
            st.markdown("#### Land Health Results")
            st.pyplot(fig)
            st.markdown(f"#### Average VARI: **{avg_vari:.3f}**")
            if avg_vari >= 0.20:
                st.success("✨ **EXCELLENT HEALTH!** High uniformity and dense vegetation.")
            elif 0.05 <= avg_vari < 0.20:
                st.warning("🟡 **MODERATE HEALTH:** Check the map for stressed (red/yellow) zones.")
            else:
                st.error("🚨 **POOR HEALTH/STRESS:** Very low average VARI.")
    else:
        st.info("Upload your color image to calculate the Visible Atmospherically Resistant Index (VARI).")

# Footer
st.markdown("---")
st.caption("Built with ❤️ — AeroSyn")
