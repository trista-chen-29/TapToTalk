# TapToTalk firmware hello.
# Board default: Raspberry Pi Pico or Pico W (Hardware Plan B).
# Do not mix in ESP32 pins unless the team switches plans together.
#
# Plan B pins (3.3V only):
#   touch input  GP14  digital output from the touch module
#   key switch   GP15  10k pull-down to GND
#   LED data     GP16  check the module logic level before wiring
#
# This file only prints one line. Sensor events come next.
# Serial, once wired: 115200 baud, one of TAP / HOLD / SELECT per line.
# Keep the real input loop non-blocking. No time.sleep longer than 50 ms.


def main():
    print("taptotalk firmware hello")


main()
