import pykit_explorer
import time
import board
import displayio
import math

from lcd_display import LCDDisplay, Colors
from digital_io import EdgeDetector
from neopixels import NeoPixels
from imu_sensor import IMUSensor
from cpu_temp import CPUTemperature
from audio_out import AudioOutput

SCREEN_WIDTH, SCREEN_HEIGHT = 240, 135
BREATHE_INTERVAL, BREATHE_PHASES = 2.5, 4

RED = (255, 0, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)
GREEN = (0, 200, 50)

INHALE_DURATION = 5.0
EXHALE_DURATION = 5.0
BG_INHALE = 0x5FD3FF
BG_EXHALE = 0x000000
TEXT_INHALE = (0, 0, 0)
TEXT_EXHALE = (95, 211, 255)
CYCLES_BEFORE_VITALS = 4


class BreathingAnimator:
    def __init__(self, lcd, audio, imu, temp):
        self.lcd = lcd
        self.audio = audio
        self.imu = imu
        self.temp = temp
        self.group = None
        self.breath_label = None
        self.indicator_label = None
        self.calm_label = None
        self.cycle_start = time.monotonic()
        self.total_cycle = INHALE_DURATION + EXHALE_DURATION
        self.last_audio_state = None
        self.last_bg_color = None
        self.blink_time = 0
        self.blink_visible = True
        self.cycle_count = 0
        self.showing_vitals = False
        self.vitals_start = 0
        self.motion_history = []

    def update(self):
        if self.showing_vitals:
            vitals_elapsed = time.monotonic() - self.vitals_start
            if vitals_elapsed < 5.0:
                self.display_vitals()
                return
            else:
                self.showing_vitals = False
                self.cycle_count = 0
                self.cycle_start = time.monotonic()

        if self.group is None:
            self.group, self.palette = self.lcd.make_group(BG_INHALE)
            self.breath_label = self.lcd.add_label(self.group, "Inhale", 120, 50, color=TEXT_INHALE, scale=3)
            self.indicator_label = self.lcd.add_label(self.group, "●", 120, 90, color=TEXT_INHALE, scale=5)
            self.calm_label = self.lcd.add_label(self.group, "Calm: 0%", 120, 120, color=TEXT_INHALE, scale=1)
            self.last_bg_color = BG_INHALE

        elapsed = time.monotonic() - self.cycle_start
        cycle_position = elapsed % self.total_cycle

        complete_cycles = int(elapsed / self.total_cycle)
        if complete_cycles > self.cycle_count:
            self.cycle_count = complete_cycles
            if self.cycle_count >= CYCLES_BEFORE_VITALS:
                self.showing_vitals = True
                self.vitals_start = time.monotonic()
                return

        if cycle_position < INHALE_DURATION:
            current_state = "INHALE"
        else:
            current_state = "EXHALE"

        time_to_next_transition = self.total_cycle - cycle_position if cycle_position >= INHALE_DURATION else INHALE_DURATION - cycle_position

        if time_to_next_transition <= 1.0:
            if cycle_position < INHALE_DURATION:
                display_state = "Exhale"
                bg_color = BG_EXHALE
                text_color = TEXT_EXHALE
            else:
                display_state = "Inhale"
                bg_color = BG_INHALE
                text_color = TEXT_INHALE
        else:
            if cycle_position < INHALE_DURATION:
                display_state = "Inhale"
                bg_color = BG_INHALE
                text_color = TEXT_INHALE
            else:
                display_state = "Exhale"
                bg_color = BG_EXHALE
                text_color = TEXT_EXHALE

        if current_state != self.last_audio_state:
            if current_state == "INHALE":
                self.audio.play_wav("/AudioFiles/Breathe In.wav")
            else:
                self.audio.play_wav("/AudioFiles/Breathe Out.wav")
            self.last_audio_state = current_state
            self.blink_time = time.monotonic()

        blink_elapsed = time.monotonic() - self.blink_time
        if blink_elapsed < 0.5:
            self.blink_visible = (int(blink_elapsed * 10) % 2 == 0)
        else:
            self.blink_visible = True

        try:
            ax, ay, az = self.imu.acceleration
            motion = abs(ax) + abs(ay) + abs(az)
            self.motion_history.append(motion)
            if len(self.motion_history) > 20:
                self.motion_history.pop(0)
            avg_motion = sum(self.motion_history) / len(self.motion_history)
            calm_percent = max(0, min(100, int(100 - avg_motion * 2)))
        except OSError:
            calm_percent = 50
        if bg_color != self.last_bg_color:
            self.group, self.palette = self.lcd.make_group(bg_color)
            self.breath_label = self.lcd.add_label(self.group, display_state, 120, 50, color=text_color, scale=3)
            self.indicator_label = self.lcd.add_label(self.group, "●" if self.blink_visible else " ", 120, 90, color=text_color, scale=5)
            calm_text = "Calm: {}%".format(calm_percent)
            self.calm_label = self.lcd.add_label(self.group, calm_text, 120, 120, color=text_color, scale=1)
            self.lcd.display.root_group = self.group
            self.last_bg_color = bg_color
        else:
            self.breath_label.text = display_state
            self.breath_label.color = text_color
            self.indicator_label.text = "●" if self.blink_visible else " "
            calm_text = "Calm: {}%".format(calm_percent)
            self.calm_label.text = calm_text
            self.calm_label.color = text_color
            self.indicator_label.color = text_color

        self.lcd.display.refresh()
    def display_vitals(self):
        temp_c = self.temp.celsius
        temp_f = (temp_c * 9 / 5) + 32
        is_shaking = self.imu.is_shaking(threshold=12.0)
        shake_status = "SHAKING" if is_shaking else "NORMAL"

        if self.group is None or self.last_bg_color != 0x000000:
            self.group, self.palette = self.lcd.make_group(0x000000)
            self.lcd.add_label(self.group, "VITALS", 120, 20, color=Colors.WHITE, scale=2)
            temp_str = "Temp: {:.1f}F".format(temp_f)
            self.lcd.add_label(self.group, temp_str, 120, 55, color=Colors.CYAN, scale=2)
            status_str = "Status: " + shake_status
            self.lcd.add_label(self.group, status_str, 120, 95, color=Colors.CYAN, scale=2)
            self.lcd.display.root_group = self.group
            self.last_bg_color = 0x000000

        self.lcd.display.refresh()


