import time
import requests
import random
import math
import json
from flask import Flask, jsonify
import paho.mqtt.client as mqtt

# ==============================================================================
# --- CONFIGURATION & GLOBAL VARIABLES ---
# ==============================================================================
SIMULATED_SPEED_KPH = 40
NUM_PRECALCULATED_ROUTES = 20
SIGNALS_DATA_FILE = "vadodara_signals.json"
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_ROUTE_TOPIC = "rapidroute/route/new"

app = Flask(__name__)

# --- NEW: Expanded list of 25 known signals ---
KNOWN_SIGNALS = {
    "Akota Stadium Crossroads": (22.3069, 73.1706),
    "Akota-Dandia Bazar Bridge Circle": (22.3182, 73.1852),
    "Amit Nagar Circle": (22.3323, 73.1951),
    "Bhayli Main Road Circle": (22.2690, 73.1430),
    "Bright Day School Circle": (22.2755, 73.1498),
    "Chakli Circle": (22.3138, 73.1687),
    "Genda Circle": (22.3245, 73.1823),
    "Gorwa Refinery Road Crossing": (22.3361, 73.1465),
    "Gotri Hospital Crossroads": (22.3100, 73.1610),
    "Gotri-Vasna T-junction": (22.2980, 73.1650),
    "Iscon Temple Circle": (22.3225, 73.1558),
    "Kalali Railway Crossing": (22.2858, 73.1812),
    "Manisha Chowkdi": (22.2933, 73.1755),
    "Nilamber Triumph Signal": (22.2882, 73.1493),
    "OP Road Circle": (22.3211, 73.1721),
    "Race Course Circle": (22.3115, 73.1795),
    "Sama-Savli Road Crossing": (22.3385, 73.1678),
    "Sun Pharma - Tandalja Road Junction": (22.2965, 73.1411),
    "Sussen Tarsali Ring Road Circle": (22.2701, 73.2045),
    "Trident Circle": (22.2995, 73.1895),
    "Urmi Crossroads": (22.3045, 73.1833),
    "Vasna-Bhayli Canal Road Circle": (22.2811, 73.1415),
    "Vasna Road - Tandalja Road Crossing": (22.2890, 73.1690),
    "Windmill Circle": (22.2952, 73.1345),
    "Yash Complex Crossroads": (22.2905, 73.1593)
}

SIGNALS = {}
SIGNAL_NAME_TO_ID = {}
SIGNAL_ID_TO_NAME = {}
PRECALCULATED_ROUTES = []
# --- State variables for the currently active route ---
route_points = []
route_signal_waypoints = []
current_point_index = 0
previous_location = None
current_start_name = ""
current_destination_name = ""
signals_passed_on_current_route = []

# --- MQTT Client for the Server ---
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "SimulationServer")

# ==============================================================================
# --- HELPER FUNCTIONS ---
# ==============================================================================

def load_signals_from_file(filename):
    """Loads signal data and creates the consistent, sorted ID mappings."""
    global SIGNALS, SIGNAL_NAME_TO_ID, SIGNAL_ID_TO_NAME
    # This function now primarily uses the KNOWN_SIGNALS list for consistency.
    # The file can still be used to add more unnamed signals if needed.
    print(f"--- Initializing signal data from pre-defined list ---", flush=True)
    SIGNALS = KNOWN_SIGNALS
    sorted_signal_names = sorted(SIGNALS.keys())
    SIGNAL_ID_TO_NAME = {i + 1: name for i, name in enumerate(sorted_signal_names)}
    SIGNAL_NAME_TO_ID = {name: i for i, name in SIGNAL_ID_TO_NAME.items()}
    print(f"--- Successfully loaded and indexed {len(SIGNALS)} signals. ---", flush=True)
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
    """Gets a route from the OSRM routing engine."""
    start_lon, start_lat = start_coord
    end_lon, end_lat = end_coord
    url = f"http://router.project-osrm.org/route/v1/driving/{start_lon},{start_lat};{end_lon},{end_lat}?overview=full&geometries=geojson"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        route_json = response.json()
        if route_json.get("code") == "Ok":
            return route_json["routes"][0]["geometry"]["coordinates"]
    except requests.exceptions.RequestException as e:
        print(f"  > Error fetching route from OSRM: {e}", flush=True)
    return None

def find_signals_on_path(route_points, start_name, end_name):
    """Finds the sequence of known signals along a route path."""
    waypoints = [name for name, (sig_lat, sig_lon) in SIGNALS.items() if any(haversine(lat, lon, sig_lat, sig_lon) < 0.05 for lat, lon in route_points)]
    start_lat, start_lon = SIGNALS[start_name]
    waypoints.sort(key=lambda name: haversine(start_lat, start_lon, SIGNALS[name][0], SIGNALS[name][1]))
    if start_name in waypoints: waypoints.remove(start_name)
    if end_name in waypoints: waypoints.remove(end_name)
    final_waypoints = [start_name] + waypoints + [end_name]
    return list(dict.fromkeys(final_waypoints))

