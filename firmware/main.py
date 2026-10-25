# main.py - TapToTalk Pico firmware (CONTRACT.md v1.7)
#
# What it does:
#   - Sends TAP, HOLD, HOLD_LONG and SELECT to the laptop over USB serial (contract section 1).
#   - Listens for "LED <state>", "CFG hold_ms <n>", and "CFG touch_holdover_ms <n>"
#     from the bridge (contract section 2).
#   - Sends nothing else.
#   - Local mode: until the bridge sends its first LED command, the Pico lights the LED
#     from your taps by itself (same rules as contract section 4), for testing and demos.
#     After that, only the bridge changes the LED.
#
# Saved on the Pico as main.py, it starts by itself every time the Pico powers on.
# For testing in Thonny: click Run, then type a command such as  LED listening
# in the Shell and press Enter.
#
# Wiring (Pico lying sideways, USB on the left):
#   Touch sensor  DO -> GP14 (pin 19, 2nd from the right, bottom edge)
#   Key module    S  -> GP15 (pin 20, last on the right, bottom edge); middle pin -> 3.3V, "-" -> GND
#   RGB LED       R -> GP16 (pin 21), G -> GP17 (pin 22), B -> GP18 (pin 24), "-" -> GND
#                 (top edge counted from the right; pin 23, 3rd from the right, is GND)
#
# Hardware note for CONTRACT.md: our key module (HW-483) has its own resistor and reads 0
# when pressed, so it uses a pull-up instead of the 10k pull-down the contract describes.
# The messages are unchanged.

import sys
import select
import time
from machine import Pin, PWM

# ---- Pins -------------------------------------------------------------------
TOUCH_PIN = 14
KEY_PIN = 15
LED_PINS = (16, 17, 18)       # R, G, B

# ---- Input settings ---------------------------------------------------------
HOLD_MS_DEFAULT = 1000        # contract default; the bridge can change it with CFG hold_ms
HOLD_LONG_MS = 3000           # direct nurse call (FR19); fixed, CFG hold_ms does not change it
HOLD_MS_MIN = 200             # CFG values outside this range are ignored
HOLD_MS_MAX = 5000
DEBOUNCE_MS = 30              # a change must last this long to count
POLL_MS = 1                   # narrow KY-036 pulses were missed at 5 ms on the Pico 2 W

TOUCH_ACTIVE_LOW = False      # True if the touch sensor reads 0 when touched
KEY_ACTIVE_LOW = True         # HW-483 key module reads 0 when pressed
TOUCH_HOLDOVER_MS = 150       # gaps in the KY-036 pulse train; CFG touch_holdover_ms
TOUCH_HOLDOVER_MIN = 20       # CFG values outside this range are ignored
TOUCH_HOLDOVER_MAX = 400
HELD_HOLDOVER_MS = 500        # once HOLD is sent, a dropout shorter than this still counts as
                              # held, so a wobbly 3-second hold can reach HOLD_LONG

# ---- LED settings (contract section 2) -----------------------------------
COMMON_ANODE = False          # HW-479 module has a "-" pin, so False
BLINK_MS = 250                # on and off time for blinking states
LED_STATES = {
    #  name        (R, G, B)       blinking
    "idle":      ((0, 0, 0),     False),   # off
    "listening": ((0, 0, 255),   False),   # solid blue
    "phrase":    ((0, 0, 255),   True),    # blinking blue
    "sent":      ((0, 255, 0),   False),   # green
    "alert":     ((255, 0, 0),   False),   # red
}

# ---- Serial out --------------------------------------------------------------
def emit(event):
    # One message per line. The contract allows only TAP, HOLD, HOLD_LONG and SELECT.
    sys.stdout.write(event + "\n")
    local.on_event(event)       # drives the LED itself until the bridge takes over


