from micropython import const

"""
    Possible I2C addresses
    (Default commonly used is 0x37, but confirm with an I2C scan or your config)
"""
CY8_ADDR_DEFAULT = const(0x37)

"""
    Register map ranges (datasheet)
"""
CY8_CFG_START   = const(0x00)
CY8_CFG_END     = const(0x7E)
CY8_CMD_START   = const(0x80)
CY8_CMD_END     = const(0x87)
CY8_STAT_START  = const(0x88)
CY8_STAT_END    = const(0xFB)

"""
    Register addresses (YOU MUST FILL THESE FROM THE CY8CMBR3xxx Registers TRM)
    Commonly used:
      - BUTTON_STAT (status bits for sensor active/inactive)
      - DEVICE_ID / FAMILY_ID / etc for connection check (optional)
      - CTRL_CMD (for save/reset/config actions) (optional)
"""
CY8_REG_BUTTON_STAT = const(0x00)   # TODO: set correct address from TRM
CY8_REG_DEVICE_ID   = const(0x00)   # TODO: optional
CY8_REG_CTRL_CMD    = const(0x00)   # TODO: optional

"""
    Other constants (optional)
"""
CY8_DEVICE_ID_VALUE = const(0x00)   # TODO: only if you use is_connected()