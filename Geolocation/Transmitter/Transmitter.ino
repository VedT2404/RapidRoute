/**
 * @file    Transmitter.ino
 * @author  Gemini
 * @brief   Fetches geolocation and publishes it to an MQTT broker.
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include "Geolocation.h" // Your updated header file

// WiFi Credentials
const char* ssid = "VED_TUF";
const char* password = "lemaou3000";

// MQTT Broker Settings
const char* mqtt_server = "broker.hivemq.com";
const int mqtt_port = 1883;
const char* mqtt_topic = "rapidroute/location/data";

// Initialize WiFi and MQTT clients
WiFiClient espClient;
PubSubClient client(espClient);

void reconnect() {
  // Loop until we're reconnected
  while (!client.connected()) {
    Serial.print("Attempting MQTT connection...");
    // Attempt to connect with a unique client ID
    if (client.connect("ESP32TransmitterClient")) {
      Serial.println("connected");
    } else {
      Serial.print("failed, rc=");
      Serial.print(client.state());
      Serial.println(" try again in 5 seconds");
      // Wait 5 seconds before retrying
      delay(5000);
    }
  }
}

void setup() {
  // Connect to Wi-Fi. Serial.begin is called inside this function.
  connect_to_wifi(ssid, password);
  
  // Configure MQTT client
  client.setServer(mqtt_server, mqtt_port);
}
 
void loop() {
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  // Get the location data as a formatted string
  String locationString = get_location_string();
  
  if (locationString.length() > 0) {
    // Publish the string to the MQTT topic
    client.publish(mqtt_topic, locationString.c_str());
    Serial.println("MQTT message published.");
  } else {
    Serial.println("Failed to retrieve location data, not publishing.");
  }
  
  delay(5000); // Wait 5 seconds
}