class CalmLink:
    def __init__(self):
        print("\n=== CALMLINK+ INITIALIZING ===\n")
        self.lcd = LCDDisplay()
        self.lcd.backlight_on()
        self.button = EdgeDetector(board.D3)
        self.audio = AudioOutput()
        self.px = NeoPixels()
        self.temp = CPUTemperature()

        try:
            self.imu = IMUSensor()
            self.imu_available = True
            print("[IMU] Connected")
        except Exception as e:
            print("[IMU] NOT CONNECTED: {}".format(e))
            self.imu = None
            self.imu_available = False

        self.start_image = None
        try:
            self.start_image = self.lcd.load_sprite("/Images/Start.bmp")
            print("[Image] Loaded Start.bmp")
        except Exception as e:
            print("[Image] FAILED: {}".format(e))

        self.breathing_animator = None
        self.breathing_active = False
        self.session_start = time.monotonic()

        print("[CALMLINK+] Ready. Press D3 to start breathing.\n")

    def display_startup(self):
        if self.start_image:
            self.lcd.display.root_group = self.start_image
            self.lcd.display.refresh()
        else:
            startup_group, _ = self.lcd.make_group(0x000000)
            self.lcd.add_label(startup_group, "CalmLink+", 120, 50, color=Colors.CYAN, scale=3)
            self.lcd.add_label(startup_group, "Press D3", 120, 100, color=Colors.WHITE, scale=1)
            self.lcd.display.root_group = startup_group
            self.lcd.display.refresh()

    def display_breathing(self):
        if self.breathing_animator is None:
            self.breathing_animator = BreathingAnimator(self.lcd, self.audio, self.imu, self.temp)
        self.breathing_animator.update()

    def handle_button(self):
        self.button.update()
        if self.button.fell:
            self.breathing_active = not self.breathing_active
            if self.breathing_active:
                self.breathing_animator = None
                print("\n[BREATHING] Started\n")
            else:
                print("\n[BREATHING] Stopped\n")
            time.sleep(0.2)

    def run(self):
        while True:
            self.handle_button()

            if self.breathing_active:
                self.display_breathing()
            else:
                self.display_startup()

            time.sleep(0.02)


device = CalmLink()
device.run()
