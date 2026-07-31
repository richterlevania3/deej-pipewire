const int NUM_SLIDERS = 5;
const int analogInputs[NUM_SLIDERS] = {A0, A1, A2, A3, A4};

int analogSliderValues[NUM_SLIDERS];

void setup() { 
  for (int i = 0; i < NUM_SLIDERS; i++) {
    pinMode(analogInputs[i], INPUT);
  }

  Serial.begin(9600);
}

void loop() {
  updateSliderValues();
  sendSliderValues(); // Actually send data (all the time)
  // printSliderValues(); // For debug
  delay(10);
}

void updateSliderValues() {
  // oversample each slider to suppress ADC/pot jitter, so deej's fine (1%)
  // noise-reduction threshold doesn't pass electrical noise as real movement
  const int SAMPLES = 16;
  for (int i = 0; i < NUM_SLIDERS; i++) {
     long sum = 0;
     for (int s = 0; s < SAMPLES; s++) {
        sum += analogRead(analogInputs[i]);
     }
     analogSliderValues[i] = sum / SAMPLES;
  }
}

void sendSliderValues() {
  String builtString = String("");

  for (int i = 0; i < NUM_SLIDERS; i++) {
    builtString += String((int)analogSliderValues[i]);

    if (i < NUM_SLIDERS - 1) {
      builtString += String("|");
    }
  }
  
  Serial.println(builtString);
}

void printSliderValues() {
  for (int i = 0; i < NUM_SLIDERS; i++) {
    String printedString = String("Slider #") + String(i + 1) + String(": ") + String(analogSliderValues[i]) + String(" mV");
    Serial.write(printedString.c_str());

    if (i < NUM_SLIDERS - 1) {
      Serial.write(" | ");
    } else {
      Serial.write("\n");
    }
  }
}
