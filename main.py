# MicroPython / uasyncio version (no _thread)
import network
import uasyncio as asyncio
import socket
import time  # fine to keep, but we won't call time.sleep()
from machine import Pin, ADC
import gc
from XRPLib.encoded_motor import EncodedMotor
from XRPLib.board import Board

# -------------------------------
# Global configuration & hardware
# -------------------------------

# False = autonomous | True = Config
is_config_mode = False

# Two plants by default
moisture_thresholds = [1000, 1000]      # per-plant soil moisture thresholds
auto_water_seconds = [3.0, 3.0]         # per-plant pump runtime when dry

_server_obj = None  # asyncio server object (so we can close it cleanly)

# --- Hardware Pin Assignments (update these for your wiring) ---
PLANT_PINS = [
    {"led": "LED", "adc": 0, "pump": 3},   # Plant 1: LED, ADC0, GP3
    {"led": 4, "adc": 1, "pump": 5},       # Plant 2: GP4, ADC1, GP5
    # {"led": 6, "adc": 2, "pump": 7},     # Plant 3 example
    # {"led": 8, "adc": 3, "pump": 9},     # Plant 4 example
]

# NOTE: These pins (36, 44) are board-specific; keep as-is per your original code.
USER_BUTTON  = Pin(36, Pin.IN, Pin.PULL_UP) #pin 36 is the USER button on the XRP Control board
SOIL_ADCs = [ADC(Pin(44)), ADC(Pin(45)) ]       # create ADC objects acting on the soil sensor pins

# --- Initialize hardware for all plants ---
leds  = [Pin(p["led"],  Pin.OUT) for p in PLANT_PINS]
adcs  = [ADC(p["adc"]) for p in PLANT_PINS]
pumps = [Pin(p["pump"], Pin.OUT) for p in PLANT_PINS]

# --- Global state for all plants ---
led_states = [False] * len(PLANT_PINS)
adc_values = [0]     * len(PLANT_PINS)
last_watered = [0]   * len(PLANT_PINS)  # timestamp of last water pump activation
pump_tasks = [None]  * len(PLANT_PINS)  # asyncio tasks for pump control (for cancellation)
watering_history = [[] for _ in PLANT_PINS]  # list of watering events: {timestamp, duration, type}

# A simple per-plant lock so pump actions don't overlap
pump_locks = [asyncio.Lock() for _ in PLANT_PINS]


board = Board.get_default_board()

async def run_pump_async(idx, secs):
    """Run pump for specified duration. Can be cancelled via task.cancel()"""
    try:
        async with pump_locks[idx]:
            last_watered[idx] = int(time.time())  # Record timestamp
            watering_history[idx].append({
                "timestamp": last_watered[idx],
                "duration": secs,
                "type": "manual"
            })
            # Keep last 100 events per plant
            if len(watering_history[idx]) > 100:
                watering_history[idx].pop(0)

            motor = EncodedMotor.get_default_encoded_motor(idx + 1)
            motor.set_effort(1.0)
            await asyncio.sleep(secs)
            motor.set_effort(0.0)
    except asyncio.CancelledError:
        # Pump was cancelled, stop the motor immediately
        try:
            motor = EncodedMotor.get_default_encoded_motor(idx + 1)
            motor.set_effort(0.0)
        except:
            pass
        raise

def _send_json(sock, obj, code=200):
    import json
    body = json.dumps(obj).encode()
    hdr = (
        f"HTTP/1.1 {code} OK\r\n"
        "Content-Type: application/json\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n\r\n"
    ).encode()
    sock.send(hdr + body)  
    
# ---------------
# WiFi / AP utils
# ---------------
def create_ap():
    """Create WiFi Access Point (blocking until active)"""
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid='AgXrpHotspot', password='sensor123')
    while not ap.active():
        pass
    print('Access Point created')
    print('SSID: AgXrpHotspot')
    print('Password: sensor123')
    print('IP Address:', ap.ifconfig()[0])
    return ap


# --------------------
# HTTP / HTML frontend
# --------------------
def generate_html():
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AgXRP Autonimous Watering System</title>
<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
  background: #f5f5f7;
  color: #1d1d1d;
  min-height: 100vh;
  padding: 40px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  transition: background 0.3s ease, color 0.3s ease;
}

body.dark-mode {
  background: #1e1e1e;
  color: #e8e8e8;
}

.header {
  text-align: center;
  color: #1d1d1d;
  margin-bottom: 40px;
}

body.dark-mode .header {
  color: #e8e8e8;
}

