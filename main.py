import network
import socket
import time
from machine import Pin, ADC
import gc
from XRPLib.encoded_motor import EncodedMotor

# Initialize hardware
#led = Pin(25, Pin.OUT)  # Built-in LED on Pico
#adc = ADC(0)  # ADC0 on GP26
#pump = Pin("LED", Pin.OUT)  # Pump control pin on GP27

# Global variables
led_state = False
adc_value = 0
is_config_mode = False # False = autonomous | True = Config
moisture_thresholds = [1000, 1000]
auto_water_seconds = [3.0, 3.0]
_server_socket_ref = None  # global so watcher can close it


# --- Hardware Pin Assignments (update these for your wiring) ---
PLANT_PINS = [
    {"led": "LED", "adc": 0, "pump": 3},   # Plant 1: GP2, ADC0, GP3
    {"led": 4, "adc": 1, "pump": 5},   # Plant 2: GP4, ADC1, GP5
    # {"led": 6, "adc": 2, "pump": 7},   # Plant 3: GP6, ADC2, GP7
    # {"led": 8, "adc": 3, "pump": 9},   # Plant 4: GP8, ADC3, GP9
]
USER_BUTTON  = Pin(36, Pin.IN, Pin.PULL_UP)
soil_adc = ADC(Pin(44))        # create an ADC object acting on the soil sensor pin
val = soil_adc.read_u16()  # read a raw analog value in the range 0-65535

# --- Initialize hardware for all plants ---
leds = [Pin(p["led"], Pin.OUT) for p in PLANT_PINS]
adcs = [ADC(p["adc"]) for p in PLANT_PINS]
pumps = [Pin(p["pump"], Pin.OUT) for p in PLANT_PINS]

# --- Global state for all plants ---
led_states = [False] * 4
adc_values = [0] * 4

def create_ap():
    """Create WiFi Access Point"""
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid='PicoHotspot', password='12345678')
    
    while not ap.active():
        pass
    
    print('Access Point created')
    print('SSID: PicoHotspot')
    print('Password: 12345678')
    print('IP Address:', ap.ifconfig()[0])
    return ap


def autonomous_btn_click():
    pass
    

