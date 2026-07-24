/*
 * Pinit Hub Firmware (ESP32-C3)
 *
 * Scans for BLE advertisements from Pinit tags (or tag_simulator boards),
 * tracks per-tag presence using an RSSI threshold with hysteresis (so a
 * tag doesn't flap present/absent from a single noisy reading), and
 * reports presence-changed events to the backend over WiFi.
 *
 * Required libraries (Arduino IDE Library Manager):
 *   - ArduinoJson (by Benoit Blanchon)
 * Required board package: esp32 by Espressif Systems, board "ESP32C3 Dev Module"
 *
 * Setup: copy config.h.example to config.h and fill in WiFi + backend details.
 */

#include "BLEDevice.h"
#include "BLEScan.h"
#include "BLEAdvertisedDevice.h"
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

#include "config.h"

#define PINIT_COMPANY_ID 0xFFFF
#define PROTOCOL_VERSION 1

#define SCAN_WINDOW_SEC 3          // how long each BLE scan burst runs
#define SCAN_INTERVAL_MS 5000      // gap between scan bursts
#define RSSI_PRESENT_THRESHOLD -75 // stronger (less negative) than this counts as "seen nearby"
#define PRESENT_CONFIRM_COUNT 2    // consecutive strong readings before flipping to "present"
#define ABSENCE_TIMEOUT_MS 30000   // no sighting at all for this long -> "absent"

#define MAX_TAGS 16
#define MAX_QUEUED_EVENTS 50
#define HTTP_TIMEOUT_MS 4000
#define WIFI_RECONNECT_INTERVAL_MS 10000

struct TagState {
  uint32_t tagId;
  bool present;
  uint8_t presentStreak;
  int lastRssi;
  uint8_t lastBattery;
  unsigned long lastSeenMs;
  bool initialized;
};

struct QueuedEvent {
  uint32_t tagId;
  bool present;
  int rssi;
  uint8_t battery;
};

TagState tags[MAX_TAGS];
int numTags = 0;

QueuedEvent eventQueue[MAX_QUEUED_EVENTS];
int queueHead = 0;
int queueCount = 0;

BLEScan *pBLEScan;
unsigned long lastScanStartMs = 0;
unsigned long lastWifiAttemptMs = 0;

TagState *findOrCreateTag(uint32_t tagId) {
  for (int i = 0; i < numTags; i++) {
    if (tags[i].tagId == tagId) return &tags[i];
  }
  if (numTags >= MAX_TAGS) {
    Serial.println("WARN: MAX_TAGS reached, dropping new tag");
    return nullptr;
  }
  TagState *t = &tags[numTags++];
  t->tagId = tagId;
  t->present = false;
  t->presentStreak = 0;
  t->lastRssi = 0;
  t->lastBattery = 0;
  t->lastSeenMs = 0;
  t->initialized = false;
  return t;
}

void enqueueEvent(uint32_t tagId, bool present, int rssi, uint8_t battery) {
  if (queueCount >= MAX_QUEUED_EVENTS) {
    // Drop the oldest event rather than losing the newest state change.
    queueHead = (queueHead + 1) % MAX_QUEUED_EVENTS;
    queueCount--;
    Serial.println("WARN: event queue full, dropping oldest event");
  }
  int writeIndex = (queueHead + queueCount) % MAX_QUEUED_EVENTS;
  eventQueue[writeIndex] = {tagId, present, rssi, battery};
  queueCount++;
}

class PinitScanCallbacks : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice advertisedDevice) override {
    if (!advertisedDevice.haveManufacturerData()) return;

    std::string mfg = advertisedDevice.getManufacturerData();
    // 2 (company id) + 1 (version) + 4 (tagId) + 1 (battery) + 1 (flags)
    if (mfg.length() < 9) return;

    uint16_t companyId = (uint8_t)mfg[0] | ((uint8_t)mfg[1] << 8);
    if (companyId != PINIT_COMPANY_ID) return;

    uint8_t version = (uint8_t)mfg[2];
    if (version != PROTOCOL_VERSION) return;

    uint32_t tagId;
    memcpy(&tagId, mfg.data() + 3, sizeof(tagId));
    uint8_t battery = (uint8_t)mfg[7];
    int rssi = advertisedDevice.getRSSI();

