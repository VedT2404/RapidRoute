import asyncio
from flask import Flask, send_from_directory
from winsdk.windows.devices import geolocation as wdg

app = Flask(__name__)

def decimal_to_dms(decimal, is_lat):
    is_positive = decimal >= 0
    decimal = abs(decimal)
    degrees = int(decimal)
    minutes_float = (decimal - degrees) * 60
    minutes = int(minutes_float)
    seconds = (minutes_float - minutes) * 60
    
    if is_lat:
        direction = "N" if is_positive else "S"
    else:
        direction = "E" if is_positive else "W"
        
    return f"{degrees}°{minutes}'{seconds:.1f}\"{direction}"

async def get_high_accuracy_location():
    locator = wdg.Geolocator()
    try:
        print("Fetching new high-accuracy location...")
        pos = await locator.get_geoposition_async()
        coords = pos.coordinate.point.position
        lat = coords.latitude
        lon = coords.longitude
        return lat, lon
    except Exception as e:
        print(f"Error fetching location: {e}")
        return None, None

# This is the new route that serves your map file
@app.route('/')
def serve_map():
    print("Web browser connected, serving live_map.html")
    # This looks for the 'live_map.html' file in the same folder as the script
    return send_from_directory('.', 'live_map.html')

# This is the existing route for your ESP32
@app.route('/location')
def get_location_route():
    lat, lon = asyncio.run(get_high_accuracy_location())
    if lat is not None:
        lat_dms = decimal_to_dms(lat, True)
        lon_dms = decimal_to_dms(lon, False)
        dms_string = f"{lat_dms} {lon_dms}"
        print(f"Location found: {dms_string}")
        return dms_string
    return "Location not found"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

