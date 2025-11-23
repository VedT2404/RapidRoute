/**
 * @file    geolocation.h
 * @author  Gemini
 * @brief   Performs a Wi-Fi scan and uses Google's Geolocation API for a more
 * accurate location estimate.
 */

#ifndef GEOLOCATION_H
#define GEOLOCATION_H

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// --- PASTE YOUR GOOGLE GEOLOCATION API KEY HERE ---
const char* GOOGLE_API_KEY = "Your API"; 

void connect_to_wifi(const char* ssid, const char* password) {
  Serial.begin(115200);
  delay(100);
  Serial.println("\nConnecting to WiFi...");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\n--------------------------------------");
  Serial.println("WiFi Connected!");
  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());
  Serial.println("--------------------------------------");
}

String get_location_string() {
  String formattedString = "";

  // --- ADDED ERROR CHECK: Verify API Key is set ---
  if (strcmp(GOOGLE_API_KEY, "YOUR_API_KEY") == 0) {
    Serial.println("ERROR: Please paste your Google Geolocation API key into the Geolocation.h file.");
    delay(5000); // Wait before retrying
    return "";
  }

  Serial.println("Scanning for Wi-Fi networks...");

  // Perform a Wi-Fi scan
  int n = WiFi.scanNetworks();
  Serial.print(n);
  Serial.println(" networks found.");

  if (n == 0) {
    Serial.println("No networks found, cannot determine location.");
    return "";
  }

  // Create the JSON payload for the Google Geolocation API
  DynamicJsonDocument jsonDoc(2048);
  JsonArray wifiAccessPoints = jsonDoc.createNestedArray("wifiAccessPoints");

  for (int i = 0; i < n; ++i) {
    JsonObject wifiPoint = wifiAccessPoints.createNestedObject();
    wifiPoint["macAddress"] = WiFi.BSSIDstr(i);
    wifiPoint["signalStrength"] = WiFi.RSSI(i);
    wifiPoint["channel"] = WiFi.channel(i);
  }

  String requestBody;
  serializeJson(jsonDoc, requestBody);

  // Send the request to the Google Geolocation API
  HTTPClient http;
  String apiUrl = "https://www.googleapis.com/geolocation/v1/geolocate?key=";
  apiUrl += GOOGLE_API_KEY;
  
  http.begin(apiUrl);
  http.addHeader("Content-Type", "application/json");

  int httpResponseCode = http.POST(requestBody);

  // --- ADDED ERROR CHECK: Verify HTTP response is successful ---
  if (httpResponseCode == 200) { // 200 means "OK"
    String payload = http.getString();
    DynamicJsonDocument responseDoc(1024);
    DeserializationError error = deserializeJson(responseDoc, payload);

    if (error) {
      Serial.print("deserializeJson() failed: ");
      Serial.println(error.c_str());
      return "";
    }

    float lat = responseDoc["location"]["lat"];
    float lng = responseDoc["location"]["lng"];
    float accuracy = responseDoc["accuracy"];

    // We don't get city/country from this API, so we'll send accuracy instead
    formattedString = String(lat, 6) + "," + String(lng, 6) + ",Accuracy:," + String(accuracy) + "m";

    Serial.println("--- Location Data (Transmitter) ---");
    Serial.println("Latitude: " + String(lat, 6));
    Serial.println("Longitude: " + String(lng, 6));
    Serial.println("Accuracy: " + String(accuracy) + " meters");
    Serial.println("-----------------------------------");

  } else {
    Serial.print("Error on HTTP request: ");
    Serial.println(httpResponseCode);
    String payload = http.getString(); // Get error message from Google
    Serial.println("Google API Error Message:");
    Serial.println(payload);
  }
  
  http.end();
  return formattedString;
}

#endif // GEOLOCATION_H