# ---- Inputs ------------------------------------------------------------------
class Input:
    """Debounces one pin and turns presses into events.

    on_press:  called once when a press starts
    on_short:  called on release if no HOLD was sent during that press
    on_hold:   called once while still pressed, after hold_ms
    on_long:   called once while still pressed, after long_ms (comes after on_hold)
    """

    def __init__(self, pin, active_low=False, holdover_ms=0,
                 on_press=None, on_short=None, on_hold=None, hold_ms=HOLD_MS_DEFAULT,
                 on_long=None, long_ms=HOLD_LONG_MS):
        self.pin = pin
        self.active_low = active_low
        self.holdover_ms = holdover_ms
        self.on_press = on_press
        self.on_short = on_short
        self.on_hold = on_hold
        self.hold_ms = hold_ms
        self.on_long = on_long
        self.long_ms = long_ms
        self.long_sent = False
        self.hold_sent = False
        self.last_on = None
        self.stable = self.read(time.ticks_ms())
        self.last_raw = self.stable
        self.last_change = time.ticks_ms()
        self.pressed_at = None     # stays None if already pressed at power-on

    def read(self, now):
        value = self.pin.value()
        if self.active_low:
            value = 1 - value
        if not self.holdover_ms:
            return value
        if value:
            self.last_on = now
            return 1
        holdover = self.holdover_ms
        if self.hold_sent and self.on_long and not self.long_sent:
            holdover = max(holdover, HELD_HOLDOVER_MS)   # be forgiving on the way to HOLD_LONG
        if self.last_on is not None and time.ticks_diff(now, self.last_on) < holdover:
            return 1
        return 0

    def update(self, now):
        raw = self.read(now)
        if raw != self.last_raw:
            self.last_raw = raw
            self.last_change = now

        if raw != self.stable and time.ticks_diff(now, self.last_change) >= DEBOUNCE_MS:
            self.stable = raw
            if raw:
                self.pressed_at = now
                self.hold_sent = False
                self.long_sent = False
                if self.on_press:
                    self.on_press()
            else:
                if self.pressed_at is not None and not self.hold_sent and self.on_short:
                    self.on_short()
                self.pressed_at = None

        if (self.on_hold and self.stable and self.pressed_at is not None
                and not self.hold_sent
                and self.held_for(now, self.hold_ms)):
            self.hold_sent = True
            self.on_hold()

        if (self.on_long and self.stable and self.pressed_at is not None
                and self.hold_sent and not self.long_sent
                and self.held_for(now, self.long_ms)):
            self.long_sent = True
            self.on_long()

    def held_for(self, now, duration_ms):
        if time.ticks_diff(now, self.pressed_at) < duration_ms:
            return False
        # Smoothing bridges gaps, but cannot prove a finger is still touching.
        # Require a real active sample at/after the threshold before emitting.
        if self.holdover_ms:
            return (self.last_on is not None
                    and time.ticks_diff(self.last_on, self.pressed_at) >= duration_ms)
        return True


touch = Input(Pin(TOUCH_PIN, Pin.IN), active_low=TOUCH_ACTIVE_LOW,
              holdover_ms=TOUCH_HOLDOVER_MS,
              on_short=lambda: emit("TAP"), on_hold=lambda: emit("HOLD"),
              on_long=lambda: emit("HOLD_LONG"))

key = Input(Pin(KEY_PIN, Pin.IN, Pin.PULL_UP), active_low=KEY_ACTIVE_LOW,
            on_press=lambda: emit("SELECT"))   # one SELECT per press, sent as it goes down


# ---- LED ---------------------------------------------------------------------
channels = []
for p in LED_PINS:
    pwm = PWM(Pin(p))
    pwm.freq(1000)
    channels.append(pwm)


def show(color):
    for pwm, value in zip(channels, color):
        duty = value * 257
        if COMMON_ANODE:
            duty = 65535 - duty
        pwm.duty_u16(duty)


class Led:
    def __init__(self):
        self.color = (0, 0, 0)
        self.blink = False
        self.lit = False
        self.last_flip = time.ticks_ms()
        self.set("idle")

    def set(self, state):
        self.color, self.blink = LED_STATES[state]
        self.lit = True
        self.last_flip = time.ticks_ms()
        show(self.color)

    def update(self, now):
        if self.blink and time.ticks_diff(now, self.last_flip) >= BLINK_MS:
            self.last_flip = now
            self.lit = not self.lit
            show(self.color if self.lit else (0, 0, 0))


