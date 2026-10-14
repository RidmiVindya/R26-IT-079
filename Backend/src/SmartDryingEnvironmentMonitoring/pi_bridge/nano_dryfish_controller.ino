/*
 * Smart Karawala - Dry Fish Verification Station & Oven Controller
 * Enhanced Arduino Nano Firmware with Animated Graphical OLED Display
 * ====================================================================
 * Hardware Connections:
 * - OLED Display (SSD1306 128x64):
 *     * 4-Pin I2C (Standard): VCC -> 5V, GND -> GND, SCL -> A5, SDA -> A4 (Address 0x3C / 0x3D)
 *     * 7-Pin SPI: VCC, GND, CLK: D13, MOSI: D11, CS: D10, DC: D9, RES: D8
 * - SHT30 Temp & Humidity: I2C (Address 0x44 or 0x45) -> A4 (SDA), A5 (SCL)
 * - DS18B20 Temp Sensor: OneWire Pin D5
 * - MQ2 Gas Sensor: Analog Pin A0
 * - HX711 Load Cell: DT Pin D2, SCK Pin D4
 * - Heater Relay: Pin D3 (HIGH = ON, LOW = OFF)
 * - Light MOSFET: Pin D6 (HIGH = ON, LOW = OFF)
 * - Fan MOSFET: Pin D7 (HIGH = ON, LOW = OFF)
 *
 * NOTE: PROGMEM is used for all custom animation bitmaps and F() for strings
 * to strictly preserve SRAM for the SSD1306 1024-byte framebuffer.
 */

#include <OneWire.h>
#include <DallasTemperature.h>
#include <Wire.h>
#include <Adafruit_SHT31.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <HX711.h>
#include <avr/pgmspace.h>

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64

// ----------------------------------------------------------------------------
// Display Configuration
// Set USE_I2C_OLED to true for standard 4-pin I2C OLED (SDA:A4, SCL:A5).
// Set USE_I2C_OLED to false for 7-pin SPI OLED.
// ----------------------------------------------------------------------------
#define USE_I2C_OLED false

#if USE_I2C_OLED
  #define OLED_RESET -1
  Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
#else
  #define OLED_MOSI 11
  #define OLED_CLK 13
  #define OLED_DC 9
  #define OLED_CS 10
  #define OLED_RESET 8
  Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, OLED_MOSI, OLED_CLK, OLED_DC, OLED_RESET, OLED_CS);
#endif

// Sensors & Actuators Pin Definitions
#define ONE_WIRE_BUS 5
#define MQ2_PIN A0
#define HX711_DT 2
#define HX711_SCK 4

#define HEATER_RELAY_PIN 3
#define LIGHT_MOSFET_PIN 6
#define FAN_MOSFET_PIN 7

OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature ds18b20(&oneWire);
Adafruit_SHT31 sht30 = Adafruit_SHT31();
HX711 scale;

// State Variables
bool heaterState = false;
bool lightState = false;
bool fanState = false;

bool oledOK = false;
bool shtOK = false;
bool hxOK = false;

float shtTemp = 0.0;
float humidity = 0.0;
float dsTemp = 0.0;
int gasValue = 0;
long loadCellRaw = 0;

// Animation & Telemetry Timers
unsigned long lastTelemetryTime = 0;
const unsigned long TELEMETRY_INTERVAL = 1000;

unsigned long lastAnimTime = 0;
const unsigned long ANIM_INTERVAL = 250; // 4 FPS animation tick
uint8_t animFrame = 0;

// ============================================================================
// PROGMEM Bitmaps for Gorgeous Animated Icons (8x8 and 10x10)
// ============================================================================
// Thermometer Icon (8x10)
const unsigned char PROGMEM icon_thermometer[] = {
  0b01100000,
  0b01010000,
  0b01010000,
  0b01110000,
  0b01110000,
  0b11111000,
  0b11111000,
  0b11111000,
  0b01110000,
  0b00000000
};

// Water Droplet Icon for Humidity (8x10)
const unsigned char PROGMEM icon_droplet[] = {
  0b00100000,
  0b01110000,
  0b01110000,
  0b11111000,
  0b11111000,
  0b11111000,
  0b11111000,
  0b01110000,
  0b00000000,
  0b00000000
};