def select_new_route():
    """Selects a new pre-calculated route at random."""
    global route_points, route_signal_waypoints, current_point_index, previous_location, current_start_name, current_destination_name, signals_passed_on_current_route
    if not PRECALCULATED_ROUTES: return False
    
    print("\n--- Selecting a new pre-calculated route ---", flush=True)
    selected_route = random.choice(PRECALCULATED_ROUTES)
    
    route_points, route_signal_waypoints = selected_route["points"], selected_route["waypoints"]
    current_start_name, current_destination_name = selected_route["start"], selected_route["end"]
    
    print(f"New route: '{current_start_name}' to '{current_destination_name}'")
    print(f"Signals on this route: {' -> '.join(route_signal_waypoints)}", flush=True)
    
    route_payload = json.dumps(route_points)
    mqtt_client.publish(MQTT_ROUTE_TOPIC, route_payload, qos=1)
    print(f"--- New route announced on topic '{MQTT_ROUTE_TOPIC}' ---", flush=True)
    
    current_point_index, previous_location = 0, None
    signals_passed_on_current_route = []
    return True

def get_next_simulated_location():
    """Gets the next coordinate point along the current route."""
    global current_point_index, previous_location
    if not route_points or current_point_index >= len(route_points):
        if not select_new_route(): return None, None 
    previous_location = route_points[current_point_index - 1] if current_point_index > 0 else route_points[0]
    current_location = route_points[current_point_index]
    current_point_index += 1
    return current_location, previous_location

def find_next_signal_on_route(current_lat, current_lon):
    """Finds the next signal from the waypoint list using a stable loop."""
    global signals_passed_on_current_route
    while True:
        next_signal_name = next((s for s in route_signal_waypoints if s not in signals_passed_on_current_route), None)
        if next_signal_name is None: return current_destination_name
        
        next_signal_lat, next_signal_lon = SIGNALS.get(next_signal_name, (0,0))
        if haversine(current_lat, current_lon, next_signal_lat, next_signal_lon) < 0.05:
            if next_signal_name not in signals_passed_on_current_route:
                print(f"--- Vehicle has arrived at {next_signal_name} ---", flush=True)
                signals_passed_on_current_route.append(next_signal_name)
        else:
            return next_signal_name

@app.route('/location')
def get_location():
    """The API endpoint for the ESP32. Sends a compressed string."""
    current_loc, prev_loc = get_next_simulated_location()
    if current_loc is None: return "error", 500
    
    next_signal_name = find_next_signal_on_route(current_loc[0], current_loc[1])
    if next_signal_name is None: return "error", 500
    
    start_id = SIGNAL_NAME_TO_ID.get(current_start_name, 0)
    dest_id = SIGNAL_NAME_TO_ID.get(current_destination_name, 0)
    next_signal_id = SIGNAL_NAME_TO_ID.get(next_signal_name, 0)
    
    payload = f"{current_loc[0]:.6f},{current_loc[1]:.6f},{prev_loc[0]:.6f},{prev_loc[1]:.6f},{start_id},{dest_id},{next_signal_id}"
    return payload

if __name__ == '__main__':
    if load_signals_from_file(SIGNALS_DATA_FILE): # We now primarily use the hardcoded list
        print(f"\n--- Pre-calculating {NUM_PRECALCULATED_ROUTES} routes... ---", flush=True)
        for i in range(NUM_PRECALCULATED_ROUTES):
            print(f"Calculating route {i+1}/{NUM_PRECALCULATED_ROUTES}...", flush=True)
            start_name, dest_name = random.sample(list(SIGNALS.keys()), 2)
            start_coord, dest_coord = SIGNALS[start_name], SIGNALS[dest_name]
            route_coords = get_osrm_route((start_coord[1], start_coord[0]), (dest_coord[1], dest_coord[0]))
            if route_coords:
                points = [(lat, lon) for lon, lat in route_coords]
                waypoints = find_signals_on_path(points, start_name, dest_name)
                PRECALCULATED_ROUTES.append({
                    "start": start_name, "end": dest_name,
                    "points": points, "waypoints": waypoints
                })
                print(f"  > Route calculated with {len(waypoints)} signals.", flush=True)
            else:
                print(f"  > Failed to calculate route {i+1}. It will be skipped.", flush=True)

        if not PRECALCULATED_ROUTES:
            print("\nFATAL ERROR: Could not pre-calculate any routes. Please check internet.", flush=True)
        else:
            print("\n--- Connecting server's MQTT client... ---", flush=True)
            mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            mqtt_client.loop_start()
            
            print(f"\n--- {len(PRECALCULATED_ROUTES)} routes ready. Starting Flask server. ---", flush=True)
            app.run(host='0.0.0.0', port=5000)

