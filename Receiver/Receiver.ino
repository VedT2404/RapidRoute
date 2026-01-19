/**
 * @file    Receiver.ino
 * @brief   Main receiver sketch. Subscribes to MQTT location data, parses 
 * compressed signal IDs, and calculates real-time alerts.
 */

#include <WiFi.h>
#include <PubSubClient.h>

// ==============================================================================
// --- CONFIGURATION ---
// ==============================================================================
const char* ssid = "VED_TUF";
const char* password = "lemaou3000";
const char* mqtt_server = "broker.hivemq.com";
const char* location_topic = "rapidroute/location/data";

const float ALERT_DISTANCE_METERS = 800.0;
const float ARRIVAL_DISTANCE_METERS = 50.0;

// ==============================================================================
// --- On-board Signal Database (The Receiver's "Brain") ---
// Sorted alphabetically to match the Python Server and Control Panel IDs.
// ==============================================================================
struct TrafficSignal {
    int id;
    const char* name;
    double lat;
    double lon;
};

TrafficSignal signals[] = {
    {1, "Chakli Circle", 22.308333, 73.165278},
    {2, "Diwalipura Circle", 22.301806, 73.165500},
    {3, "Elora T-Junction", 22.315333, 73.161444},
    {4, "Genda Circle (Natubhai Circle)", 22.309944, 73.158667},
    {5, "Gotri Circle", 22.315556, 73.138000},
    {6, "Hari Nagar Char Rasta", 22.311278, 73.153167},
    {7, "ISKCON Circle", 22.303361, 73.151833},
    {8, "Manisha Circle", 22.296306, 73.164583},
    {9, "Nilamber Circle", 22.302000, 73.138944},
    {10, "Tandalja SP T-Junction (Natubhai Circle)", 22.280444, 73.153194}
};
const int numSignals = sizeof(signals) / sizeof(TrafficSignal);

// ==============================================================================
// --- GLOBAL VARIABLES & OBJECTS ---
// ==============================================================================
WiFiClient wifiClient;
PubSubClient client(wifiClient);

char lastApproachingSignal[64] = "";
double lastDistanceToSignal = 99999.0;
bool alertSentForCurrentSignal = false;

// ==============================================================================
// --- HELPER FUNCTIONS ---
// ==============================================================================

double haversine(double lat1, double lon1, double lat2, double lon2) {
    const double R = 6371000.0;
    double lat1_rad = lat1 * M_PI / 180.0;
    double lon1_rad = lon1 * M_PI / 180.0;
    double lat2_rad = lat2 * M_PI / 180.0;
    double lon2_rad = lon2 * M_PI / 180.0;
    double dlon = lon2_rad - lon1_rad;
    double dlat = lat2_rad - lat1_rad;
    double a = sin(dlat / 2.0) * sin(dlat / 2.0) + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2.0) * sin(dlon / 2.0);
    double c = 2.0 * atan2(sqrt(a), sqrt(1.0 - a));
    return R * c;
}

double calculate_bearing(double lat1, double lon1, double lat2, double lon2) {
    double lat1_rad = lat1 * M_PI / 180.0;
    double lon1_rad = lon1 * M_PI / 180.0;
    double lat2_rad = lat2 * M_PI / 180.0;
    double lon2_rad = lon2 * M_PI / 180.0;
    double dLon = lon2_rad - lon1_rad;
    double y = sin(dLon) * cos(lat2_rad);
    double x = cos(lat1_rad) * sin(lat2_rad) - sin(lat1_rad) * cos(lat2_rad) * cos(dLon);
    double bearing = atan2(y, x) * 180.0 / M_PI;
    return fmod((bearing + 360.0), 360.0);
}

String bearing_to_direction(double bearing) {
    if (bearing >= 337.5 || bearing < 22.5) return "North";
    if (bearing >= 22.5 && bearing < 67.5) return "North-East";
    if (bearing >= 67.5 && bearing < 112.5) return "East";
    if (bearing >= 112.5 && bearing < 157.5) return "South-East";
    if (bearing >= 157.5 && bearing < 202.5) return "South";
    if (bearing >= 202.5 && bearing < 247.5) return "South-West";
    if (bearing >= 247.5 && bearing < 292.5) return "West";
    if (bearing >= 292.5 && bearing < 337.5) return "North-West";
    return "Unknown";
}