.header h1 {
  font-size: 2.2em;
  font-weight: 600;
  margin-bottom: 10px;
  letter-spacing: -0.5px;
}

.header p {
  font-size: 1em;
  color: #666;
  font-weight: 400;
  letter-spacing: 0.3px;
}

body.dark-mode .header p {
  color: #aaa;
}

.container {
  width: 100%;
  max-width: 1200px;
}

.plants-area {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 30px;
  margin-bottom: 30px;
}

.plant-box {
  background: white;
  border-radius: 8px;
  padding: 25px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  transition: box-shadow 0.3s ease;
  border: 1px solid #e8e8ea;
}

.plant-box:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

body.dark-mode .plant-box {
  background: #2d2d2d;
  color: #e8e8e8;
  border-color: #3d3d3d;
}

.plant-box header {
  text-align: center;
  font-size: 1.4em;
  font-weight: 600;
  color: #1d1d1d;
  margin-bottom: 25px;
  padding-bottom: 15px;
  border-bottom: 2px solid #3b82f6;
  letter-spacing: -0.3px;
}

body.dark-mode .plant-box header {
  color: #e8e8e8;
}

.control-section {
  margin-bottom: 20px;
  padding: 15px;
  background: #f9fafb;
  border-radius: 6px;
  border-left: 3px solid #3b82f6;
}

.control-section:last-child {
  margin-bottom: 0;
}

body.dark-mode .control-section {
  background: #1f1f23;
  border-left-color: #3b82f6;
}