// Heat Wave Flame Animation (8x8, 2 Frames)
const unsigned char PROGMEM icon_flame_f1[] = {
  0b00100100,
  0b01001000,
  0b01001000,
  0b00100100,
  0b00100100,
  0b01001000,
  0b01001000,
  0b00100100
};
const unsigned char PROGMEM icon_flame_f2[] = {
  0b01001000,
  0b00100100,
  0b00100100,
  0b01001000,
  0b01001000,
  0b00100100,
  0b00100100,
  0b01001000
};

// Fan Blade Animation (8x8, 4 Frames: +, x, +, x)
const unsigned char PROGMEM icon_fan_f1[] = {
  0b00011000,
  0b00011000,
  0b00011000,
  0b11111111,
  0b11111111,
  0b00011000,
  0b00011000,
  0b00011000
};
const unsigned char PROGMEM icon_fan_f2[] = {
  0b10000001,
  0b01000010,
  0b00100100,
  0b00011000,
  0b00011000,
  0b00100100,
  0b01000010,
  0b10000001
};

// Light Bulb Glowing Icon (8x8)
const unsigned char PROGMEM icon_bulb_on[] = {
  0b01111110,
  0b11111111,
  0b11111111,
  0b11111111,
  0b01111110,
  0b00111100,
  0b00111100,
  0b00011000
};
const unsigned char PROGMEM icon_bulb_off[] = {
  0b01111110,
  0b10000001,
  0b10000001,
  0b10000001,
  0b01000010,
  0b00100100,
  0b00111100,
  0b00011000
};


// ============================================================================
// Setup
// ============================================================================
void setup() {
  Serial.begin(9600);

  pinMode(HEATER_RELAY_PIN, OUTPUT);
  pinMode(LIGHT_MOSFET_PIN, OUTPUT);
  pinMode(FAN_MOSFET_PIN, OUTPUT);

  digitalWrite(HEATER_RELAY_PIN, LOW);
  digitalWrite(LIGHT_MOSFET_PIN, LOW);
  digitalWrite(FAN_MOSFET_PIN, LOW);

  delay(150);

  // Initialize OLED Display (Tries 0x3C first, then 0x3D)
#if USE_I2C_OLED
  Wire.begin();
  Wire.setClock(400000); // 400kHz Fast I2C for silky smooth UI
  oledOK = display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  if (!oledOK) {
    oledOK = display.begin(SSD1306_SWITCHCAPVCC, 0x3D);
  }
#else
  oledOK = display.begin(SSD1306_SWITCHCAPVCC);
#endif

  if (oledOK) {
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);

    // Boot Splash Animation
    display.drawRoundRect(2, 2, 124, 60, 4, SSD1306_WHITE);
    display.setTextSize(1);
    display.setCursor(18, 12);
    display.print(F("SMART KARAWALA"));
    display.setCursor(22, 26);
    display.print(F("DRYING OVEN"));

    // Animated Loading Bar
    for (int i = 0; i < 90; i += 15) {
      display.fillRoundRect(18, 42, i, 6, 2, SSD1306_WHITE);
      display.display();
      delay(40);
    }
    delay(200);
  } else {
    Serial.println(F("OLED not found"));
  }

  ds18b20.begin();

  shtOK = sht30.begin(0x44);
  if (!shtOK) {
    shtOK = sht30.begin(0x45);
  }

  scale.begin(HX711_DT, HX711_SCK);
  hxOK = scale.is_ready();

  Serial.println(F("System Ready"));
}


// ============================================================================
// Main Loop
// ============================================================================
void loop() {
  readSerialCommands();

  unsigned long currentMillis = millis();

  // Animation Frame Tick (Every 250ms)
  if (currentMillis - lastAnimTime >= ANIM_INTERVAL) {
    lastAnimTime = currentMillis;
    animFrame = (animFrame + 1) % 4;
    if (oledOK) {
      drawBeautifulDashboard();
    }
  }

  // Sensor Telemetry & Serial Output Tick (Every 1000ms)
  if (currentMillis - lastTelemetryTime >= TELEMETRY_INTERVAL) {
    lastTelemetryTime = currentMillis;
    readSensors();
    printSensorDataJSON();
  }
}


