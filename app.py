import os
import random
from typing import Optional, Tuple
import requests
import streamlit as st
from streamlit_folium import st_folium
import folium
from folium.plugins import HeatMap
from datetime import datetime


DEFAULT_IMAGE_PATH = "default_farm_image.jpg"  


def safe_float(val):
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
        if "results" not in res or not res["results"]:
            return None
        return res["results"][0]["latitude"], res["results"][0]["longitude"]
    except Exception:
        return None

@st.cache_data(ttl=600)
def get_open_meteo(lat: float, lon: float) -> Optional[dict]:
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            "&hourly=temperature_2m,relativehumidity_2m&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,uv_index_max"
            "&current_weather=true&timezone=auto"
        )
        return requests.get(url, timeout=10).json()
    except Exception:
        return None

@st.cache_data(ttl=600)
def get_wttr(city_name: str) -> dict:
    try:
        url = f"https://wttr.in/{requests.utils.quote(city_name)}?format=j1"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, timeout=10, headers=headers).json()
        current = res.get('current_condition', [{}])[0]
        return {
            "temperature": safe_float(current.get('temp_C')),
            "windspeed": safe_float(current.get('windspeedKmph')),
            "humidity": safe_float(current.get('humidity')),
            "raw": res,
        }
    except Exception:
        return {"temperature": None, "windspeed": None, "humidity": None}


def get_current_month() -> int:
    return datetime.now().month

def is_crop_in_season(crop: str, current_month: int):
    crop = crop.lower()
    kharif_plant = range(6, 9)
    rabi_plant = range(10, 13)
    if "paddy" in crop or "rice" in crop:
        if current_month in kharif_plant:
            return True, "Kharif season — ideal for rice."
        return True, "Secondary Rabi rice possible with irrigation."
    if "wheat" in crop:
        if current_month in rabi_plant:
            return True, "Perfect Rabi season — go for wheat now."
        return False, "Not ideal time for wheat planting."
    if "cotton" in crop:
        if current_month in (4,5,6,7):
            return True, "Cotton planting window — good time."
        return False, "Not ideal for cotton sowing."
    if "tomato" in crop:
        if current_month in (1,2,3,9,10,11):
            return True, "Good period for tomato cultivation."
        return False, "High temperature/humidity risk for disease."
    if "sugarcane" in crop:
        if current_month in (1,2,3,10,11):
            return True, "Right season for sugarcane."
        return False, "Not ideal for sugarcane."
    return True, "Unknown crop — check local extension services."

def recommend_fertilizer(crop: str) -> str:
    crop = crop.lower()
    if "paddy" in crop or "rice" in crop:
        return "NPK 75:30:30 kg/ha — split top dressings required."
    if "wheat" in crop:
        return "NPK 100:40:20 kg/ha — ensure nitrogen at tillering."
    if "cotton" in crop:
        return "NPK + micronutrients — avoid excess nitrogen."
    if "tomato" in crop:
        return "NPK 100:60:100 + calcium spray for BER."
    if "sugarcane" in crop:
        return "Split nitrogen + potassium — trench method recommended."
    return "Follow soil test recommendations."

def pest_risk_advice(crop: str, temp_c, humidity):
    if temp_c is None:
        return "Not enough data for pest risk."
    crop = crop.lower()
    msg = []
    if "tomato" in crop and temp_c > 28 and (humidity or 0) > 75:
        msg.append("Blight risk — avoid overhead irrigation, use fungicide.")
    if "paddy" in crop and temp_c > 30:
        msg.append("Blast risk — monitor neck/leaf spots.")
    if "cotton" in crop and temp_c > 34:
        msg.append("Whitefly risk — monitor foliage daily.")
    return " ".join(msg) if msg else "Low pest risk now."


st.set_page_config(page_title="AeroSyn 🌿", layout="wide")
st.title("AeroSyn — Precision Agronomy")


if os.path.exists(DEFAULT_IMAGE_PATH):
    st.markdown(
        f"""
        <style>
        .stApp {{
            background: url("{DEFAULT_IMAGE_PATH}");
            background-size: cover;
            background-position: center;
            background-repeat: no-repeat;
        }}
        .css-18e3th9 {{
            backdrop-filter: blur(6px);
            background: rgba(255,255,255,0.25);
        }}
        h1 {{ color:#fff; text-shadow:0 0 12px black; }}
        </style>
        """, unsafe_allow_html=True
    )

