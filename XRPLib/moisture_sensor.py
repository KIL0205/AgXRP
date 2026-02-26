try:
    from .moisture_sensor_defs import *
except (TypeError, ModuleNotFoundError):
    pass

from machine import I2C, Pin
import time

class MoistureSensor:

    _DEFAULT_INSTANCE = None

    @classmethod
    def get_default_moisture_sensor(cls):
        """
        Singleton getter, mirroring IMU.get_default_imu().
        """
        if cls._DEFAULT_INSTANCE is None:
            cls._DEFAULT_INSTANCE = cls()
        return cls._DEFAULT_INSTANCE

    def __init__(
        self,
        scl_pin: int | str = "I2C_SCL_1",
        sda_pin: int | str = "I2C_SDA_1",
        addr: int = CY8_ADDR_DEFAULT,
        i2c_id: int = 1,
        freq: int = 400_000,
        n_channels: int = 2,
        active_high_means_wet: bool = True,
    ):
        # I2C values
        self.i2c = I2C(id=i2c_id, scl=Pin(scl_pin), sda=Pin(sda_pin), freq=freq)
        self.addr = addr

        # Config
        self.n_channels = n_channels
        self.active_high_means_wet = active_high_means_wet

        # TX/RX buffers (matches IMU style)
        self.tb = bytearray(1)
        self.rb = bytearray(1)

        # Sanity check: ensure register constants were set
        if CY8_REG_BUTTON_STAT == 0x00:
            # If 0x00 is actually correct for your part, delete this guard.
            # Otherwise, it helps catch "forgot to fill in TRM addresses".
            pass

    """
        Private helper methods to read and write registers
        (same pattern as IMU)
    """

    def _setreg(self, reg: int, dat: int):
        self.tb[0] = dat & 0xFF
        self.i2c.writeto_mem(self.addr, reg, self.tb)

    def _getreg(self, reg: int) -> int:
        self.i2c.readfrom_mem_into(self.addr, reg, self.rb)
        return self.rb[0]

    def _getregs(self, reg: int, num_bytes: int) -> bytearray:
        rx_buf = bytearray(num_bytes)
        self.i2c.readfrom_mem_into(self.addr, reg, rx_buf)
        return rx_buf

    """
        Public API Methods
    """

    def is_connected(self) -> bool:
        """
        Optional identity check (only works if you fill DEVICE_ID constants).
        If you don't have those, just return True (or implement an I2C scan).
        """
        if CY8_REG_DEVICE_ID == 0x00 and CY8_DEVICE_ID_VALUE == 0x00:
            return True
        dev_id = self._getreg(CY8_REG_DEVICE_ID)
        return dev_id == CY8_DEVICE_ID_VALUE

    def read_active_mask(self) -> int:
        """
        Reads the touch/active status bitmask.
        Many CY8 status masks are 16-bit (supports up to 16 sensors), so we read 2 bytes.
        Confirm width in the TRM.
        """
        if CY8_REG_BUTTON_STAT == 0x00:
            raise RuntimeError("CY8_REG_BUTTON_STAT not set (fill in from Registers TRM).")

        raw = self._getregs(CY8_REG_BUTTON_STAT, 2)
        return raw[0] | (raw[1] << 8)

    def is_wet(self, channel: int) -> bool:
        """
        Interprets 'active' as 'wet' by default (you can invert).
        """
        if channel < 0 or channel >= self.n_channels:
            raise ValueError("bad channel index")

        active = bool(self.read_active_mask() & (1 << channel))
        return active if self.active_high_means_wet else (not active)

    def read_all(self) -> list[bool]:
        """
        Returns wet states for all channels: [wet0, wet1, ...]
        """
        mask = self.read_active_mask()
        out = []
        for ch in range(self.n_channels):
            active = bool(mask & (1 << ch))
            out.append(active if self.active_high_means_wet else (not active))
        return out