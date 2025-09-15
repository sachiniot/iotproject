from flask import Flask, request, jsonify
import requests
import time

app = Flask(__name__)

# ===================== ESP32 + WEATHER STORAGE ==========
THINGSBOARD_TOKEN = None
frequency = power_factor = voltage = current = power = energy = None
solar_voltage = solar_current = solar_power = battery_percentage = light_intensity = None
battery_voltage = inverter_load = prev_batterypercent = prev_time= None
temperature = cloudcover = windspeed = precipitation = irradiance = prev_irradiance = None
LAT = LON = IP = RoomEsp = None
battery_alert = solar_alert = overload_status = sunlight_alert = charging_alert = None
payload = {}


# ===================== ALERT GENERATION ===================
def generate_alerts():
    global battery_alert, solar_alert, sunlight_alert, charging_alert, prev_time
    global solar_power, voltage, current, inverter_load, overload_status, power
    global battery_percentage, light_intensity, prev_batterypercent, prev_irradiance

    # Reset alerts and calculate irradiance
    battery_alert = solar_alert = overload_status = sunlight_alert = charging_alert = None
    irradiance = light_intensity / 120 

    # Fixed timegap (seconds)
    timegap = time.time() - prev_time

    # ----- 1. Battery Overcharge / Low -----
    if battery_percentage is not None:
        if battery_percentage >= 100:
            battery_alert = "Battery fully charged (100%) - Overcharge risk!"
        elif battery_percentage < 15:
            battery_alert = "Battery critically low (<15%) - Discharge risk!"

    # ----- 2. Solar Panel Underperformance -----
    if solar_voltage is not None and irradiance is not None:
        solar_power_calc = (solar_power) / 1000

        if 900 <= irradiance <= 1200 and not (0.31 <= solar_power_calc <= 0.37):
            solar_alert = (
                "Sunlight strong but solar panel underperforming (900-1200 W/m²)"
            )
        elif 600 <= irradiance < 900 and not (0.22 <= solar_power_calc <= 0.30):
            solar_alert = (
                "Sunlight moderate but solar panel underperforming (600-900 W/m²)"
            )
        elif 350 <= irradiance < 600 and not (0.14 <= solar_power_calc <= 0.22):
            solar_alert = "Sunlight low but solar panel underperforming (350-600 W/m²)"
        elif 150 <= irradiance < 350 and not (0.05 <= solar_power_calc <= 0.14):
            solar_alert = (
                "Sunlight very low but solar panel underperforming (150-350 W/m²)"
            )
        elif irradiance < 150 and solar_power_calc > 0.05:
            solar_alert = "Unexpected power generated in very low sunlight (<150 W/m²)"

    # ----- 3. Inverter Overload -----
    if power is not None and inverter_load is not None:

        # Define thresholds dynamically
        warning_limit = inverter_load * 0.90  # 90% load pe warning
        overload_limit = inverter_load * 1.00  # 100% se upar overload

        if power > overload_limit:
            overload_status = f"Overload! ({power:.2f}W > {inverter_load}W)"
        elif power > warning_limit:
            overload_status = f"High Load Warning. ({power:.2f}W / {inverter_load}W)"
        else:
            overload_status = f"Load Normal ({power:.2f} W)"

    # ----- 4. Sudden Drop in Sunlight -----
    if irradiance is not None and prev_irradiance is not None and timegap:
        lightslope = (irradiance - prev_irradiance) / timegap
        thresholdslope = -0.1
        if lightslope < thresholdslope:
            sunlight_alert = "Sudden drop in sunlight detected!"

    # ----- 5. Solar Power Generated but Battery Not Charging -----
    if (
        solar_voltage
        and solar_current
        and battery_percentage is not None
        and prev_batterypercent is not None
        and timegap
    ):
        if solar_power > 0:
            battery_slope = (battery_percentage - prev_batterypercent) / timegap
            threshold_battery_slope = 0.05
            if battery_slope < threshold_battery_slope:
                charging_alert = "Solar generating power but battery not charging!"


# ===================== WEATHER DATA ===================


def safe_first(lst):
    """Safely return the first element of a list, or None if empty"""
    return lst[0] if lst and len(lst) > 0 else None