TrafficSignal* findSignalById(int id) {
    for (int i = 0; i < numSignals; i++) {
        if (signals[i].id == id) return &signals[i];
    }
    return nullptr;
}

// ==============================================================================
// --- MQTT CALLBACK (Data Processing) ---
// ==============================================================================

void callback(char* topic, byte* payload, unsigned int length) {
    char message[length + 1];
    memcpy(message, payload, length);
    message[length] = '\0';
    
    double vehicleLat, vehicleLon, prevVehicleLat, prevVehicleLon;
    int startId, destId, nextSignalId;

    // Parse the 7 values sent by the server
    int success = sscanf(message, "%lf,%lf,%lf,%lf,%d,%d,%d", 
                         &vehicleLat, &vehicleLon, &prevVehicleLat, &prevVehicleLon, 
                         &startId, &destId, &nextSignalId);

    if (success != 7) return;

    TrafficSignal* startSignal = findSignalById(startId);
    TrafficSignal* destSignal = findSignalById(destId);
    TrafficSignal* nextSignal = findSignalById(nextSignalId);

    if (!startSignal || !destSignal || !nextSignal) return;
    
    double distanceToNextSignal = haversine(vehicleLat, vehicleLon, nextSignal->lat, nextSignal->lon);

    // Track state changes between different signals
    if (strcmp(lastApproachingSignal, nextSignal->name) != 0) {
        strcpy(lastApproachingSignal, nextSignal->name);
        lastDistanceToSignal = 99999.0; 
        alertSentForCurrentSignal = false;
    }

    // Continuous Telemetry Output
    Serial.printf("Start: %s | Dest: %s | Next: %s | Dist: %.0fm\n", 
                  startSignal->name, destSignal->name, nextSignal->name, distanceToNextSignal);

    // Arrival Alert
    if (distanceToNextSignal <= ARRIVAL_DISTANCE_METERS && !alertSentForCurrentSignal) {
        Serial.println("\n[!] ARRIVED AT: " + String(nextSignal->name));
        alertSentForCurrentSignal = true; 
    }
    
    // Proximity Approach Alert (Directional)
    if (distanceToNextSignal <= ALERT_DISTANCE_METERS && distanceToNextSignal < lastDistanceToSignal && !alertSentForCurrentSignal) {
        double bearingToSignal = calculate_bearing(vehicleLat, vehicleLon, nextSignal->lat, nextSignal->lon);
        // We want the direction the vehicle is coming FROM relative to the signal center
        double reciprocalBearing = fmod((bearingToSignal + 180.0), 360.0);
        String approachDirection = bearing_to_direction(reciprocalBearing);

        Serial.printf("  >> ALERT: Approaching %s from the %s!\n", nextSignal->name, approachDirection.c_str());
    }
    
    lastDistanceToSignal = distanceToNextSignal;
}

// ==============================================================================
// --- CORE LOGIC ---
// ==============================================================================

void reconnect_mqtt() {
    while (!client.connected()) {
        Serial.print("Attempting MQTT connection...");
        String clientId = "ESP32-Receiver-" + String(random(0xffff), HEX);
        if (client.connect(clientId.c_str())) {
            Serial.println("connected");
            client.subscribe(location_topic);
        } else {
            Serial.print("failed, rc=");
            Serial.print(client.state());
            Serial.println(" try again in 5 seconds");
            delay(5000);
        }
    }
}

void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("\n--- RapidRoute Receiver Final Active ---");
    
    WiFi.begin(ssid, password);
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println("\nWiFi Connected!");

    client.setServer(mqtt_server, 1883);
    client.setCallback(callback);
}

void loop() {
    if (!client.connected()) {
        reconnect_mqtt();
    }
    client.loop();
}