    TagState *t = findOrCreateTag(tagId);
    if (!t) return;

    t->lastRssi = rssi;
    t->lastBattery = battery;
    t->lastSeenMs = millis();

    if (!t->initialized) {
      // First time we've ever seen this tag: establish a baseline without
      // firing a spurious "arrived" event on hub boot.
      t->initialized = true;
      t->present = (rssi >= RSSI_PRESENT_THRESHOLD);
      t->presentStreak = t->present ? PRESENT_CONFIRM_COUNT : 0;
      return;
    }

    if (rssi >= RSSI_PRESENT_THRESHOLD) {
      if (t->presentStreak < PRESENT_CONFIRM_COUNT) t->presentStreak++;
      if (!t->present && t->presentStreak >= PRESENT_CONFIRM_COUNT) {
        t->present = true;
        Serial.printf("Tag %u -> present (rssi=%d)\n", tagId, rssi);
        enqueueEvent(tagId, true, rssi, battery);
      }
    } else {
      t->presentStreak = 0;
    }
  }
};

void checkAbsences() {
  unsigned long now = millis();
  for (int i = 0; i < numTags; i++) {
    TagState *t = &tags[i];
    if (!t->initialized) continue;
    if (t->present && (now - t->lastSeenMs > ABSENCE_TIMEOUT_MS)) {
      t->present = false;
      t->presentStreak = 0;
      Serial.printf("Tag %u -> absent (no sighting for %lums)\n", t->tagId, now - t->lastSeenMs);
      enqueueEvent(t->tagId, false, t->lastRssi, t->lastBattery);
    }
  }
}

void ensureWifiConnected() {
  if (WiFi.status() == WL_CONNECTED) return;
  unsigned long now = millis();
  if (now - lastWifiAttemptMs < WIFI_RECONNECT_INTERVAL_MS) return;
  lastWifiAttemptMs = now;
  Serial.println("WiFi disconnected, reconnecting...");
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

bool flushEventQueue() {
  if (queueCount == 0) return true;
  if (WiFi.status() != WL_CONNECTED) return false;

  StaticJsonDocument<2048> doc;
  JsonArray events = doc.createNestedArray("events");

  int toSend = min(queueCount, MAX_QUEUED_EVENTS);
  for (int i = 0; i < toSend; i++) {
    int idx = (queueHead + i) % MAX_QUEUED_EVENTS;
    JsonObject e = events.createNestedObject();
    e["tag_id"] = eventQueue[idx].tagId;
    e["present"] = eventQueue[idx].present;
    e["rssi"] = eventQueue[idx].rssi;
    e["battery_pct"] = eventQueue[idx].battery;
  }

  String body;
  serializeJson(doc, body);

  HTTPClient http;
  http.begin(String(BACKEND_BASE_URL) + "/api/events");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Pinit-Hub-Key", HUB_API_KEY);
  http.setTimeout(HTTP_TIMEOUT_MS);

  int statusCode = http.POST(body);
  http.end();

  if (statusCode == 201 || statusCode == 200) {
    queueHead = (queueHead + toSend) % MAX_QUEUED_EVENTS;
    queueCount -= toSend;
    Serial.printf("Flushed %d event(s) to backend\n", toSend);
    return true;
  }

  Serial.printf("Backend POST failed, status=%d (will retry)\n", statusCode);
  return false;
}

void setup() {
  Serial.begin(115200);
  delay(500);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.println("Connecting to WiFi...");

  BLEDevice::init("Pinit-Hub");
  pBLEScan = BLEDevice::getScan();
  pBLEScan->setAdvertisedDeviceCallbacks(new PinitScanCallbacks());
  pBLEScan->setActiveScan(true);
  pBLEScan->setInterval(100);
  pBLEScan->setWindow(99);
}

void loop() {
  ensureWifiConnected();

  unsigned long now = millis();
  if (now - lastScanStartMs >= SCAN_INTERVAL_MS) {
    lastScanStartMs = now;
    pBLEScan->start(SCAN_WINDOW_SEC, false);
    pBLEScan->clearResults();
    checkAbsences();
    flushEventQueue();
  }
}