// ============================================================================
// Serial Commands Interface
// ============================================================================
void readSerialCommands() {
  while (Serial.available() > 0) {
    char input = Serial.read();

    if (input == '1') {
      heaterState = true;
      digitalWrite(HEATER_RELAY_PIN, HIGH);
      Serial.println(F("Heater ON"));
    }
    else if (input == '0') {
      heaterState = false;
      digitalWrite(HEATER_RELAY_PIN, LOW);
      Serial.println(F("Heater OFF"));
    }
    else if (input == 'l' || input == 'L') {
      lightState = true;
      digitalWrite(LIGHT_MOSFET_PIN, HIGH);
      Serial.println(F("Light ON"));
    }
    else if (input == 'k' || input == 'K') {
      lightState = false;
      digitalWrite(LIGHT_MOSFET_PIN, LOW);
      Serial.println(F("Light OFF"));
    }
    else if (input == 'f' || input == 'F') {
      fanState = true;
      digitalWrite(FAN_MOSFET_PIN, HIGH);
      Serial.println(F("Fan ON"));
    }
    else if (input == 'e' || input == 'E') {
      fanState = false;
      digitalWrite(FAN_MOSFET_PIN, LOW);
      Serial.println(F("Fan OFF"));
    }
    else if (input == 't' || input == 'T') {
      if (scale.is_ready()) {
        scale.tare();
        Serial.println(F("Load Cell Tared"));
      } else {
        Serial.println(F("HX711 not ready"));
      }
    }
  }
}


// ============================================================================
// Sensor Reading
// ============================================================================
void readSensors() {
  if (shtOK) {
    float t = sht30.readTemperature();
    float h = sht30.readHumidity();

    if (!isnan(t) && !isnan(h)) {
      shtTemp = t;
      humidity = h;
    }
  }

  ds18b20.requestTemperatures();
  float d = ds18b20.getTempCByIndex(0);
  if (d > -55.0 && d < 125.0) {
    dsTemp = d;
  } else {
    dsTemp = shtTemp;
  }

  gasValue = analogRead(MQ2_PIN);

  if (scale.is_ready()) {
    hxOK = true;
    loadCellRaw = scale.read();
  } else {
    hxOK = false;
  }
}


// ============================================================================
// Standard JSON Telemetry for Raspberry Pi
// ============================================================================
void printSensorDataJSON() {
  Serial.print(F("DATA:{"));
  Serial.print(F("\"sht_temp\":")); Serial.print(shtTemp, 2); Serial.print(F(","));
  Serial.print(F("\"humidity\":")); Serial.print(humidity, 2); Serial.print(F(","));
  Serial.print(F("\"ds_temp\":")); Serial.print(dsTemp, 2); Serial.print(F(","));
  Serial.print(F("\"gas\":")); Serial.print(gasValue); Serial.print(F(","));
  Serial.print(F("\"load_cell\":")); Serial.print(hxOK ? loadCellRaw : 0); Serial.print(F(","));
  Serial.print(F("\"heater\":")); Serial.print(heaterState ? 1 : 0); Serial.print(F(","));
  Serial.print(F("\"light\":")); Serial.print(lightState ? 1 : 0); Serial.print(F(","));
  Serial.print(F("\"fan\":")); Serial.print(fanState ? 1 : 0);
  Serial.println(F("}"));
}


