# TapToTalk firmware hello.
# Board: Raspberry Pi Pico, chosen 2026-10-23. ESP32 is a backup only.
#
# Pins (3.3V only). Confirm against the module datasheet before wiring.
#   touch input  GP14  digital output from the touch module
#   key switch   GP15  10k pull-down to GND, sends SELECT
#   LED red      GP16  220 ohm in series unless the module has resistors
#   LED green    GP17  same resistor rule
#   LED blue     GP18  same resistor rule
#
# This file only prints one line. Sensor events come next.
# Serial, once wired: 115200 baud.
#   Pico sends one of TAP / HOLD / SELECT per line.
#   Bridge sends LED idle, LED listening, LED phrase, LED sent, LED alert,
#   and CFG hold_ms <n> (default CFG hold_ms 1000).
# Keep the real input loop non-blocking. No time.sleep longer than 50 ms.


def main():
    print("taptotalk firmware hello")


main()
