# input_test.py - Friday night task 2
# Prints TAP, HOLD and SELECT from the real touch sensor and key switch.
# Done when each action prints exactly once per press.
#
# Wiring (check against the Hardware Plan doc):
#   Touch sensor  SIG -> GP14 (pin 19), VCC -> 3V3 OUT (pin 36), GND -> GND (pin 38)
#   Key switch module (pins labelled "-", middle, "S"):
#                 "-" -> GND, middle pin -> 3V3 OUT, "S" -> GP15 (pin 20)
#                 No extra resistor: the module has its own, and S reads 0 when pressed.
#                 Module with only "-" and "S": same wiring without the middle pin;
#                 the Pico's internal pull-up below does the resistor's job.

from machine import Pin
import time

TOUCH_PIN = 14
KEY_PIN = 15

HOLD_MS = 800       # long press threshold; later this comes from profile.json via CFG hold_ms
DEBOUNCE_MS = 30    # ignore changes shorter than this
POLL_MS = 5         # how often we read the pins

TOUCH_ACTIVE_LOW = False   # set True if the touch sensor reads 0 when touched
KEY_ACTIVE_LOW = True      # the key module pulls S to 0 when pressed

# The metal touch sensor (KY-036 style) flickers on and off very fast while touched,
# because it picks up mains hum through your body. Count the touch as "still on"
# if it was on at any point in the last TOUCH_HOLDOVER_MS. 0 turns this off.
TOUCH_HOLDOVER_MS = 150

DEBUG_RAW = False          # True prints a raw 0/1 line every 200 ms, to check wiring

touch = Pin(TOUCH_PIN, Pin.IN)                 # touch module drives DO itself
key = Pin(KEY_PIN, Pin.IN, Pin.PULL_UP)        # reads 1 at rest, 0 when pressed


def emit(event):
    # One event per line over USB serial. The bridge reads these lines.
    # Check CONTRACT.md section 4 for the exact event format.
    print(event)


class Button:
    """Debounces one input and turns presses into events.

    on_short: called on release if no HOLD was sent during the press
    on_hold:  called once while still pressed, after hold_ms (None = no hold)
    """

    def __init__(self, pin, on_short, on_hold=None, hold_ms=HOLD_MS, active_low=False,
                 holdover_ms=0):
        self.pin = pin
        self.on_short = on_short
        self.on_hold = on_hold
        self.hold_ms = hold_ms
        self.active_low = active_low
        self.holdover_ms = holdover_ms
        self.last_on = None      # last time the raw input read "pressed"
        self.stable = self.read()
        self.last_raw = self.stable
        self.last_change = time.ticks_ms()
        self.pressed_at = None   # stays None if the input was already high at boot
        self.hold_sent = False

    def read(self):
        # Returns 1 when pressed, 0 when released, whatever the wiring polarity
        value = self.pin.value()
        value = 1 - value if self.active_low else value
        if not self.holdover_ms:
            return value
        # Smooth out flicker: stay "on" until the input has been off for holdover_ms
        now = time.ticks_ms()
        if value:
            self.last_on = now
            return 1
        if self.last_on is not None and time.ticks_diff(now, self.last_on) < self.holdover_ms:
            return 1
        return 0

    def update(self, now):
        raw = self.read()

        # Restart the debounce timer whenever the raw value changes
        if raw != self.last_raw:
            self.last_raw = raw
            self.last_change = now

        # Accept the new value only once it has been steady for DEBOUNCE_MS
        if raw != self.stable and time.ticks_diff(now, self.last_change) >= DEBOUNCE_MS:
            self.stable = raw
            if raw:  # pressed
                self.pressed_at = now
                self.hold_sent = False
            else:    # released
                if self.pressed_at is not None and not self.hold_sent:
                    self.on_short()
                self.pressed_at = None

        # Send HOLD while still pressed, so the patient gets feedback without letting go
        if (self.on_hold and self.stable and self.pressed_at is not None
                and not self.hold_sent
                and time.ticks_diff(now, self.pressed_at) >= self.hold_ms):
            self.hold_sent = True
            self.on_hold()


touch_button = Button(touch, on_short=lambda: emit("TAP"), on_hold=lambda: emit("HOLD"),
                      active_low=TOUCH_ACTIVE_LOW, holdover_ms=TOUCH_HOLDOVER_MS)
key_button = Button(key, on_short=lambda: emit("SELECT"),   # any press of the key = one SELECT
                    active_low=KEY_ACTIVE_LOW)

print("input_test ready: touch = TAP / HOLD, key = SELECT")

last_debug = time.ticks_ms()
while True:
    now = time.ticks_ms()
    touch_button.update(now)
    key_button.update(now)
    if DEBUG_RAW and time.ticks_diff(now, last_debug) >= 200:
        last_debug = now
        print("raw touch GP14 =", touch.value(), " raw key GP15 =", key.value())
    time.sleep_ms(POLL_MS)