def generate_html():
    html = """<!DOCTYPE html>
    <html lang="en">
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body{margin-top: 150px ;background-color: lightgray; display: flex; flex-direction: column; justify-content: center; font-family:'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;}
        .plants-area{display: flex; flex-direction: row; gap: 120px; justify-content: center;}
        .plant-box{padding: 20px; background-color: white; border: 3px solid grey; border-radius: 8px; display: flex; flex-direction: column}
        .plant-box header{text-align: center; margin-bottom: 20px; font-size: 20px;}
        .attribute{display: flex; flex-direction: row; align-items: center}
        .attribute p{width: 150px; margin-right: 30px;}
        .attribute input{width: 80px; margin-right: 20px;}
        .text-box{margin: 10px; border: 3px, solid, grey; border-radius: 5px; padding: 3px;}
        button{padding: 4px; width: 50px;}
        button:active{translate: 1px 1px}
        .start-btn{background-color: orange; border-radius: 3px; border-style: none;}
        .apply-btn{background-color: lightgreen; border-radius: 3px; border-style: none;}
        .auto-button{background-color: mediumblue; border-radius: 3px; color: white; width: 120px;height: 80px;}
        .auto-button-container{display: flex; justify-content: center; margin-top: 20px;}
    </style>
</head>
<body>
    <div class="plants-area">
        <div class="plant-box">
            <header>Plant 1</header>
            <div class="attribute">
                <p>Soil moisture:</p>
                <input class="text-box" type="text" readonly>
            </div>
            <div class="attribute">
                <p>Pump for:</p>
                <input id="pump0" class="text-box" type="text">
                <button class="start-btn" onclick="runPump(0)">Start</button>
            </div>
            <div class="attribute">
                <p>Moisture threshold:</p>
                <input class="text-box" type="text">
                <button class="apply-btn">Apply</button>
            </div>
            <div class="attribute">
                <p>Water seconds:</p>
                <input class="text-box" type="text">
                <button class="apply-btn">Apply</button>
            </div>
        </div>
        <div class="plant-box">
            <header>Plant 2</header>
            <div class="attribute">
                <p>Soil moisture:</p>
                <input class="text-box" type="text" readonly>
            </div>
            <div class="attribute">
                <p>Pump for:</p>
                <input id="pump1" class="text-box" type="text">
                <button class="start-btn" onclick="runPump(1)">Start</button>
            </div>
            <div class="attribute">
                <p>Moisture threshold:</p>
                <input class="text-box" type="text">
                <button class="apply-btn">Apply</button>
            </div>
            <div class="attribute">
                <p>Water seconds:</p>
                <input class="text-box" type="text">
                <button class="apply-btn">Apply</button>
            </div>
        </div>
    </div>
    <div class="auto-button-container">
        <button class="auto-button">Autonomous Mode</button>
    </div>
        <script>
            async function runPump(i){
                const secs = Number(document.getElementById("pump" + i).value || '0');
                
                if (isNaN(secs)) {
                    alert("Please enter a number.");
                    return;
                }
                if (secs <= 0) {
                    alert("Please enter a number greater than 0.");
                    return;
                }

                try {
                    await fetch('/api/pump/' + i + '/' + secs, { method: 'POST' });
                } catch (e) {
                    console.log("Error sending pump request:", e);
                }
            }

            async function applyThreshold(i){
                thresholdValue = Number(document.getElementById("threshold" + i).value);

                try{
                    await fetch('/api/set_threshold/' + i + '/' + thresholdValue, { method: 'POST' });
                } catch (e){
                    console.log("error setting moisture threhold:", e);
                }

            }

            async function applyWater(i){
                waterValue = Number(document.getElementById("water" + i).value);

                try{
                    await fetch('/api/set_water/' + i + '/' + waterValue, { method: 'POST' });
                } catch (e){
                    console.log("error setting water duration:", e);
                }

            }
        </script>
    </body>
    </html>"""
    return html