# Sidebar
st.sidebar.header("Controls")
city = st.sidebar.text_input("Enter your city:", value="Madurai")
crops = ["Paddy (Rice)", "Wheat", "Cotton", "Tomato", "Sugarcane", "Other"]
selected_crop = st.sidebar.selectbox("Select your crop", crops)
show_forecast = st.sidebar.checkbox("Show 7-day forecast", value=True)

# Layout
col1, col2 = st.columns([2,1])
open_data = {}
weather_card = {}
temperatures = []
humidity_series = []

coords = get_coordinates(city)
if coords:
    lat, lon = coords
    open_data = get_open_meteo(lat, lon)
    if open_data and "current_weather" in open_data:
        cw = open_data["current_weather"]
        weather_card["temperature"] = safe_float(cw.get("temperature"))
        weather_card["windspeed"] = safe_float(cw.get("windspeed"))
        temperatures = (open_data.get("hourly", {}).get("temperature_2m", []) or [])[-24:]
        humidity_series = (open_data.get("hourly", {}).get("relativehumidity_2m", []) or [])[-24:]
    else:
        wt = get_wttr(city)
        weather_card["temperature"] = wt.get("temperature")
        weather_card["windspeed"] = wt.get("windspeed")
        humidity_series = [wt.get("humidity")]


with col1:
    if coords:
        st.markdown("## 🗺 Location")
        st.write(f"📍 **{city}** — {lat:.4f}, {lon:.4f}")
        st.markdown("### 🔥 Temperature Heatmap (approx last 24h)")

        
        if "heat_points" not in st.session_state or st.session_state.get("last_city") != city:
            st.session_state.heat_points = []
            st.session_state.last_city = city
            temps = temperatures if temperatures else [weather_card.get("temperature",28)+random.uniform(-2,2) for _ in range(12)]
            for _ in range(50):
                t = random.choice(temps)
                if t is not None:
                    st.session_state.heat_points.append([
                        lat + random.uniform(-0.05,0.05),
                        lon + random.uniform(-0.05,0.05),
                        float(t)
                    ])

        if st.session_state.heat_points:
            m = folium.Map(location=[lat, lon], zoom_start=10)
            HeatMap(st.session_state.heat_points, radius=25, blur=15, min_opacity=0.6).add_to(m)
            st_folium(m, width=700, height=500, key="heatmap")
        else:
            st.info("Heatmap data unavailable.")
    else:
        st.error("Invalid city — try correcting spelling.")


with col2:
    st.markdown("## 📊 Current Conditions")
    col_t, col_w = st.columns(2)
    with col_t:
        st.metric("Temperature (°C)", weather_card.get("temperature","N/A"))
    with col_w:
        st.metric("Wind Speed (km/h)", weather_card.get("windspeed","N/A"))

    st.markdown("---")
    if show_forecast:
        st.markdown("### 📅 7-Day Forecast")
        if open_data and "daily" in open_data:
            daily = open_data["daily"]
            df = {
                "Date": daily.get("time", []),
                "Max Temp (°C)": daily.get("temperature_2m_max", []),
                "Min Temp (°C)": daily.get("temperature_2m_min", []),
                "Precipitation (mm)": daily.get("precipitation_sum", []),
                "UV Index": daily.get("uv_index_max", []),
            }
            st.dataframe(df, width='stretch')
        else:
            st.info("Forecast not available.")

    st.markdown("---")
    st.markdown("## 🌾 Agronomy")
    current_month = get_current_month()
    ok, msg = is_crop_in_season(selected_crop, current_month)
    if ok:
        st.success(f"🌱 {selected_crop} can be planted now.")
    else:
        st.warning(f"❌ Not ideal time for {selected_crop}.")
    st.caption(msg)

    temp = weather_card.get("temperature")
    wind = weather_card.get("windspeed")
    hum = humidity_series[0] if humidity_series else None

    if temp and wind and wind < 8 and 18 <= temp <= 35:
        st.success("🧴 Safe to spray pesticides now.")
    elif wind and wind >= 8:
        st.warning("⚠️ Wind too high — avoid spraying.")
    elif temp and (temp < 18 or temp > 35):
        st.warning("⚠️ Temperature not ideal for spraying.")
    else:
        st.info("Spray advice unavailable.")

    st.write("**Fertilizer:**", recommend_fertilizer(selected_crop))
    st.write("**Pest Risk:**", pest_risk_advice(selected_crop, temp, hum))
