from machine import I2C, Pin
import time

scl_1_pin: int|str = "I2C_SCL_1"
sda_1_pin: int|str = "I2C_SDA_1"
scl_0_pin: int|str = "I2C_SCL_0"
sda_0_pin: int|str = "I2C_SDA_0"

# Adjust pins to match your board
i2c_1 = I2C(
    1,
    scl=Pin(scl_1_pin),   # or actual GPIO number
    sda=Pin(sda_1_pin),
    freq=400_000
)

i2c_0 = I2C(
    0,
    scl=Pin(scl_0_pin),
    sda=Pin(sda_0_pin),
    freq=400_000
)

print("Scanning I2C 0 bus...")
devices_0 = i2c_0.scan()

if not devices_0:
    print("No I2C 0 devices found.")
else:
    print(f"Found {len(devices_0)} device(s) on I2C 0 bus:")
    for addr in devices_0:
        print("  Decimal:", addr, " Hex:", hex(addr))

print("\nScanning I2C 1 bus...")
devices_1 = i2c_1.scan()

if not devices_1:
    print("No I2C 1 devices found.")
else:
    print(f"Found {len(devices_1)} device(s) on I2C 1 bus:")
    for addr in devices_1:
        print("  Decimal:", addr, " Hex:", hex(addr))