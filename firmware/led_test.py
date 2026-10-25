# led_test.py - Friday night task 3
# Steps the LED through idle, listening, phrase, sent and alert.
# Done when all five states show on the module.
#
# Set up for the HW-479 / KY-016 RGB module (4 pins: R, G, B, -),
# which has its own 150 ohm resistors (marked 151), so no extra resistors.
#
# Wiring (Pico lying sideways, USB on the left; pins counted on the TOP edge from the right):
#   R -> GP16 (pin 21, 1st pin from the right)
#   G -> GP17 (pin 22, 2nd from the right)
#   B -> GP18 (pin 24, 4th from the right; the 3rd is GND, skip it)
#   - -> blue GND rail (the rail must have one wire to any Pico GND pin)

from machine import Pin, PWM
import time

LED_TYPE = "rgb"        # "rgb" for your 4-pin module, "neopixel" for a 3-pin VCC/GND/DIN module

# Plain RGB settings
RGB_PINS = (16, 17, 18)  # R, G, B
COMMON_ANODE = False     # your module's 4th pin is "-", so leave this False

# NeoPixel settings (only used if LED_TYPE = "neopixel")
NEO_PIN = 16
NUM_LEDS = 1
NEO_BRIGHTNESS = 0.25    # addressable LEDs are very bright; this scales them down

# Each state has a colour and a pattern, so the states can be told apart
# even by someone who can't tell colours apart. Values are 0-255 per colour.
STATES = [
    ("idle",      (0, 0, 60),     "solid"),   # dim blue
    ("listening", (0, 255, 255),  "solid"),   # cyan
    ("phrase",    (255, 70, 0),   "solid"),   # amber / orange
    ("sent",      (0, 255, 0),    "solid"),   # green
    ("alert",     (255, 0, 0),    "blink"),   # blinking red
]

if LED_TYPE == "neopixel":
    import neopixel
    strip = neopixel.NeoPixel(Pin(NEO_PIN), NUM_LEDS)

    def show(color):
        scaled = tuple(int(c * NEO_BRIGHTNESS) for c in color)
        for i in range(NUM_LEDS):
            strip[i] = scaled
        strip.write()
else:
    channels = []
    for p in RGB_PINS:
        pwm = PWM(Pin(p))
        pwm.freq(1000)
        channels.append(pwm)

    def show(color):
        for pwm, value in zip(channels, color):
            duty = value * 257                # 0-255 -> 0-65535
            if COMMON_ANODE:
                duty = 65535 - duty
            pwm.duty_u16(duty)


def play(color, pattern, seconds=2):
    if pattern == "blink":
        end = time.ticks_add(time.ticks_ms(), seconds * 1000)
        while time.ticks_diff(end, time.ticks_ms()) > 0:
            show(color)
            time.sleep_ms(250)
            show((0, 0, 0))
            time.sleep_ms(250)
    else:
        show(color)
        time.sleep(seconds)


# Wiring check first: each colour on its own for 1 second.
# If the wrong colour lights up, two wires are swapped.
print("wiring check: red, green, blue")
for name, color in (("red", (255, 0, 0)), ("green", (0, 255, 0)), ("blue", (0, 0, 255))):
    print("  should be", name)
    show(color)
    time.sleep(1)
show((0, 0, 0))
time.sleep_ms(500)

print("led_test: stepping through", len(STATES), "states")
for name, color, pattern in STATES:
    print("LED:", name)
    play(color, pattern)

show((0, 0, 0))
print("led_test done")
