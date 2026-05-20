#include <ArduinoBLE.h>

#define FSR_PIN A0
#define MOTOR_PIN 3
#define LED_PIN LED_BUILTIN

BLEService fsrService("180C");
BLEStringCharacteristic fsrChar("2A56", BLENotify, 32);
BLEStringCharacteristic cmdChar("2A57", BLEWrite, 16);

int threshold = 500;
int wakeThreshold = 900;   // squeeze harder than this to wake
int motorIntensity = 150;
int sampleDelay = 50;

unsigned long timeOffset = 0;
bool sleeping = false;

// Serial logging throttling (keeps BLE timing stable while still showing "it's alive")
const unsigned long SERIAL_PRINT_INTERVAL_MS = 500;
unsigned long lastSerialPrintMs = 0;
unsigned long samplesSincePrint = 0;
int lastFsr = 0;
unsigned long lastT = 0;

void enterSoftSleep() {
  Serial.println("Entering soft sleep...");
  analogWrite(MOTOR_PIN, 0);
  digitalWrite(LED_PIN, LOW);
  BLE.stopAdvertise();
  BLE.disconnect();
  sleeping = true;
}

void wakeUp() {
  Serial.println("Waking up...");
  sleeping = false;
  timeOffset = millis();  // auto-sync time on wake too
  BLE.advertise();
  Serial.println("BLE advertising resumed.");
}

void sleepLoop() {
  // Minimal loop — just watch FSR, everything else is off
  while (sleeping) {
    int fsr = analogRead(FSR_PIN);
    if (fsr > wakeThreshold) {
      // Debounce — confirm it's a real squeeze not a spike
      delay(80);
      fsr = analogRead(FSR_PIN);
      if (fsr > wakeThreshold) {
        wakeUp();
        return;
      }
    }
    delay(100);  // poll at 10 Hz to save power while sleeping
  }
}

void setup() {
  pinMode(MOTOR_PIN, OUTPUT);
  pinMode(LED_PIN, OUTPUT);
  Serial.begin(115200);

  if (!BLE.begin()) {
    Serial.println("BLE failed!");
    while (1);
  }

  BLE.setLocalName("HapticBall");
  BLE.setAdvertisedService(fsrService);
  fsrService.addCharacteristic(fsrChar);
  fsrService.addCharacteristic(cmdChar);
  BLE.addService(fsrService);
  BLE.advertise();

  Serial.println("BLE ready...");
}

void loop() {
  if (sleeping) {
    sleepLoop();
    return;
  }

  BLE.poll();

  // ==== HANDLE COMMANDS ====
  if (cmdChar.written()) {
    String cmd = cmdChar.value();
    cmd.trim();

    if (cmd == "SYNC") {
      timeOffset = millis();
      Serial.println("Timestamp synced.");
    } else if (cmd == "SLEEP") {
      enterSoftSleep();
      return;
    }
  }

  int fsr = analogRead(FSR_PIN);
  unsigned long t = millis() - timeOffset;

  analogWrite(MOTOR_PIN, fsr > threshold ? motorIntensity : 0);

  if (BLE.connected()) {
    digitalWrite(LED_PIN, HIGH);
    fsrChar.writeValue(String(t) + "," + String(fsr));
  } else {
    digitalWrite(LED_PIN, (millis() / 500) % 2);
  }

  // Throttled serial heartbeat (prints latest sample + effective sample rate)
  lastFsr = fsr;
  lastT = t;
  samplesSincePrint++;
  unsigned long now = millis();
  if (now - lastSerialPrintMs >= SERIAL_PRINT_INTERVAL_MS) {
    float hz = (samplesSincePrint * 1000.0f) / (now - lastSerialPrintMs);
    Serial.print("t=");
    Serial.print(lastT);
    Serial.print(" fsr=");
    Serial.print(lastFsr);
    Serial.print(" hz=");
    Serial.print(hz, 1);
    Serial.print(" ble=");
    Serial.println(BLE.connected() ? "1" : "0");
    lastSerialPrintMs = now;
    samplesSincePrint = 0;
  }

  delay(sampleDelay);
}