def handle_request(client_socket):
    try:
        req = client_socket.recv(1024).decode()
        if not req:
            return

        first_line = req.split('\n', 1)[0].strip()  # "POST /api/pump/0/2 HTTP/1.1"
        parts = first_line.split()
        if len(parts) < 2:
            return
        method, path = parts[0], parts[1]

        # Serve HTML
        if method == 'GET' and path == '/':
            response = 'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n'
            response += generate_html()
            client_socket.send(response.encode())
            return

        # API: pump
        if method == 'POST' and path.startswith('/api/pump/'):
            try:
                _, _, _, idx_str, sec_str = path.split('/')
                print("starting pump")
                idx = int(idx_str)
                print(idx)
                secs = float(sec_str)
                if idx < 0 or idx > 1:
                    raise ValueError('bad plant index')
                
                print("idx: ", idx)

                motor = EncodedMotor.get_default_encoded_motor(idx+1)
                print(idx)
                motor.set_effort(1.0)
                time.sleep(secs)
                motor.set_effort(0.0)

                client_socket.send(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nOK')
            except Exception as e:
                print('pump route error:', e)
                client_socket.send(b'HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nERR')
            return
        
        # API: set per-plant moisture threshold
        if method == 'POST' and path.startswith('/api/set_threshold/'):
            try:
                _, _, _, idx_str, val_str = path.split('/')
                idx = int(idx_str)  
                threshold_val = int(val_str)
                if idx < 1 or idx > 2: raise ValueError('bad plant index')
                moisture_thresholds[idx-1] = threshold_val
                client_socket.send(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nOK')
            except Exception as e:
                print('set_threshold error:', e)
                client_socket.send(b'HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nERR')
            return
        
        # API: set per-plant autonomous watering duration (seconds)
        if method == 'POST' and path.startswith('/api/set_water/'):
            try:
                _, _, _, idx_str, val_str = path.split('/')
                idx = int(idx_str)
                water_secs = float(val_str)
                if idx < 1 or idx > 2: raise ValueError('bad plant index')
                if secs < 0: raise ValueError('PLease enter non-negative seconds')
                auto_water_seconds[idx-1] = water_secs
                client_socket.send(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nOK')
            except Exception as e:
                print('set_water error:', e)
                client_socket.send(b'HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nERR')
            return

        client_socket.send(b'HTTP/1.1 404 Not Found\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nNot Found')

    except Exception as e:
        print(f"Error handling request: {e}")
    finally:
        try: client_socket.close()
        except: pass
        

def _button_watcher():
    global is_config_mode, _server_socket_ref
    last = 1
    pressed_count = 0
    
    while True:
        print("USER_BUTTON value:", USER_BUTTON.value())
        print("Is Config Mode:", is_config_mode)
        val = USER_BUTTON.value()  # 0 when pressed (pull-up)
        if val == 0 and last == 1:
            # simple debounce: wait ~50ms confirming
            time.sleep(0.05)
            if USER_BUTTON.value() == 0:
                if is_config_mode:
                    print("Button pressed -> leaving config mode")
                    is_config_mode = False
                    # Close the server socket to unblock accept()
                    try:
                        if _server_socket_ref:
                            _server_socket_ref.close()
                    except:
                        pass
                else:
                    print("Button pressed -> entering config mode")
                    is_config_mode = True
        last = val
        time.sleep(0.02)

def start_webserver():
    global is_config_mode, _server_socket_ref

    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    server_socket = socket.socket()
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(addr)
    server_socket.listen(2)
    server_socket.settimeout(0.2)   # <<— key: short timeout so we can poll
    _server_socket_ref = server_socket

    print('Web server started on port 80')
    print('Connect to PicoHotspot WiFi and visit: http://192.168.4.1')

    try:
        while is_config_mode:
            try:
                client_socket, caddr = server_socket.accept()
            except OSError:
                # timeout OR socket was closed by watcher — check mode and continue/break
                if not is_config_mode:
                    break
                continue

            try:
                print('Client connected from', caddr)
                handle_request(client_socket)
            finally:
                try: client_socket.close()
                except: pass

            gc.collect()
    finally:
        try: server_socket.close()
        except: pass
        _server_socket_ref = None
            
def config_mode():
    """Configuration mode"""
    
    for i in range(len(PLANT_PINS)):
        motor = EncodedMotor.get_default_encoded_motor(i+1)
        motor.set_effort(0.0)

    
    # Creates the access point
    ap = create_ap()
    
    # Starts the web server
    start_webserver()
    
    try:
        ap.active(False)      # tear down AP before returning to main
        print("AP deactivated")
    except:
        pass
    
    
def autonomous_mode():
    """Autonomous mode"""
    global adc_values, led_states, led_state, adc_value
    
    # while not is_config_mode:
    for i in range(len(PLANT_PINS)):
        adc_values[i] = adcs[i].read_u16()
        print(f"Plant {i+1} ADC Value: {adc_values[i]}")
        
        if adc_values[i] < moisture_thresholds[i]:
            print(f"Plant {i+1} soil is dry. Activating pump for {auto_water_seconds[i]} seconds.")
            motor = EncodedMotor.get_default_encoded_motor(i+1)
            motor.set_effort(1.0)
            time.sleep(auto_water_seconds[i])
            motor.set_effort(0.0)
    

def main():
    global is_config_mode

    print("Starting Pico Web Server...")

    # Start in autonomous unless watcher flips us
    while True:
        print("Main loop iteration. is_config_mode =", is_config_mode)
        if is_config_mode:
            print("Entering Configuration Mode")
            config_mode()   # returns when watcher flips is_config_mode to False
            # loop continues, next iteration will run autonomous
        else:
            # Autonomous runs one short cycle, then yields back to the loop
            # so we can react quickly if the watcher flips the mode.
            # (Avoid a long blocking loop here.)
            autonomous_mode()
            time.sleep(0.1)

if __name__ == '__main__':
    main()


