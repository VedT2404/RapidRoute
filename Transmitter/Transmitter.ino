/**
 * @file    Transmitter.ino
 * @brief   Fetches simulated coordinates from the Python server and 
 * publishes them to the MQTT broker.
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <PubSubClient.h>

// ==============================================================================
// --- CONFIGURATION ---
// ==============================================================================
const char* ssid = "VED_TUF";
const char* password = "lemaou3000";
const char* mqtt_server = "broker.hivemq.com";
const char* location_topic = "rapidroute/location/data";

// This is the IP address of your laptop's hotspot
const char* laptopIp = "192.168.137.1"; 
const int laptopPort = 5000;

// ==============================================================================
// --- GLOBAL OBJECTS ---
// ==============================================================================
WiFiClient wifiClient;
PubSubClient client(wifiClient);

// ==============================================================================
// --- MQTT FUNCTIONS ---
// ==============================================================================

void reconnect_mqtt() {
    // Loop until we're reconnected
    while (!client.connected()) {
        Serial.print("Attempting MQTT connection...");
        // Generate a unique client ID
        String clientId = "ESP32-Transmitter-";
        clientId += String(random(0xffff), HEX);
        
        if (client.connect(clientId.c_str())) {
            Serial.println("connected");
        } else {
            Serial.print("failed, rc=");
            Serial.print(client.state());
            Serial.println(" try again in 5 seconds");
            delay(5000);
        }
    }
}

// ==============================================================================
// --- SETUP & LOOP ---
// ==============================================================================

void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("\n\n--- RapidRoute Transmitter Active ---");

    // Connect to WiFi
    WiFi.begin(ssid, password);
    Serial.println("Connecting to WiFi...");
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println("\nWiFi Connected!");
    Serial.print("IP Address: ");
    Serial.println(WiFi.localIP());

    // Initialize MQTT
    client.setServer(mqtt_server, 1883);
}

void loop() {
    // Ensure MQTT is connected
    if (!client.connected()) {
        reconnect_mqtt();
    }
    client.loop();

    // Fetch location from the Python server
    HTTPClient http;
    String serverPath = "http://" + String(laptopIp) + ":" + String(laptopPort) + "/location";
    
    // Fast polling for smooth map updates
    http.begin(serverPath.c_str());
    int httpResponseCode = http.GET();

    if (httpResponseCode == 200) {
        String payload = http.getString();
        
        // Publish the coordinate string directly to MQTT
        bool published = client.publish(location_topic, payload.c_str());
        
        if (published) {
            Serial.print("Published: ");
            Serial.println(payload);
        } else {
            Serial.println("MQTT Publish Failed.");
        }
    } else if (httpResponseCode == 500) {
        // This usually means the Python server is running but no route is selected yet
        Serial.println("Server 500: Waiting for route selection in Control Panel...");
    } else {
        Serial.print("HTTP Error: ");
        Serial.println(httpResponseCode);
    }

    http.end();

    // Delay between polls (lower value = smoother movement, higher = less network load)
    delay(250); 
}