led = Led()


# ---- Local mode: the LED follows taps on its own, until the bridge takes over ----
# A small copy of CONTRACT.md section 4, used only for the LED, so the device can be
# tested and demoed with no laptop software. The first valid "LED ..." command from the
# bridge switches local mode off until the next power-on, so the two never fight.
LOCAL_MODE = True             # False = the LED only ever changes on bridge commands
LOCAL_TIMEOUT_MS = 8000       # no input for this long in a menu -> back to idle
LOCAL_SENT_MS = 2000          # how long "sent" (green) shows before idle
LOCAL_ALERT_MS = 5000         # how long "alert" (red) shows before idle


class Local:
    def __init__(self):
        self.active = LOCAL_MODE
        self.state = "idle"
        self.since = time.ticks_ms()

    def go(self, state):
        self.state = state
        self.since = time.ticks_ms()
        led.set(state)

    def on_event(self, event):
        if not self.active:
            return
        s = self.state
        if event == "HOLD_LONG":
            self.go("alert")                      # direct nurse call, from any mode
        elif s == "idle":
            if event == "HOLD":
                self.go("listening")              # category mode; TAP ignored
        elif s == "listening":
            if event in ("HOLD", "SELECT"):
                self.go("phrase")                 # open the phrases
            elif event == "TAP":
                self.since = time.ticks_ms()      # next category: stay, restart the timer
        elif s == "phrase":
            if event in ("HOLD", "SELECT"):
                self.go("sent")                   # phrase chosen
            elif event == "TAP":
                self.since = time.ticks_ms()      # next phrase

    def update(self, now):
        if not self.active or self.state == "idle":
            return
        waited = time.ticks_diff(now, self.since)
        limit = {"sent": LOCAL_SENT_MS, "alert": LOCAL_ALERT_MS}.get(self.state, LOCAL_TIMEOUT_MS)
        if waited >= limit:
            self.go("idle")

    def bridge_took_over(self):
        self.active = False


local = Local()


# ---- Serial in (commands from the bridge) ------------------------------------
poller = select.poll()
poller.register(sys.stdin, select.POLLIN)
line_buf = ""


def handle_command(line):
    parts = line.split()
    if len(parts) == 2 and parts[0] == "LED" and parts[1] in LED_STATES:
        local.bridge_took_over()
        led.set(parts[1])
    elif len(parts) == 3 and parts[0] == "CFG" and parts[1] == "hold_ms":
        try:
            value = int(parts[2])
        except ValueError:
            return
        if HOLD_MS_MIN <= value <= HOLD_MS_MAX and value < HOLD_LONG_MS:
            touch.hold_ms = value
    elif len(parts) == 3 and parts[0] == "CFG" and parts[1] == "touch_holdover_ms":
        try:
            value = int(parts[2])
        except ValueError:
            return
        if TOUCH_HOLDOVER_MIN <= value <= TOUCH_HOLDOVER_MAX:
            touch.holdover_ms = value
    # Anything else is ignored: the contract says the Pico acknowledges nothing.


def read_commands():
    global line_buf
    while poller.poll(0):
        ch = sys.stdin.read(1)
        if not ch:
            break
        if ch in "\r\n":
            if line_buf:
                handle_command(line_buf.strip())
                line_buf = ""
        else:
            line_buf += ch
            if len(line_buf) > 64:     # drop garbage instead of growing forever
                line_buf = ""


# ---- Main loop ------------------------------------------------------------------
def main():
    try:
        while True:
            now = time.ticks_ms()
            touch.update(now)
            key.update(now)
            read_commands()
            local.update(now)
            led.update(now)
            time.sleep_ms(POLL_MS)
    except KeyboardInterrupt:
        show((0, 0, 0))     # Stop in Thonny turns the LED off


if __name__ == "__main__":
    main()