// ============================================================================
// Gorgeous Animated OLED Display UI (128x64)
// ============================================================================
void drawBeautifulDashboard() {
  display.clearDisplay();

  // 1. Top Header Bar
  display.fillRect(0, 0, SCREEN_WIDTH, 11, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK, SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(2, 2);
  display.print(F("SMART KARAWALA"));

  // Top Right Pulse Heartbeat Dot
  if (animFrame % 2 == 0) {
    display.fillCircle(123, 5, 2, SSD1306_BLACK);
  }

  // 2. Main Metrics Container (Left Column)
  display.setTextColor(SSD1306_WHITE);

  // Temperature Box
  display.drawBitmap(2, 15, icon_thermometer, 8, 10, SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(14, 16);
  display.print(shtTemp, 1);
  display.print((char)247); // Degree symbol
  display.print(F("C"));

  // Humidity Box
  display.drawBitmap(2, 28, icon_droplet, 8, 10, SSD1306_WHITE);
  display.setCursor(14, 29);
  display.print(humidity, 0);
  display.print(F("% RH"));

  // Secondary Temp & Gas
  display.setCursor(2, 42);
  display.print(F("DS:"));
  display.print(dsTemp, 1);
  display.print(F("C G:"));
  display.print(gasValue);

  // Weight / Load Cell Line
  display.setCursor(2, 54);
  display.print(F("Wt:"));
  if (hxOK) {
    // Show rough kg if calibrated or raw value
    float approxKg = (loadCellRaw - 71900) / 381866.0;
    if (approxKg < 0) approxKg = 0.0;
    display.print(approxKg, 2);
    display.print(F("kg ("));
    display.print(loadCellRaw / 1000);
    display.print(F("k)"));
  } else {
    display.print(F("No Scale"));
  }

  // Vertical Separator Divider
  display.drawFastVLine(66, 13, 38, SSD1306_WHITE);

  // 3. Actuator Status & Animated Graphics (Right Column)
  // --- A. HEATER ACTUATOR ---
  display.setCursor(70, 16);
  display.print(F("H:"));
  if (heaterState) {
    // Animated Heat Waves (Pulsing rising flames)
    const unsigned char* flameIcon = (animFrame % 2 == 0) ? icon_flame_f1 : icon_flame_f2;
    display.drawBitmap(84, 15, flameIcon, 8, 8, SSD1306_WHITE);
    display.fillRoundRect(95, 14, 30, 10, 2, SSD1306_WHITE);
    display.setTextColor(SSD1306_BLACK, SSD1306_WHITE);
    display.setCursor(98, 15);
    display.print(F("HEAT"));
    display.setTextColor(SSD1306_WHITE);
  } else {
    display.drawRoundRect(95, 14, 30, 10, 2, SSD1306_WHITE);
    display.setCursor(102, 15);
    display.print(F("OFF"));
  }

  // --- B. LIGHT ACTUATOR ---
  display.setCursor(70, 29);
  display.print(F("L:"));
  if (lightState) {
    // Glowing Light Bulb Icon
    display.drawBitmap(84, 28, icon_bulb_on, 8, 8, SSD1306_WHITE);
    display.fillRoundRect(95, 27, 30, 10, 2, SSD1306_WHITE);
    display.setTextColor(SSD1306_BLACK, SSD1306_WHITE);
    display.setCursor(102, 28);
    display.print(F("ON"));
    display.setTextColor(SSD1306_WHITE);
  } else {
    display.drawBitmap(84, 28, icon_bulb_off, 8, 8, SSD1306_WHITE);
    display.drawRoundRect(95, 27, 30, 10, 2, SSD1306_WHITE);
    display.setCursor(102, 28);
    display.print(F("OFF"));
  }

  // --- C. FAN ACTUATOR ---
  display.setCursor(70, 42);
  display.print(F("F:"));
  if (fanState) {
    // Animated Spinning Fan Blades (Rotates every 250ms)
    const unsigned char* fanIcon = (animFrame % 2 == 0) ? icon_fan_f1 : icon_fan_f2;
    display.drawBitmap(84, 41, fanIcon, 8, 8, SSD1306_WHITE);
    display.fillRoundRect(95, 40, 30, 10, 2, SSD1306_WHITE);
    display.setTextColor(SSD1306_BLACK, SSD1306_WHITE);
    display.setCursor(102, 41);
    display.print(F("ON"));
    display.setTextColor(SSD1306_WHITE);
  } else {
    display.drawRoundRect(95, 40, 30, 10, 2, SSD1306_WHITE);
    display.setCursor(102, 41);
    display.print(F("OFF"));
  }

  display.display();
}
