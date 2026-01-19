import time
import requests
import random
import math
import json
from flask import Flask, jsonify, render_template_string, request
from flask_cors import CORS
import paho.mqtt.client as mqtt

# ==============================================================================
# --- CONFIGURATION & GLOBAL VARIABLES ---
# ==============================================================================
SIMULATED_SPEED_KPH = 60
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_ROUTE_TOPIC = "rapidroute/route/new"
HTML_TEMPLATE_FILE = "control_panel.html"
WAYPOINT_PROXIMITY_KM = 0.1 

app = Flask(__name__)
CORS(app) # Enable Cross-Origin Resource Sharing

# --- Final, Hyper-Accurate, Manually Verified Coordinates ---
# This list matches the Receiver's internal database exactly.
KNOWN_SIGNALS = {
    "Chakli Circle": (22.308333, 73.165278),
    "Diwalipura Circle": (22.301806, 73.165500),
    "Elora T-Junction": (22.315333, 73.161444),
    "Genda Circle (Natubhai Circle)": (22.309944, 73.158667),
    "Gotri Circle": (22.315556, 73.138000),
    "Hari Nagar Char Rasta": (22.311278, 73.153167),
    "ISKCON Circle": (22.303361, 73.151833),
    "Manisha Circle": (22.296306, 73.164583),
    "Nilamber Circle": (22.302000, 73.138944),
    "Tandalja SP T-Junction (Natubhai Circle)": (22.280444, 73.153194)
}

SIGNALS = {}
SIGNAL_NAME_TO_ID = {}
SIGNAL_ID_TO_NAME = {}

# --- State variables for the active route ---
route_points = []
route_signal_waypoints = []
current_point_index = 0
previous_location = None
current_start_name = ""
current_destination_name = ""
signals_passed_on_current_route = []

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "ControlPanelServer")

# ==============================================================================
# --- HELPER FUNCTIONS ---
# ==============================================================================

def setup_signal_data():
    """Initializes the signal data and ID mappings (sorted alphabetically)."""
    global SIGNALS, SIGNAL_NAME_TO_ID, SIGNAL_ID_TO_NAME
    SIGNALS = KNOWN_SIGNALS
    sorted_signal_names = sorted(SIGNALS.keys())
    SIGNAL_ID_TO_NAME = {i + 1: name for i, name in enumerate(sorted_signal_names)}
    SIGNAL_NAME_TO_ID = {name: i for i, name in SIGNAL_ID_TO_NAME.items()}
    print(f"--- Loaded and indexed {len(SIGNALS)} signals. ---", flush=True)
    return True

def haversine(lat1, lon1, lat2, lon2):
    """Calculates distance between two coordinates in kilometers."""
    R = 6371.0
    lat1_rad, lon1_rad, lat2_rad, lon2_rad = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def get_osrm_route(start_coord, end_coord):
    """Fetches a fastest-driving route from OSRM."""
    start_lon, start_lat = start_coord
    end_lon, end_lat = end_coord
    coordinates = f"{start_lon},{start_lat};{end_lon},{end_lat}"
    url = f"http://router.project-osrm.org/route/v1/driving/{coordinates}?overview=full&geometries=geojson"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("code") == "Ok":
            return data["routes"][0]["geometry"]["coordinates"]
    except Exception as e:
        print(f"Route error: {e}")
    return None

def find_signals_on_path(points, start_name, end_name):
    """Finds signals along the route points within waypoint proximity."""
    path_signals = [name for name, (s_lat, s_lon) in SIGNALS.items() 
                    if any(haversine(p_lat, p_lon, s_lat, s_lon) < WAYPOINT_PROXIMITY_KM for p_lat, p_lon in points)]
    
    start_lat, start_lon = SIGNALS[start_name]
    path_signals.sort(key=lambda n: haversine(start_lat, start_lon, SIGNALS[n][0], SIGNALS[n][1]))
    
    if start_name in path_signals: path_signals.remove(start_name)
    if end_name in path_signals: path_signals.remove(end_name)
    
    return [start_name] + path_signals + [end_name]

def get_next_simulated_location():
    """Iterates through the route points for the simulation."""
    global current_point_index, previous_location
    if not route_points or current_point_index >= len(route_points):
        return None, None
    
    previous_location = route_points[current_point_index - 1] if current_point_index > 0 else route_points[0]
    current_location = route_points[current_point_index]
    current_point_index += 1
    return current_location, previous_location

def find_next_signal_on_route(curr_lat, curr_lon):
    """Identifies the next upcoming signal waypoint."""
    global signals_passed_on_current_route
    while True:
        next_sig = next((s for s in route_signal_waypoints if s not in signals_passed_on_current_route), None)
        if next_sig is None: return current_destination_name
        
        s_lat, s_lon = SIGNALS[next_sig]
        if haversine(curr_lat, curr_lon, s_lat, s_lon) < 0.05: # 50m arrival
            if next_sig not in signals_passed_on_current_route:
                print(f"Passed: {next_sig}")
                signals_passed_on_current_route.append(next_sig)
        else:
            return next_sig

# ==============================================================================
# --- ROUTES ---
# ==============================================================================

@app.route('/')
def index():
    try:
        with open(HTML_TEMPLATE_FILE, 'r', encoding='utf-8') as f:
            return render_template_string(f.read())
    except FileNotFoundError:
        return "control_panel.html not found.", 404

@app.route('/start-manual-route', methods=['POST'])
def start_route():
    global route_points, route_signal_waypoints, current_point_index, previous_location, current_start_name, current_destination_name, signals_passed_on_current_route
    data = request.get_json()
    start_id, end_id = int(data['start']), int(data['end'])
    
    current_start_name = SIGNAL_ID_TO_NAME[start_id]
    current_destination_name = SIGNAL_ID_TO_NAME[end_id]
    
    coords = get_osrm_route(
        (SIGNALS[current_start_name][1], SIGNALS[current_start_name][0]),
        (SIGNALS[current_destination_name][1], SIGNALS[current_destination_name][0])
    )
    
    if coords:
        route_points = [(lat, lon) for lon, lat in coords]
        route_signal_waypoints = find_signals_on_path(route_points, current_start_name, current_destination_name)
        current_point_index = 0
        signals_passed_on_current_route = []
        
        mqtt_client.publish(MQTT_ROUTE_TOPIC, json.dumps(route_points), qos=1)
        return jsonify({"message": "Started", "route": route_signal_waypoints})
    return jsonify({"message": "OSRM Error"}), 500

@app.route('/location')
def get_location():
    curr, prev = get_next_simulated_location()
    if curr is None: return "error: no route selected", 500
    
    nxt_name = find_next_signal_on_route(curr[0], curr[1])
    
    s_id = SIGNAL_NAME_TO_ID.get(current_start_name, 0)
    d_id = SIGNAL_NAME_TO_ID.get(current_destination_name, 0)
    n_id = SIGNAL_NAME_TO_ID.get(nxt_name, 0)
    
    return f"{curr[0]:.6f},{curr[1]:.6f},{prev[0]:.6f},{prev[1]:.6f},{s_id},{d_id},{n_id}"

@app.route('/route')
def get_route_data():
    return jsonify(route_points)

if __name__ == '__main__':
    setup_signal_data()
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqtt_client.loop_start()
    app.run(host='0.0.0.0', port=5000)