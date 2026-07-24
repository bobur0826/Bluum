/*
 * Pinit Tag Simulator
 *
 * Stand-in for the production nRF52810 tag PCB. Flash this onto any spare
 * ESP32/ESP32-C3 dev board and it advertises the same BLE payload a real
 * Pinit tag would. Since presence detection is RSSI-based, physically
 * carrying this board away from the hub *is* the "item left the house"
 * simulation - no software faking needed.
 *
 * To simulate multiple tags, flash this to multiple boards, changing
 * TAG_ID before each flash.
 *
 * Required board package: esp32 by Espressif Systems (Arduino IDE Boards
 * Manager). Uses the BLE library bundled with that core - no extra
 * libraries to install.
 */

#include "BLEDevice.h"
#include "BLEAdvertising.h"
#include "BLEUtils.h"

// ---- Per-board config: change TAG_ID before flashing each simulator ----
#define TAG_ID 1001
// -------------------------------------------------------------------

// 0xFFFF is the Bluetooth SIG "for testing only" company identifier.
// Swap for a real assigned company ID before any production run.
#define PINIT_COMPANY_ID 0xFFFF
#define PROTOCOL_VERSION 1
#define ADV_INTERVAL_MS 1000

BLEAdvertising *pAdvertising;
uint8_t simulatedBatteryPct = 92;

void buildAndSetAdvertisingData() {
  BLEAdvertisementData advData;
  advData.setFlags(0x06); // general discoverable, BR/EDR not supported

  // Payload layout (little-endian): [companyId:2][version:1][tagId:4][battery:1][flags:1]
  std::string mfgData;
  mfgData += (char)(PINIT_COMPANY_ID & 0xFF);
  mfgData += (char)((PINIT_COMPANY_ID >> 8) & 0xFF);
  mfgData += (char)PROTOCOL_VERSION;

  uint32_t tagId = TAG_ID;
  mfgData.append(reinterpret_cast<char *>(&tagId), sizeof(tagId));

  mfgData += (char)simulatedBatteryPct;
  mfgData += (char)0; // flags byte, reserved (e.g. future motion/button bits)

  advData.setManufacturerData(mfgData);
  pAdvertising->setAdvertisementData(advData);
}

void setup() {
  Serial.begin(115200);

  String deviceName = "Pinit-Tag-" + String(TAG_ID);
  BLEDevice::init(deviceName.c_str());

  pAdvertising = BLEDevice::getAdvertising();
  buildAndSetAdvertisingData();
  pAdvertising->start();

  Serial.printf("Tag simulator running. tag_id=%d name=%s\n", TAG_ID, deviceName.c_str());
}

void loop() {
  // Real tags would sleep between advertising bursts to save battery.
  // Nothing else to do here - the radio keeps advertising on its own.
  delay(ADV_INTERVAL_MS);
}
