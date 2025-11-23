import time
import requests
import random
import math
import json
from flask import Flask, jsonify, render_template_string, request
from flask_cors import CORS
import paho.mqtt.client as mqtt

#  GLOBAL VARIABLES 

SIMULATED_SPEED_KPH = 60
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_ROUTE_TOPIC = "rapidroute/route/new"
HTML_TEMPLATE_FILE = "control_panel.html"
WAYPOINT_PROXIMITY_KM = 0.1 

app = Flask(__name__)
CORS(app) # Enable Cross-Origin Resource Sharing for the frontend

#  Final, Accurate, Manually Verified Coordinates 
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
#  State variables for the active route 
route_points = []
route_signal_waypoints = []
current_point_index = 0
previous_location = None
current_start_name = ""
current_destination_name = ""
signals_passed_on_current_route = []

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "ControlPanelServer")

#  HELPER FUNCTIONS 

def setup_signal_data():
    """Initializes the signal data using the hardcoded list."""
    global SIGNALS, SIGNAL_NAME_TO_ID, SIGNAL_ID_TO_NAME
    print(f" Initializing signal data from list ", flush=True)
    SIGNALS = KNOWN_SIGNALS
    # Sort the signals alphabetically to create a consistent ID mapping
    sorted_signal_names = sorted(SIGNALS.keys())
    SIGNAL_ID_TO_NAME = {i + 1: name for i, name in enumerate(sorted_signal_names)}
    SIGNAL_NAME_TO_ID = {name: i for i, name in SIGNAL_ID_TO_NAME.items()}
    print(f" Successfully loaded and indexed {len(SIGNALS)} signals. ", flush=True)
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
    """
    Gets a route from OSRM to find the
    optimized route for a vehicle.
    OSRM expects (longitude, latitude).
    """
    start_lon, start_lat = start_coord
    end_lon, end_lat = end_coord
    
    coordinates = f"{start_lon},{start_lat};{end_lon},{end_lat}"
    url = f"http://router.project-osrm.org/route/v1/driving/{coordinates}?overview=full&geometries=geojson"
    
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
    waypoints = [name for name, (sig_lat, sig_lon) in SIGNALS.items() 
                 if any(haversine(lat, lon, sig_lat, sig_lon) < WAYPOINT_PROXIMITY_KM for lat, lon in route_points)]
    
    start_lat, start_lon = SIGNALS[start_name]
    waypoints.sort(key=lambda name: haversine(start_lat, start_lon, SIGNALS[name][0], SIGNALS[name][1]))
    
    # Clean up the list to ensure logical ordering
    if start_name in waypoints: waypoints.remove(start_name)
    if end_name in waypoints: waypoints.remove(end_name)
    final_waypoints = [start_name] + waypoints + [end_name]
    return list(dict.fromkeys(final_waypoints))

def get_next_simulated_location():
    """Gets the next point along the current route."""
    global current_point_index, previous_location
    if not route_points or current_point_index >= len(route_points):
        if route_points:
            print(" End of manual route reached. Waiting for new route from control panel. ", flush=True)
        if route_points:
            return route_points[-1], route_points[-2] if len(route_points) > 1 else route_points[-1]
        return None, None
        
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
                print(f" Vehicle has arrived at {next_signal_name} ", flush=True)
                signals_passed_on_current_route.append(next_signal_name)
        else:
            return next_signal_name

#  WEB SERVER LOGIC (API for ESP32 and Frontend) 

@app.route('/')
def index():
    """Serves the main HTML control panel."""
    try:
        with open(HTML_TEMPLATE_FILE, 'r', encoding='utf-8') as f:
            return render_template_string(f.read())
    except FileNotFoundError:
        return f"Error: {HTML_TEMPLATE_FILE} not found in the same directory.", 404

@app.route('/get-signals')
def get_signals():
    """Provides the signal list to the frontend."""
    return jsonify(SIGNAL_ID_TO_NAME)

@app.route('/start-manual-route', methods=['POST'])
def start_manual_route():
    """Receives route selection from the frontend and starts the simulation."""
    global route_points, route_signal_waypoints, current_point_index, previous_location, current_start_name, current_destination_name, signals_passed_on_current_route
    data = request.get_json()
    start_id = int(data['start'])
    end_id = int(data['end'])

    current_start_name = SIGNAL_ID_TO_NAME[start_id]
    current_destination_name = SIGNAL_ID_TO_NAME[end_id]
    
    print(f"\n Manual route requested: {current_start_name} -> {current_destination_name} ", flush=True)
    
    start_coord = SIGNALS[current_start_name]
    end_coord = SIGNALS[current_destination_name]
    
    full_route_coords = get_osrm_route(
        (start_coord[1], start_coord[0]),
        (end_coord[1], end_coord[0])
    )
    
    if full_route_coords:
        route_points = [(lat, lon) for lon, lat in full_route_coords]
        route_signal_waypoints = find_signals_on_path(route_points, current_start_name, current_destination_name)
        
        print("\n Custom Route Ready! ")
        print(f"Full Path: {' -> '.join(route_signal_waypoints)}")
        
        current_point_index, previous_location = 0, None
        signals_passed_on_current_route = []
        
        route_payload = json.dumps(route_points)
        mqtt_client.publish(MQTT_ROUTE_TOPIC, route_payload, qos=1)
        print(" Route announced to map via MQTT ", flush=True)
        return jsonify({"message": "Simulation started successfully!", "route": route_signal_waypoints})
    else:
        return jsonify({"message": "Error: Could not calculate route."}), 500

@app.route('/location')
def get_location():
    """The API endpoint for the ESP32 transmitter."""
    current_loc, prev_loc = get_next_simulated_location()
    if current_loc is None: return "error: no route selected", 500
    
    next_signal_name = find_next_signal_on_route(current_loc[0], current_loc[1])
    if next_signal_name is None: return "error: could not find next signal", 500
    
    start_id = SIGNAL_NAME_TO_ID.get(current_start_name, 0)
    dest_id = SIGNAL_NAME_TO_ID.get(current_destination_name, 0)
    next_signal_id = SIGNAL_NAME_TO_ID.get(next_signal_name, 0)
    
    payload = f"{current_loc[0]:.6f},{current_loc[1]:.6f},{prev_loc[0]:.6f},{prev_loc[1]:.6f},{start_id},{dest_id},{next_signal_id}"
    return payload

@app.route('/route')
def get_route_for_map():
    """Provides the full route coordinates for the web map."""
    return jsonify(route_points) if route_points else jsonify([])

#  MAIN EXECUTION BLOCK 

if __name__ == '__main__':
    if setup_signal_data():
        print("\n Connecting server's MQTT client... ", flush=True)
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
        
        print(f"\n Server is ready. ", flush=True)
        print(f"To start the simulation, open your browser to http://127.0.0.1:5000")
        app.run(host='0.0.0.0', port=5000)