.attribute {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.attribute-label {
  font-size: 0.95em;
  font-weight: 500;
  color: #555;
}

.input-group {
  display: flex;
  gap: 10px;
  align-items: center;
}

.text-box {
  flex: 1;
  padding: 10px 12px;
  border: 2px solid #e0e0e0;
  border-radius: 6px;
  font-size: 1em;
  font-family: inherit;
  transition: border-color 0.2s ease;
}

.text-box:focus {
  outline: none;
  border-color: #667eea;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
}

.text-box[readonly] {
  background-color: #f0f0f0;
  color: #666;
  cursor: not-allowed;
}

.text-box:disabled {
  background-color: #f0f0f0;
  color: #999;
  cursor: not-allowed;
}

body.dark-mode .text-box[readonly],
body.dark-mode .text-box:disabled {
  background-color: #1a1a1a;
  color: #888;
  border-color: #444;
}

body.dark-mode .text-box {
  background: #2d2d2d;
  color: #e0e0e0;
  border-color: #444;
}

button {
  padding: 10px 16px;
  border: none;
  border-radius: 4px;
  font-size: 0.9em;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  text-transform: none;
  letter-spacing: 0;
}

button:hover {
  opacity: 0.9;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
}

button:active {
  transform: scale(0.98);
}

.start-btn {
  background-color: #10b981;
  color: white;
  flex: 0 0 auto;
}

.start-btn:hover {
  background-color: #059669;
}

.stop-btn {
  background-color: #ef4444;
  color: white;
  flex: 0 0 auto;
  animation: pulse 1s infinite;
}

.stop-btn:hover {
  background-color: #dc2626;
}

@keyframes pulse {
  0%, 100% { box-shadow: 0 2px 8px rgba(239, 68, 68, 0.3); }
  50% { box-shadow: 0 2px 12px rgba(239, 68, 68, 0.5); }
}

.apply-btn {
  background-color: #3b82f6;
  color: white;
  flex: 0 0 auto;
}

.apply-btn:hover {
  background-color: #2563eb;
}

.soil-display {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.moisture-value {
  font-size: 1.5em;
  font-weight: 600;
  color: #3b82f6;
}

.mode-section {
  display: flex;
  justify-content: center;
  gap: 20px;
  flex-wrap: wrap;
}

.auto-button {
  padding: 12px 32px;
  background: #3b82f6;
  color: white;
  font-size: 1em;
  font-weight: 600;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.3s ease;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.2);
}

.auto-button:hover {
  background: #2563eb;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
}

.auto-button:active {
  transform: scale(0.98);
}

@media (max-width: 768px) {
  .header h1 {
    font-size: 2em;
  }

  .plants-area {
    grid-template-columns: 1fr;
  }

  body {
    padding: 20px 10px;
  }
}

.header-controls {
  position: absolute;
  top: 20px;
  right: 20px;
  display: flex;
  gap: 10px;
}

.dark-toggle {
  padding: 8px 12px;
  background-color: #4b5563;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-weight: 600;
  font-size: 0.85em;
  transition: all 0.3s ease;
}

.dark-toggle:hover {
  background-color: #5a6577;
}

.display-panel {
  background: #f9fafb;
  border-radius: 6px;
  padding: 12px;
  margin-bottom: 10px;
  border-left: 3px solid #3b82f6;
  border: 1px solid #e8e8ea;
  border-left: 3px solid #3b82f6;
}

body.dark-mode .display-panel {
  background: #1f1f23;
  border-color: #3d3d3d;
  border-left-color: #3b82f6;
}

.panel-row {
  display: flex;
  justify-content: space-around;
  align-items: center;
  gap: 15px;
  padding: 10px 0;
}

.panel-item {
  text-align: center;
  flex: 1;
}

.panel-label {
  font-size: 0.8em;
  font-weight: 600;
  color: #666;
  margin-bottom: 5px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

body.dark-mode .panel-label {
  color: #999;
}

.panel-value {
  font-size: 1.3em;
  font-weight: 700;
  color: #3b82f6;
  font-family: 'Segoe UI', monospace;
}

.last-watered-display {
  background: #eff6ff;
  border-radius: 6px;
  padding: 12px;
  margin: 10px 0;
  text-align: center;
  border: 1px solid #bfdbfe;
}

body.dark-mode .last-watered-display {
  background: #1e3a4c;
  border-color: #1e40af;
}

.timer-value {
  font-size: 1.6em;
  font-weight: 700;
  color: #3b82f6;
  font-family: 'Courier New', monospace;
  letter-spacing: 2px;
}

body.dark-mode .timer-value {
  color: #60a5fa;
}

.history-btn {
  background-color: #6366f1;
  color: white;
  padding: 8px 12px;
  border: none;
  border-radius: 4px;
  font-size: 0.85em;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  width: 100%;
  margin-top: 10px;
}

.history-btn:hover {
  background-color: #4f46e5;
}

.modal {
  display: none;
  position: fixed;
  z-index: 1000;
  left: 0;
  top: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.5);
  animation: fadeIn 0.3s ease;
}

.modal.show {
  display: flex;
  align-items: center;
  justify-content: center;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.modal-content {
  background: white;
  border-radius: 12px;
  padding: 25px;
  width: 90%;
  max-width: 500px;
  max-height: 80vh;
  overflow-y: auto;
  box-shadow: 0 10px 50px rgba(0, 0, 0, 0.3);
  animation: slideUp 0.3s ease;
}

body.dark-mode .modal-content {
  background: #2d2d2d;
  color: #e0e0e0;
}

@keyframes slideUp {
  from { transform: translateY(20px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  padding-bottom: 15px;
  border-bottom: 2px solid #3b82f6;
}

.modal-header h2 {
  margin: 0;
  font-size: 1.4em;
  font-weight: 600;
}

.close-btn {
  background: none;
  border: none;
  font-size: 1.5em;
  cursor: pointer;
  color: #666;
  padding: 0;
  transition: color 0.2s ease;
}

.close-btn:hover {
  color: #3b82f6;
}

body.dark-mode .close-btn {
  color: #aaa;
}

body.dark-mode .close-btn:hover {
  color: #60a5fa;
}

.history-timeline {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.history-event {
  padding: 12px;
  border-left: 4px solid #6366f1;
  background: #f9fafb;
  border-radius: 4px;
  transition: all 0.2s ease;
}

body.dark-mode .history-event {
  background: #1f1f23;
}

.history-event:hover {
  background: #f3f4f6;
}

body.dark-mode .history-event:hover {
  background: #2a2a30;
}

.history-event.auto {
  border-left-color: #10b981;
}

.history-event.manual {
  border-left-color: #f59e0b;
}

.event-type {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 3px;
  font-size: 0.7em;
  font-weight: 700;
  text-transform: uppercase;
  margin-bottom: 6px;
  letter-spacing: 0.5px;
}

.event-type.auto {
  background: #dcfce7;
  color: #166534;
}

.event-type.manual {
  background: #fef3c7;
  color: #92400e;
}

body.dark-mode .event-type.auto {
  background: #166534;
  color: #dcfce7;
}

body.dark-mode .event-type.manual {
  background: #78350f;
  color: #fef3c7;
}

.event-time {
  font-size: 0.85em;
  color: #999;
  margin-bottom: 5px;
}

body.dark-mode .event-time {
  color: #777;
}

.event-duration {
  font-weight: 700;
  color: #3b82f6;
  font-size: 1em;
}

.empty-message {
  text-align: center;
  padding: 30px;
  color: #999;
}

body.dark-mode .empty-message {
  color: #666;
}
</style>
</head>
<body>
<div class="header-controls">
  <button class="dark-toggle" onclick="toggleDarkMode()">Dark Mode</button>
</div>

<div class="header">
  <h1>Smart Plant Watering System</h1>
  <p>Automated soil moisture monitoring and plant watering</p>
</div>

<div class="container">
  <div class="plants-area">
    <div class="plant-box">
      <header>Plant 1</header>

      <div class="display-panel">
        <div class="panel-row">
          <div class="panel-item">
            <div class="panel-label">Moisture Threshold</div>
            <div class="panel-value" id="display-threshold0">—</div>
          </div>
          <div class="panel-item">
            <div class="panel-label">Auto-Water Duration</div>
            <div class="panel-value" id="display-water0">—</div>s
          </div>
        </div>
      </div>

      <div class="last-watered-display">
        <div class="panel-label">Last Watered</div>
        <div class="timer-value" id="timer0">0:0:0:0</div>
      </div>

      <div class="control-section">
        <div class="attribute">
          <span class="attribute-label">Soil Moisture Level</span>
          <div class="soil-display">
            <input id="soil-field0" class="text-box" type="text" readonly value="—">
          </div>
        </div>
      </div>

      <div class="control-section">
        <div class="attribute">
          <span class="attribute-label">Manual Pump Control (seconds)</span>
          <div class="input-group">
            <input id="pump0" class="text-box" type="text" placeholder="3.0">
            <button class="start-btn" onclick="runPump(0)">Start</button>
          </div>
        </div>
      </div>

      <div class="control-section">
        <div class="attribute">
          <span class="attribute-label">Moisture Threshold</span>
          <div class="input-group">
            <input id="threshold0" class="text-box" type="text" placeholder="1000">
            <button class="apply-btn" onclick="applyThreshold(0)">Apply</button>
          </div>
        </div>
      </div>

      <div class="control-section">
        <div class="attribute">
          <span class="attribute-label">Auto Water Duration (seconds)</span>
          <div class="input-group">
            <input id="water0" class="text-box" type="text" placeholder="3.0">
            <button class="apply-btn" onclick="applyWater(0)">Apply</button>
          </div>
        </div>
      </div>
      <button class="history-btn" onclick="openHistoryModal(0)">View Watering History</button>
    </div>

    <div class="plant-box">
      <header>Plant 2</header>

      <div class="display-panel">
        <div class="panel-row">
          <div class="panel-item">
            <div class="panel-label">Moisture Threshold</div>
            <div class="panel-value" id="display-threshold1">—</div>
          </div>
          <div class="panel-item">
            <div class="panel-label">Auto-Water Duration</div>
            <div class="panel-value" id="display-water1">—</div>s
          </div>
        </div>
      </div>

      <div class="last-watered-display">
        <div class="panel-label">Last Watered</div>
        <div class="timer-value" id="timer1">0:0:0:0</div>
      </div>

      <div class="control-section">
        <div class="attribute">
          <span class="attribute-label">Soil Moisture Level</span>
          <div class="soil-display">
            <input id="soil-field1" class="text-box" type="text" readonly value="—">
          </div>
        </div>
      </div>

      <div class="control-section">
        <div class="attribute">
          <span class="attribute-label">Manual Pump Control (seconds)</span>
          <div class="input-group">
            <input id="pump1" class="text-box" type="text" placeholder="3.0">
            <button class="start-btn" onclick="runPump(1)">Start</button>
          </div>
        </div>
      </div>

      <div class="control-section">
        <div class="attribute">
          <span class="attribute-label">Moisture Threshold</span>
          <div class="input-group">
            <input id="threshold1" class="text-box" type="text" placeholder="1000">
            <button class="apply-btn" onclick="applyThreshold(1)">Apply</button>
          </div>
        </div>
      </div>

      <div class="control-section">
        <div class="attribute">
          <span class="attribute-label">Auto Water Duration (seconds)</span>
          <div class="input-group">
            <input id="water1" class="text-box" type="text" placeholder="3.0">
            <button class="apply-btn" onclick="applyWater(1)">Apply</button>
          </div>
        </div>
      </div>
      <button class="history-btn" onclick="openHistoryModal(1)">View Watering History</button>
    </div>
  </div>

  <div class="mode-section">
    <button class="auto-button" onclick="toggleAutonomous()">Toggle Autonomous Mode</button>
  </div>
</div>

<script>
// Track pump state and timeouts
const pumpState = { 0: false, 1: false };
const pumpTimeouts = { 0: null, 1: null };

// Dark mode toggle
function toggleDarkMode() {
  document.body.classList.toggle('dark-mode');
  localStorage.setItem('darkMode', document.body.classList.contains('dark-mode'));
}

// Initialize dark mode from localStorage
if (localStorage.getItem('darkMode') === 'true') {
  document.body.classList.add('dark-mode');
}

function updatePumpButton(i) {
  const btn = document.querySelector(`button[onclick="runPump(${i})"], button[onclick="stopPump(${i})"]`);
  const input = document.getElementById("pump" + i);
  if (pumpState[i]) {
    btn.textContent = "Stop";
    btn.onclick = function() { stopPump(i); };
    btn.classList.remove("start-btn");
    btn.classList.add("stop-btn");
    input.disabled = true;
  } else {
    btn.textContent = "Start";
    btn.onclick = function() { runPump(i); };
    btn.classList.remove("stop-btn");
    btn.classList.add("start-btn");
    input.disabled = false;
  }
}

async function runPump(i){
  const secs = Number(document.getElementById("pump" + i).value || '0');
  if (isNaN(secs)) { alert("Please enter a number."); return; }
  if (secs <= 0) { alert("Please enter a number greater than 0."); return; }

  try {
    pumpState[i] = true;
    updatePumpButton(i);

    await fetch('/api/pump/' + i + '/' + secs, { method: 'POST' });

    // Set timeout to auto-reset button after duration
    pumpTimeouts[i] = setTimeout(() => {
      pumpState[i] = false;
      updatePumpButton(i);
      updateSettings(i);
    }, secs * 1000);
  } catch(e) {
    console.log("Error sending pump request:", e);
    pumpState[i] = false;
    updatePumpButton(i);
  }
}

async function stopPump(i){
  try {
    if (pumpTimeouts[i]) {
      clearTimeout(pumpTimeouts[i]);
      pumpTimeouts[i] = null;
    }
    pumpState[i] = false;
    updatePumpButton(i);
    await fetch('/api/pump_stop/' + i, { method: 'POST' });
  } catch(e) {
    console.log("Error stopping pump:", e);
  }
}

async function applyThreshold(i){
  const v = Number(document.getElementById("threshold" + i).value);
  if (isNaN(v)) { alert("Enter a number"); return; }
  try {
    await fetch('/api/set_threshold/' + i + '/' + v, { method: 'POST' });
    alert("Threshold updated for Plant " + (i + 1));
    updateSettings(i);
  } catch(e) { console.log("error setting moisture threshold:", e); }
}

async function applyWater(i){
  const v = Number(document.getElementById("water" + i).value);
  if (isNaN(v) || v < 0) { alert("Enter a non-negative number"); return; }
  try {
    await fetch('/api/set_water/' + i + '/' + v, { method: 'POST' });
    alert("Auto-water duration updated for Plant " + (i + 1));
    updateSettings(i);
  } catch(e) { console.log("error setting water duration:", e); }
}

async function updateSettings(i){
  try {
    const res = await fetch('/api/get_settings/' + i, { method: 'GET' });
    const json_res = await res.json();
    document.getElementById("display-threshold" + i).textContent = json_res.threshold;
    document.getElementById("display-water" + i).textContent = json_res.water_duration.toFixed(1);
    window["lastWatered" + i] = json_res.last_watered;
    window["serverTime" + i] = json_res.current_time;
  } catch (e) {
    console.log("error updating settings display: ", e)
  }
}

function formatTimeSince(plantIdx) {
  const lastWatered = window["lastWatered" + plantIdx] || 0;
  const serverTime = window["serverTime" + plantIdx] || 0;

  if (!lastWatered || lastWatered === 0) return "Never";

  const seconds = serverTime - lastWatered;
  if (seconds < 0) return "Never";

  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;

  return `${days}:${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

async function updateSoil(i){
  try {
    const res = await fetch('/api/update_soil/' + i, { method: 'GET' });
    const json_res = await res.json();
    const moistureValue = json_res.raw;
    document.getElementById("soil-field" + i).value = moistureValue;

    // Change color based on moisture level
    const input = document.getElementById("soil-field" + i);
    const threshold = parseInt(document.getElementById("threshold" + i).value) || 1000;
    if (moistureValue < threshold) {
      input.style.background = "rgba(255, 107, 107, 0.1)";
    } else {
      input.style.background = "";
    }
  } catch (e) {
    console.log("error updating soil moisture: ", e)
  }
}

function updateTimers() {
  updateSettings(0);
  updateSettings(1);
  document.getElementById("timer0").textContent = formatTimeSince(0);
  document.getElementById("timer1").textContent = formatTimeSince(1);
}

setInterval(() => updateSoil(0), 1000);
setInterval(() => updateSoil(1), 1000);
setInterval(updateTimers, 1000);

updateSoil(0);
updateSoil(1);
updateTimers();

async function toggleAutonomous(){
  try {
    await fetch('/api/toggle_mode', { method: 'POST' });
    alert("Mode toggled! Refresh page to see update.");
  } catch(e) { console.log("error toggling mode:", e); }
}

async function openHistoryModal(plantIdx) {
  const modal = document.getElementById("historyModal");
  const modalTitle = document.getElementById("modalTitle");
  const historyContainer = document.getElementById("historyContainer");

  modalTitle.textContent = `Plant ${plantIdx + 1} - Watering History`;

  try {
    const res = await fetch('/api/get_watering_history/' + plantIdx, { method: 'GET' });
    const json_res = await res.json();
    const history = json_res.history || [];
    const currentTime = json_res.current_time;

    if (history.length === 0) {
      historyContainer.innerHTML = '<div class="empty-message">No watering events recorded yet</div>';
      modal.classList.add('show');
      return;
    }

    // Sort history in reverse order (newest first)
    const sortedHistory = [...history].reverse();

    historyContainer.innerHTML = sortedHistory.map((event, idx) => {
      const timeSince = formatTimeForHistory(currentTime - event.timestamp);
      const eventDate = new Date(event.timestamp * 1000).toLocaleString();
      const typeClass = event.type === 'auto' ? 'auto' : 'manual';
      const typeLabel = event.type === 'auto' ? 'Automatic' : 'Manual';

      return `
        <div class="history-event ${typeClass}">
          <span class="event-type ${typeClass}">${typeLabel}</span>
          <div class="event-time">${timeSince} ago</div>
          <div>${eventDate}</div>
          <div class="event-duration">Duration: ${event.duration}s</div>
        </div>
      `;
    }).join('');

    modal.classList.add('show');
  } catch (e) {
    console.log("error loading history:", e);
    historyContainer.innerHTML = '<div class="empty-message">Error loading history</div>';
    modal.classList.add('show');
  }
}

function closeHistoryModal() {
  const modal = document.getElementById("historyModal");
  modal.classList.remove('show');
}

function formatTimeForHistory(seconds) {
  if (seconds < 60) return "Just now";
  if (seconds < 3600) return Math.floor(seconds / 60) + "m";
  if (seconds < 86400) return Math.floor(seconds / 3600) + "h";
  return Math.floor(seconds / 86400) + "d";
}

// Close modal when clicking outside of it
window.onclick = function(event) {
  const modal = document.getElementById("historyModal");
  if (event.target == modal) {
    modal.classList.remove('show');
  }
}
</script>

<!-- History Modal -->
<div id="historyModal" class="modal">
  <div class="modal-content">
    <div class="modal-header">
      <h2 id="modalTitle">Plant 1 - Watering History</h2>
      <button class="close-btn" onclick="closeHistoryModal()">&times;</button>
    </div>
    <div id="historyContainer" class="history-timeline">
      <!-- History events will be inserted here -->
    </div>
  </div>
</div>

</body>
</html>"""
    return html


async def handle_client(reader, writer):
    """Async HTTP 1.0/1.1 handler (very small, just enough for this UI)."""
    try:
        req = await reader.read(1024)
        if not req:
            return
        try:
            req_s = req.decode()
        except:
            req_s = str(req)

        first_line = req_s.split('\n', 1)[0].strip()  # "POST /api/pump/0/2 HTTP/1.1"
        parts = first_line.split()
        if len(parts) < 2:
            return
        method, path = parts[0], parts[1]

        # Serve HTML
        if method == 'GET' and path == '/':
            body = generate_html()
            resp = (
                'HTTP/1.1 200 OK\r\n'
                'Content-Type: text/html\r\n'
                'Connection: close\r\n\r\n' + body
            )
            writer.write(resp.encode())
            await writer.drain()
            return

        # Toggle mode (UI button) — flips to autonomous and button task will also work
        if method == 'POST' and path == '/api/toggle_mode':
            global is_config_mode
            is_config_mode = not is_config_mode
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nOK')
            await writer.drain()
            return
        
        #API: get soil moisture
        if method == 'GET' and path.startswith('/api/update_soil/'):
            try:
                _, _, _, idx_str = path.split('/')
                idx = int(idx_str)
                if idx < 0 or idx >= len(SOIL_ADCs): raise ValueError('bad plant index')
                raw_val = SOIL_ADCs[idx].read_u16()
                import json
                body = json.dumps({"raw": raw_val}).encode()
                hdr = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(hdr + body)
            except Exception as e:
                print('error reading soil sensor', e)
                writer.write(b'HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nERR')
            await writer.drain()
            return

        # API: pump (indexes 0..N-1)
        if method == 'POST' and path.startswith('/api/pump/'):
            try:
                _, _, _, idx_str, sec_str = path.split('/')
                idx = int(idx_str)
                secs = float(sec_str)
                if idx < 0 or idx >= len(PLANT_PINS):
                    raise ValueError('bad plant index')
                if secs <= 0:
                    raise ValueError('seconds must be > 0')

                # Cancel any existing pump task
                if pump_tasks[idx] is not None:
                    pump_tasks[idx].cancel()

                # Create and store new pump task
                pump_tasks[idx] = asyncio.create_task(run_pump_async(idx, secs))

                writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nOK')
            except Exception as e:
                print('pump route error:', e)
                writer.write(b'HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nERR')
            await writer.drain()
            return

        # API: pump stop (indexes 0..N-1)
        if method == 'POST' and path.startswith('/api/pump_stop/'):
            try:
                _, _, _, idx_str = path.split('/')
                idx = int(idx_str)
                if idx < 0 or idx >= len(PLANT_PINS):
                    raise ValueError('bad plant index')

                # Cancel the pump task if it exists
                if pump_tasks[idx] is not None:
                    pump_tasks[idx].cancel()
                    pump_tasks[idx] = None

                # Ensure motor is off
                async with pump_locks[idx]:
                    motor = EncodedMotor.get_default_encoded_motor(idx + 1)
                    motor.set_effort(0.0)

                writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nOK')
            except Exception as e:
                print('pump stop error:', e)
                writer.write(b'HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nERR')
            await writer.drain()
            return

        # API: set per-plant moisture threshold
        if method == 'POST' and path.startswith('/api/set_threshold/'):
            try:
                _, _, _, idx_str, val_str = path.split('/')
                idx = int(idx_str)
                threshold_val = int(val_str)
                if idx < 0 or idx >= len(moisture_thresholds):
                    raise ValueError('bad plant index') 
                moisture_thresholds[idx] = threshold_val
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nOK')
            except Exception as e:
                print('set_threshold error:', e)
                writer.write(b'HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nERR')
            await writer.drain()
            return

        # API: set per-plant autonomous watering duration (seconds)
        if method == 'POST' and path.startswith('/api/set_water/'):
            try:
                _, _, _, idx_str, val_str = path.split('/')
                idx = int(idx_str)
                water_secs = float(val_str)
                if idx < 0 or idx >= len(auto_water_seconds):
                    raise ValueError('bad plant index')
                if water_secs < 0:
                    raise ValueError('Please enter non-negative seconds')  # FIX: variable name
                auto_water_seconds[idx] = water_secs
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nOK')
            except Exception as e:
                print('set_water error:', e)
                writer.write(b'HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nERR')
            await writer.drain()
            return

        # API: get plant settings and last watered time
        if method == 'GET' and path.startswith('/api/get_settings/'):
            try:
                _, _, _, idx_str = path.split('/')
                idx = int(idx_str)
                if idx < 0 or idx >= len(PLANT_PINS):
                    raise ValueError('bad plant index')
                import json
                body = json.dumps({
                    "threshold": moisture_thresholds[idx],
                    "water_duration": auto_water_seconds[idx],
                    "last_watered": last_watered[idx],
                    "current_time": int(time.time())
                }).encode()
                hdr = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(hdr + body)
            except Exception as e:
                print('get_settings error:', e)
                writer.write(b'HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nERR')
            await writer.drain()
            return

        # API: get watering history
        if method == 'GET' and path.startswith('/api/get_watering_history/'):
            try:
                _, _, _, idx_str = path.split('/')
                idx = int(idx_str)
                if idx < 0 or idx >= len(PLANT_PINS):
                    raise ValueError('bad plant index')
                import json
                body = json.dumps({
                    "history": watering_history[idx],
                    "current_time": int(time.time())
                }).encode()
                hdr = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(hdr + body)
            except Exception as e:
                print('get_watering_history error:', e)
                writer.write(b'HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nERR')
            await writer.drain()
            return

        # Not found
        writer.write(b'HTTP/1.1 404 Not Found\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nNot Found')
        await writer.drain()

    except Exception as e:
        print("Error handling request:", e)
    finally:
        try:
            await writer.drain()
        except:
            pass
        try:
            # Some MicroPython builds may not have wait_closed(); ignore if so
            await writer.wait_closed()
        except:
            try:
                writer.close()
            except:
                pass


# -----------------------
# Mode handlers (asyncio)
# -----------------------
async def start_webserver():
    """Start async web server on port 80 (returns server object)."""
    print('Web server starting on port 80...')
    server = await asyncio.start_server(handle_client, '0.0.0.0', 80, backlog=2)
    print('Web server started. Visit: http://192.168.4.1')
    return server


async def stop_webserver(server):
    """Stop the async web server cleanly."""
    try:
        print("Stopping web server...")
        server.close()
        await server.wait_closed()
        print("Web server stopped.")
    except Exception as e:
        print("Error stopping server:", e)


async def config_mode_task():
    """Run configuration mode: bring up AP and serve the UI until mode flips false."""
    global _server_obj

    # Ensure all pumps off when entering config
    for i in range(len(PLANT_PINS)):
        try:
            motor = EncodedMotor.get_default_encoded_motor(i + 1)
            motor.set_effort(0.0)
        except Exception as e:
            print("Motor init off error:", e)

    ap = create_ap()

    # Start server
    _server_obj = await start_webserver()

    try:
        # Poll until mode flips off (button task or UI endpoint will flip)
        while is_config_mode:
            await asyncio.sleep(0.2)
            gc.collect()
    finally:
        # Stop server and AP
        if _server_obj:
            await stop_webserver(_server_obj)
            _server_obj = None
        try:
            ap.active(False)
            print("AP deactivated")
        except:
            pass


async def autonomous_cycle_once():
    """One short autonomous scan of all plants."""
    for i in range(len(PLANT_PINS)):
        try:
            adc_values[i] = SOIL_ADCs[i].read_u16()
        except Exception as e:
            print("ADC read fail plant", i, e)
            adc_values[i] = 0

        print(f"Plant {i+1} ADC Value: {adc_values[i]} (threshold {moisture_thresholds[i]})")

        if adc_values[i] < moisture_thresholds[i]:
            # Soil is "dry" by your convention: lower value = drier.
            secs = float(auto_water_seconds[i])
            print(f"Plant {i+1} soil is dry. Activating pump for {secs} seconds.")
            try:
                async with pump_locks[i]:
                    last_watered[i] = int(time.time())  # Record timestamp
                    watering_history[i].append({
                        "timestamp": last_watered[i],
                        "duration": secs,
                        "type": "auto"
                    })
                    # Keep last 100 events per plant
                    if len(watering_history[i]) > 100:
                        watering_history[i].pop(0)

                    motor = EncodedMotor.get_default_encoded_motor(i + 1)
                    motor.set_effort(1.0)
                    await asyncio.sleep(secs)
                    motor.set_effort(0.0)
            except Exception as e:
                print("Pump error:", e)


# -------------------
# Button watcher task
# -------------------
async def button_watcher():
    """Poll a pull-up button; short press toggles config/autonomous."""
    global is_config_mode
    last = 1

    while True:
        try:
            val = USER_BUTTON.value()  # 0 when pressed
            # simple edge detect w/ debounce
            if val == 0 and last == 1:
                await asyncio.sleep_ms(50)
                if USER_BUTTON.value() == 0:
                    is_config_mode = not is_config_mode
                    print("Button pressed -> is_config_mode:", is_config_mode)
                    # wait for release
                    while USER_BUTTON.value() == 0:
                        await asyncio.sleep_ms(10)
            last = val
        except Exception as e:
            print("Button watcher error:", e)
        await asyncio.sleep_ms(20)


# -----
# main
# -----
async def main():
    global is_config_mode

    print("Starting Pico (u)asyncio app...")

    # Kick off the button watcher (no threads)
    asyncio.create_task(button_watcher())

    # Start in autonomous unless user flips the mode
    while True:
        print("Main loop. is_config_mode =", is_config_mode)

        if is_config_mode:
            print("Entering Configuration Mode")
            board.led_on()
            await config_mode_task()  # returns when mode flips to False
            # loop continues, next iteration will run autonomous
        else:
            # Run a single quick autonomous cycle, then yield back to loop
            board.led_off()
            await autonomous_cycle_once()
            await asyncio.sleep(0.1)

        gc.collect()


# Entry point
try:
    asyncio.run(main())
finally:
    # Ensure pumps off if we ever exit
    try:
        for i in range(len(PLANT_PINS)):
            motor = EncodedMotor.get_default_encoded_motor(i + 1)
            motor.set_effort(0.0)
    except:
        pass