def fetch_weather():
    global temperature, cloudcover, windspeed, precipitation, light_intensity
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={LAT}&longitude={LON}&hourly=temperature_2m,cloudcover,windspeed_10m,precipitation"
        )
        response = requests.get(url, timeout=10)
        data = response.json()

        hourly = data.get("hourly", {})
        temperature = safe_first(hourly.get("temperature_2m", []))
        cloudcover = safe_first(hourly.get("cloudcover", []))
        windspeed = safe_first(hourly.get("windspeed_10m", []))
        precipitation = safe_first(hourly.get("precipitation", []))
    except Exception as e:
        print("Error fetching weather:", str(e))
        temperature = cloudcover = windspeed = precipitation = None


# ===================== ESP32 DATA =====================
@app.route("/esp32-data", methods=["POST"])
def receive_data():
    global payload, LAT, LON, THINGSBOARD_TOKEN, IP, inverter_load, prev_batterypercent
    global frequency, power_factor, voltage, current, power, energy, prev_irradiance
    global solar_voltage, solar_current, solar_power, battery_percentage, overload_status
    global light_intensity, battery_voltage, RoomEsp
    global battery_alert, solar_alert, sunlight_alert, charging_alert
    try:
        data = request.get_json()

        # Update globals
        inverter_load = data.get("InverterLoad")
        frequency = data.get("Frequency")
        power_factor = data.get("PowerFactor")
        voltage = data.get("Voltage")
        current = data.get("Current")
        power = data.get("Power")
        energy = data.get("Energy")
        solar_voltage = data.get("solarVoltage")
        solar_current = data.get("solarCurrent")
        solar_power = data.get("solarPower")
        battery_percentage = data.get("batteryPercentage")
        light_intensity = data.get("lightIntensity")
        battery_voltage = data.get("batteryVoltage")
        THINGSBOARD_TOKEN = data.get("THINGSBOARD_TOKEN")
        LAT = data.get("latitude")
        LON = data.get("longitude")
        IP = data.get("deviceIP")
        RoomEsp = data.get("RoomEsp")

        #update time
        prev_time = time.time()

        # Update weather
        fetch_weather()

        # Check alerts
        generate_alerts()

        # After alerts, update previous values
        prev_batterypercent = battery_percentage
        prev_irradiance = light_intensity / 120

        # Build payload once and store globally
        payload = {
            k: v
            for k, v in {
                "InverterLoad": inverter_load,
                "Frequency": frequency,
                "PowerFactor": power_factor,
                "Voltage": voltage,
                "Current": current,
                "Power": power,
                "Energy": energy,
                "SolarVoltage": solar_voltage,
                "SolarCurrent": solar_current,
                "SolarPower": solar_power,
                "BatteryPercentage": battery_percentage,
                "LightIntensity": light_intensity,
                "BatteryVoltage": battery_voltage,
                "Temperature": temperature,
                "CloudPercent": cloudcover,
                "WindSpeed": windspeed,
                "RainInMM": precipitation,
                "deviceIP": IP,
                "latitude": LAT,
                "longitude": LON,
                "RoomEsp": RoomEsp,
                "battery_alert": battery_alert,  # Battery fully charged (100%) - Overcharge risk! || Battery critically low (<15%) - Discharge risk!
                "solar_alert": solar_alert,  # Sunlight strong but solar panel underperforming (900-1200 W/m²) || Sunlight moderate but solar panel underperforming (600-900 W/m²) || Sunlight low but solar panel underperforming (350-600 W/m²) || Sunlight very low but solar panel underperforming (150-350 W/m²) || Unexpected power generated in very low sunlight (<150 W/m²)
                "sunlight_alert": sunlight_alert,  # Sudden drop in sunlight detected!
                "charging_alert": charging_alert,  # Solar generating power but battery not charging!
                "overload_status": overload_status,  # Invalid or missing load data || High Load Warning. (450W / 500W) || Load Normal (350.00 W) || Overload! (550W > 500W)
            }.items()
            if v is not None
        }

        # Send to ThingsBoard
        THINGSBOARD_URL = (
            f"http://demo.thingsboard.io/api/v1/{THINGSBOARD_TOKEN}/telemetry"
        )
        response = requests.post(THINGSBOARD_URL, json=payload, timeout=5)

        return (
            jsonify(
                {
                    "status": "success",
                    "message": "ESP32 data received",
                    "thingsboard_status": response.status_code,
                    "payload_sent": payload,
                }
            ),
            200,
        )

    except Exception as e:
        print("Error:", str(e))
        return jsonify({"status": "error", "message": str(e)}), 400


# ===================== HOME PAGE =====================
@app.route("/")
def home():
    global payload
    return jsonify(payload)  # always return latest stored payload


# ===================== MAIN APP =====================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
