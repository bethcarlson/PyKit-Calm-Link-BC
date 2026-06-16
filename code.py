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

INHALE_DURATION = 5.0
EXHALE_DURATION = 5.0
BG_INHALE = 0x5FD3FF
BG_EXHALE = 0x000000
TEXT_INHALE = (0, 0, 0)
TEXT_EXHALE = (95, 211, 255)
BG_QUESTIONS = 0xADD8E6
HEADER_QUESTIONS = 0x00008B
TEXT_QUESTIONS = (0, 0, 0)
CYCLES_BEFORE_VITALS = 2
SHAKE_THRESHOLD_HIGH = 25.0
SHAKE_THRESHOLD_LOW = 15.0

MODE_START = -1
MODE_INTAKE = 0
MODE_CALM = 1
MODE_SUMMARY = 2

MEDICAL_QUESTIONS = [
    "Known medical conditions?",
    "Any allergies?",
    "On any medications?",
    "Recent injury or fall?",
    "Feeling pain?",
]


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
        self.temp_label = None
        self.shake_label = None
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
        self.finished_vitals = False
        self.is_shaking_state = False

    def update(self):
        if self.showing_vitals:
            vitals_elapsed = time.monotonic() - self.vitals_start
            if vitals_elapsed < 5.0:
                self.display_vitals()
                return
            else:
                self.showing_vitals = False
                self.finished_vitals = True
                return

        if self.group is None:
            self.group, self.palette = self.lcd.make_group(BG_INHALE)
            self.breath_label = self.lcd.add_label(self.group, "Inhale", 120, 40, color=TEXT_INHALE, scale=3)
            self.indicator_label = self.lcd.add_label(self.group, "●", 120, 75, color=TEXT_INHALE, scale=4)
            self.calm_label = self.lcd.add_label(self.group, "Calm: 0%", 40, 100, color=TEXT_INHALE, scale=1)
            self.temp_label = self.lcd.add_label(self.group, "Temp: 0F", 140, 100, color=TEXT_INHALE, scale=1)
            self.shake_label = self.lcd.add_label(self.group, "Shake: OK", 40, 120, color=TEXT_INHALE, scale=1)
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
            
            if self.is_shaking_state:
                if avg_motion < SHAKE_THRESHOLD_LOW:
                    self.is_shaking_state = False
            else:
                if avg_motion > SHAKE_THRESHOLD_HIGH:
                    self.is_shaking_state = True
        except OSError:
            calm_percent = 50

        temp_c = self.temp.celsius
        temp_f = (temp_c * 9 / 5) + 32
        shake_status = "SHAKING" if self.is_shaking_state else "OK"

        if bg_color != self.last_bg_color:
            self.group, self.palette = self.lcd.make_group(bg_color)
            self.breath_label = self.lcd.add_label(self.group, display_state, 120, 40, color=text_color, scale=3)
            self.indicator_label = self.lcd.add_label(self.group, "●" if self.blink_visible else " ", 120, 75, color=text_color, scale=4)
            calm_text = "Calm: {}%".format(calm_percent)
            self.calm_label = self.lcd.add_label(self.group, calm_text, 40, 100, color=text_color, scale=1)
            temp_text = "Temp: {:.0f}F".format(temp_f)
            self.temp_label = self.lcd.add_label(self.group, temp_text, 140, 100, color=text_color, scale=1)
            shake_text = "Shake: " + shake_status
            self.shake_label = self.lcd.add_label(self.group, shake_text, 40, 120, color=text_color, scale=1)
            self.lcd.display.root_group = self.group
            self.last_bg_color = bg_color
        else:
            self.breath_label.text = display_state
            self.breath_label.color = text_color
            self.indicator_label.text = "●" if self.blink_visible else " "
            self.indicator_label.color = text_color
            calm_text = "Calm: {}%".format(calm_percent)
            self.calm_label.text = calm_text
            self.calm_label.color = text_color
            temp_text = "Temp: {:.0f}F".format(temp_f)
            self.temp_label.text = temp_text
            self.temp_label.color = text_color
            shake_text = "Shake: " + shake_status
            self.shake_label.text = shake_text
            self.shake_label.color = text_color

        self.lcd.display.refresh()

    def display_vitals(self):
        temp_c = self.temp.celsius
        temp_f = (temp_c * 9 / 5) + 32
        shake_status = "SHAKING" if self.is_shaking_state else "NORMAL"

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

        self.mode = MODE_START
        self.medical_answers = [None] * len(MEDICAL_QUESTIONS)
        self.current_question = 0
        self.last_question_displayed = -1
        self.last_summary_time = -1
        self.start_screen_time = time.monotonic()
        self.breathing_animator = None
        self.session_start = time.monotonic()
        self.click_count = 0
        self.last_click_time = 0
        self.last_shake_check = time.monotonic()

        print("[CALMLINK+] Ready. Single click = YES, Double click = NO.\n")

    def display_start(self):
        if self.start_image:
            self.lcd.display.root_group = self.start_image
            self.lcd.display.refresh()
        else:
            startup_group, _ = self.lcd.make_group(0x000000)
            self.lcd.add_label(startup_group, "CalmLink+", 120, 50, color=Colors.CYAN, scale=3)
            self.lcd.add_label(startup_group, "Starting...", 120, 100, color=Colors.WHITE, scale=1)
            self.lcd.display.root_group = startup_group
            self.lcd.display.refresh()

    def display_question(self):
        if self.current_question != self.last_question_displayed:
            group, _ = self.lcd.make_group(BG_QUESTIONS)
            self.lcd.add_label(group, "Medical Q's", 120, 10, color=HEADER_QUESTIONS, scale=2)
            self.lcd.add_label(group, MEDICAL_QUESTIONS[self.current_question], 120, 45, color=TEXT_QUESTIONS, scale=1)
            self.lcd.add_label(group, "1 click = YES  2 clicks = NO", 120, 110, color=TEXT_QUESTIONS, scale=1)
            self.lcd.display.root_group = group
            self.last_question_displayed = self.current_question
        self.lcd.display.refresh()

    def display_breathing(self):
        if self.breathing_animator is None:
            self.breathing_animator = BreathingAnimator(self.lcd, self.audio, self.imu, self.temp)
        self.breathing_animator.update()

    def display_summary(self):
        session_time = int(time.monotonic() - self.session_start)
        if session_time != self.last_summary_time:
            group, _ = self.lcd.make_group(0x000000)
            self.lcd.add_label(group, "SUMMARY", 120, 10, color=Colors.CYAN, scale=2)
            y = 30
            for i, question in enumerate(MEDICAL_QUESTIONS):
                ans = "YES" if self.medical_answers[i] else "NO"
                short_q = question.split("?")[0][:14]
                self.lcd.add_label(group, short_q + ": " + ans, 130, y, color=Colors.WHITE, scale=1)
                y += 13
            minutes = session_time // 60
            seconds = session_time % 60
            time_str = "{}m {}s".format(minutes, seconds)
            self.lcd.add_label(group, time_str, 130, y + 3, color=Colors.GREEN, scale=1)
            self.lcd.display.root_group = group
            self.last_summary_time = session_time
        self.lcd.display.refresh()

    def handle_button_intake(self):
        self.button.update()
        if self.mode == MODE_START:
            elapsed = time.monotonic() - self.start_screen_time
            if elapsed > 3:
                self.mode = MODE_INTAKE
                print("[START] Auto-advancing")
        if self.button.fell:
            if self.mode == MODE_START:
                self.mode = MODE_INTAKE
                print("[START] Manual skip")
                time.sleep(0.3)
                return
            self.click_count += 1
            self.last_click_time = time.monotonic()
        
        if self.click_count > 0 and time.monotonic() - self.last_click_time > 0.5:
            if self.click_count == 1:
                self.medical_answers[self.current_question] = True
                print("[INPUT] YES")
            elif self.click_count >= 2:
                self.medical_answers[self.current_question] = False
                print("[INPUT] NO")
            
            self.current_question += 1
            self.click_count = 0
            if self.current_question >= len(MEDICAL_QUESTIONS):
                self.mode = MODE_CALM
                self.session_start = time.monotonic()
                self.breathing_animator = None
                print("[INTAKE] Complete")
            time.sleep(0.3)

    def handle_button(self):
        self.button.update()
        if self.button.fell:
            if self.mode == MODE_CALM:
                self.mode = MODE_SUMMARY
                print("[SESSION] Summary")
            elif self.mode == MODE_SUMMARY:
                self.mode = MODE_START
                self.current_question = 0
                self.medical_answers = [None] * len(MEDICAL_QUESTIONS)
                self.start_screen_time = time.monotonic()
                self.click_count = 0
                self.breathing_animator = None
                print("[RESET] Restart")
            time.sleep(0.2)

    def check_shake_periodically(self):
        now = time.monotonic()
        if now - self.last_shake_check > 2.0 and self.breathing_animator is not None:
            try:
                ax, ay, az = self.imu.acceleration
                motion = abs(ax) + abs(ay) + abs(az)
                self.breathing_animator.motion_history.append(motion)
                if len(self.breathing_animator.motion_history) > 20:
                    self.breathing_animator.motion_history.pop(0)
                avg_motion = sum(self.breathing_animator.motion_history) / len(self.breathing_animator.motion_history)
                
                if self.breathing_animator.is_shaking_state:
                    if avg_motion < SHAKE_THRESHOLD_LOW:
                        self.breathing_animator.is_shaking_state = False
                else:
                    if avg_motion > SHAKE_THRESHOLD_HIGH:
                        self.breathing_animator.is_shaking_state = True
            except OSError:
                pass
            self.last_shake_check = now

    def run(self):
        while True:
            self.check_shake_periodically()
            
            if self.mode == MODE_START:
                self.display_start()
                self.handle_button_intake()
            elif self.mode == MODE_INTAKE:
                self.display_question()
                self.handle_button_intake()
            elif self.mode == MODE_CALM:
                self.handle_button()
                self.display_breathing()
            elif self.mode == MODE_SUMMARY:
                self.display_summary()
                self.handle_button()
            time.sleep(0.02)


device = CalmLink()
device.run()
