from __future__ import annotations

import json
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from smart_fan.config import DEFAULTS
from smart_fan.controller import FAN_ONLY_COMMANDS, FanController, ControllerStatus
from smart_fan.follower import FollowController, TargetObservation
from smart_fan.hardware import ServoOutput
from smart_fan.main import Application, MockServo
from smart_fan.voice import (
    EN_COMMANDS,
    GRAMMAR_EN,
    WAKE_ALIASES_EN,
    VoiceListener,
    phrase_to_command,
)


class FakeFan:
    def __init__(self):
        self.enabled = False
        self.duty_ratio = 0.0
        self.level = ""

    def set_level(self, level):
        levels = {"low": 0.70, "medium": 0.80, "high": 0.90, "max": 1.0}
        self.level = level
        return self.set_ratio(levels[level])

    def set_ratio(self, ratio):
        self.duty_ratio = ratio
        self.enabled = ratio > 0
        return ratio

    def off(self):
        self.enabled = False
        self.duty_ratio = 0.0


class FakeServo:
    def __init__(self, initial=180.0):
        self.angle = initial
        self.cfg = DEFAULTS["servo"]
        self._enabled = True

    def set_angle(self, angle):
        self.angle = max(self.cfg["min_angle"], min(self.cfg["max_angle"], angle))
        return self.angle

    def suspend(self):
        self._enabled = False

    def resume(self):
        self._enabled = True


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class TestAngleMapping(unittest.TestCase):
    def test_270_degree_mapping(self):
        servo = object.__new__(ServoOutput)
        servo.cfg = dict(DEFAULTS["servo"])
        self.assertEqual(servo.pulse_us_for_angle(0), 500)
        self.assertEqual(servo.pulse_us_for_angle(135), 1500)
        self.assertEqual(servo.pulse_us_for_angle(270), 2500)


class TestServoPowerOff(unittest.TestCase):
    def test_suspend_keeps_angle_and_disables_pwm(self):
        class FakePwm:
            def __init__(self):
                self.enabled = True
                self.duty_writes = []

            def set_duty_ns(self, duty_ns):
                self.duty_writes.append(duty_ns)

            def enable(self, on):
                self.enabled = on

            def close(self, unexport=False):
                self.enabled = False
                self.closed = True

        servo = object.__new__(ServoOutput)
        servo.cfg = dict(DEFAULTS["servo"])
        servo.angle = 220.0
        servo._enabled = True
        servo.pwm = FakePwm()

        servo.suspend()

        self.assertEqual(servo.angle, 220.0)
        self.assertFalse(servo._enabled)
        self.assertFalse(servo.pwm.enabled)
        self.assertEqual(servo.pwm.duty_writes, [])

    def test_close_keeps_angle_as_service_shuts_down(self):
        class FakePwm:
            def __init__(self):
                self.enabled = True
                self.duty_writes = []
                self.closed = False

            def set_duty_ns(self, duty_ns):
                self.duty_writes.append(duty_ns)

            def enable(self, on):
                self.enabled = on

            def close(self, unexport=False):
                self.enabled = False
                self.closed = True

        servo = object.__new__(ServoOutput)
        servo.cfg = dict(DEFAULTS["servo"])
        servo.angle = 220.0
        servo._enabled = True
        servo.pwm = FakePwm()

        servo.close()

        self.assertEqual(servo.angle, 220.0)
        self.assertFalse(servo._enabled)
        self.assertFalse(servo.pwm.enabled)
        self.assertTrue(servo.pwm.closed)
        self.assertEqual(servo.pwm.duty_writes, [])

    def test_mock_suspend_keeps_angle(self):
        servo = MockServo(dict(DEFAULTS["servo"]))
        servo.angle = 220.0

        servo.suspend()

        self.assertEqual(servo.angle, 220.0)
        self.assertFalse(servo._enabled)


class TestFollowController(unittest.TestCase):
    def test_moves_towards_target(self):
        servo = FakeServo(180)
        cfg = dict(DEFAULTS["servo"])
        cfg["invert"] = False
        follower = FollowController(cfg, servo)
        target = TargetObservation(valid=True, x=0.8, received_at=0.0)
        angle = follower.update(target, 0.1, 0.1)
        self.assertIsNotNone(angle)
        self.assertGreater(servo.angle, 180)

    def test_deadband_does_not_move(self):
        servo = FakeServo(180)
        follower = FollowController(dict(DEFAULTS["servo"]), servo)
        target = TargetObservation(valid=True, x=0.52, received_at=0.0)
        self.assertIsNone(follower.update(target, 0.1, 0.1))
        self.assertEqual(servo.angle, 180)

    def test_centers_after_loss(self):
        servo = FakeServo(220)
        follower = FollowController(dict(DEFAULTS["servo"]), servo)
        target = TargetObservation(valid=True, x=0.8, received_at=0.0)
        follower.update(target, 0.1, 0.1)
        follower.update(target, 0.2, 0.1)
        follower.update(TargetObservation(valid=False, received_at=0.3), 0.3, 0.1)
        follower.update(TargetObservation(valid=False, received_at=20.0), 20.0, 0.1)
        self.assertEqual(servo.angle, 180)


class TestController(unittest.TestCase):
    def make(self):
        cfg = {
            "vision": dict(DEFAULTS["vision"]),
            "servo": dict(DEFAULTS["servo"]),
            "fan": dict(DEFAULTS["fan"]),
            "behavior": dict(DEFAULTS["behavior"]),
        }
        clock = Clock()
        fan = FakeFan()
        servo = FakeServo()
        ctl = FanController(cfg, fan, servo, now_fn=clock)
        ctl._last_tick = 0.0
        return ctl, fan, servo, clock

    def test_fan_and_level(self):
        ctl, fan, _, _ = self.make()
        self.assertTrue(ctl.execute("fan_on"))
        self.assertTrue(fan.enabled)
        self.assertAlmostEqual(fan.duty_ratio, 0.80)
        for command, ratio in (
            ("level_low", 0.70),
            ("level_medium", 0.80),
            ("level_high", 0.90),
            ("level_max", 1.0),
        ):
            self.assertTrue(ctl.execute(command))
            self.assertAlmostEqual(fan.duty_ratio, ratio)
        ctl.execute("fan_off")
        self.assertFalse(fan.enabled)

    def test_timer_expires(self):
        ctl, fan, servo, clock = self.make()
        ctl.cfg["behavior"]["standby_after_sec"] = 700.0
        ctl.execute("fan_on")
        ctl.execute("timer_10m")
        self.assertTrue(fan.enabled)
        clock.value = 599.0
        ctl.tick(None)
        servo.angle = 220.0
        self.assertTrue(fan.enabled)
        clock.value = 601.0
        ctl._last_tick = 600.0
        ctl.tick(None)
        self.assertFalse(fan.enabled)
        self.assertEqual(servo.angle, 220.0)
        self.assertIsNone(ctl.status().timer_remaining_sec)

    def test_timer_does_not_turn_on_fan(self):
        for command, seconds in (
            ("timer_10m", 600.0),
            ("timer_half_hour", 1800.0),
            ("timer_1h", 3600.0),
        ):
            with self.subTest(command=command):
                ctl, fan, _, _ = self.make()
                self.assertTrue(ctl.execute(command))
                self.assertFalse(ctl.fan_on)
                self.assertFalse(fan.enabled)
                self.assertEqual(ctl.status().behavior_state, "off")
                self.assertEqual(ctl.status().timer_remaining_sec, seconds)

    def test_fan_off_stops_following(self):
        ctl, fan, servo, clock = self.make()
        clock.value = 0.2
        ctl._last_tick = 0.1
        ctl.tick(TargetObservation(valid=True, x=0.8, received_at=0.2, frame=1))
        clock.value = 0.5
        ctl._last_tick = 0.4
        ctl.tick(TargetObservation(valid=True, x=0.8, received_at=0.5, frame=4))
        servo.angle = 220.0
        self.assertTrue(ctl.execute("fan_off"))
        self.assertFalse(fan.enabled)
        self.assertEqual(ctl.status().behavior_state, "off")
        self.assertEqual(servo.angle, 220.0)

    def test_follow_off_keeps_current_servo_angle(self):
        ctl, _, servo, clock = self.make()
        ctl.execute("fan_on")
        servo.angle = 220
        clock.value = 1.0
        ctl._last_tick = 0.9
        self.assertTrue(ctl.execute("follow_off"))
        ctl.tick(TargetObservation(valid=True, x=0.9, received_at=1.0, frame=1))
        self.assertEqual(servo.angle, 220)
        self.assertFalse(ctl.status().follow)
        self.assertEqual(ctl.status().behavior_state, "manual")

    def test_voice_settings_wait_for_fan_on(self):
        ctl, fan, _, _ = self.make()
        for command in FAN_ONLY_COMMANDS:
            self.assertFalse(ctl.execute(command, require_fan_on=True), command)
        self.assertEqual(ctl.level, "medium")
        self.assertTrue(ctl.follow)
        self.assertFalse(fan.enabled)
        self.assertEqual(ctl.status().last_action, "风扇未开启，命令未执行")

    def test_web_or_programmatic_level_change_still_works_while_off(self):
        ctl, fan, _, _ = self.make()
        self.assertTrue(ctl.execute("level_high"))
        self.assertEqual(ctl.level, "high")
        self.assertFalse(fan.enabled)

    def test_no_person_starts_search_before_standby(self):
        ctl, fan, _, clock = self.make()
        ctl.execute("fan_on")
        clock.value = 31.0
        ctl._last_tick = 30.9
        events = ctl.tick(TargetObservation(valid=False, received_at=31.0))
        self.assertIn("search_start", events)
        self.assertEqual(ctl.status().behavior_state, "search")
        self.assertTrue(fan.enabled)

    def test_search_then_target_found(self):
        ctl, fan, servo, clock = self.make()
        ctl.execute("fan_on")
        clock.value = 6.0
        ctl._last_tick = 5.9
        events = ctl.tick(TargetObservation(valid=False, received_at=6.0))
        self.assertIn("search_start", events)
        self.assertEqual(ctl.status().behavior_state, "search")
        before = servo.angle
        clock.value = 7.0
        ctl._last_tick = 6.9
        ctl.tick(TargetObservation(valid=False, received_at=7.0))
        self.assertNotEqual(servo.angle, before)
        target = TargetObservation(valid=True, x=0.55, received_at=8.0, frame=10)
        clock.value = 8.0
        ctl._last_tick = 7.9
        ctl.tick(target)
        clock.value = 8.6
        ctl._last_tick = 8.5
        events = ctl.tick(
            TargetObservation(valid=True, x=0.55, received_at=8.6, frame=16)
        )
        self.assertIn("target_found", events)
        self.assertEqual(ctl.status().behavior_state, "follow")
        self.assertTrue(fan.enabled)

    def test_single_frame_false_positive_does_not_leave_search(self):
        ctl, fan, _, clock = self.make()
        ctl.execute("fan_on")
        clock.value = 6.0
        ctl._last_tick = 5.9
        ctl.tick(TargetObservation(valid=False, received_at=6.0))
        clock.value = 6.1
        ctl._last_tick = 6.0
        ctl.tick(TargetObservation(valid=True, x=0.7, received_at=6.1, frame=99))
        clock.value = 6.2
        ctl._last_tick = 6.1
        ctl.tick(TargetObservation(valid=False, received_at=6.2, frame=100))
        self.assertEqual(ctl.status().behavior_state, "search")
        self.assertFalse(ctl.status().target_confirmed)
        self.assertTrue(fan.enabled)

    def test_pending_target_switch_counts_as_person_presence(self):
        ctl, fan, _, clock = self.make()
        ctl.execute("fan_on")
        events = []
        for i in range(1, 61):
            clock.value = i * 0.1
            ctl._last_tick = clock.value - 0.1
            events.extend(ctl.tick(TargetObservation(
                valid=True,
                x=0.82,
                received_at=clock.value,
                frame=i,
                followable=False,
                selection={"reason": "switch_pending"},
            )))
        self.assertNotIn("search_start", events)
        self.assertEqual(ctl.status().behavior_state, "follow")
        self.assertTrue(fan.enabled)

    def test_no_person_enters_standby(self):
        ctl, fan, servo, clock = self.make()
        ctl.execute("fan_on")
        servo.angle = 220.0
        clock.value = 61.0
        ctl._last_tick = 60.9
        events = ctl.tick(TargetObservation(valid=False, received_at=61.0))
        self.assertIn("standby", events)
        self.assertEqual(ctl.status().behavior_state, "standby")
        self.assertFalse(fan.enabled)
        self.assertEqual(servo.angle, 220.0)

    def test_auto_off_switch_keeps_search_running(self):
        ctl, fan, _, clock = self.make()
        ctl.execute("fan_on")
        self.assertTrue(ctl.execute("auto_off_off"))
        clock.value = 61.0
        ctl._last_tick = 60.9
        events = ctl.tick(TargetObservation(valid=False, received_at=61.0))
        self.assertNotIn("standby", events)
        self.assertTrue(fan.enabled)
        self.assertFalse(ctl.status().auto_off_enabled)
        self.assertEqual(ctl.status().behavior_state, "search")

    def test_auto_off_switch_can_be_reenabled(self):
        ctl, fan, _, clock = self.make()
        ctl.execute("fan_on")
        ctl.execute("auto_off_off")
        self.assertTrue(ctl.execute("auto_off_on"))
        clock.value = 61.0
        ctl._last_tick = 60.9
        events = ctl.tick(TargetObservation(valid=False, received_at=61.0))
        self.assertIn("standby", events)
        self.assertFalse(fan.enabled)
        self.assertTrue(ctl.status().auto_off_enabled)

    def test_auto_off_clears_pending_timer(self):
        ctl, fan, _, clock = self.make()
        ctl.execute("fan_on")
        ctl.execute("timer_1h")

        clock.value = 61.0
        ctl._last_tick = 60.9
        events = ctl.tick(TargetObservation(valid=False, received_at=61.0))

        self.assertIn("standby", events)
        self.assertFalse(fan.enabled)
        self.assertIsNone(ctl.status().timer_remaining_sec)

    def test_target_loss_enters_search(self):
        ctl, fan, _, clock = self.make()
        ctl.execute("fan_on")
        target = TargetObservation(valid=True, x=0.5, received_at=0.0)
        ctl.tick(target)
        clock.value = 31.0
        ctl._last_tick = 30.9
        events = ctl.tick(TargetObservation(valid=False, received_at=31.0))
        self.assertIn("search_start", events)
        self.assertTrue(fan.enabled)


class TestVoiceDispatch(unittest.TestCase):
    def test_voice_fan_off_keeps_current_servo_angle(self):
        cfg = {
            "vision": dict(DEFAULTS["vision"]),
            "servo": dict(DEFAULTS["servo"]),
            "fan": dict(DEFAULTS["fan"]),
            "behavior": dict(DEFAULTS["behavior"]),
        }
        clock = Clock()
        fan = FakeFan()
        servo = FakeServo()
        controller = FanController(cfg, fan, servo, now_fn=clock)
        controller._last_tick = 0.0
        self.assertTrue(controller.execute("fan_on"))
        servo.angle = 220.0

        app = object.__new__(Application)
        app.announcement_language = "zh"
        app.controller = controller
        app.servo = servo
        app.vision = Mock()
        app.speaker = Mock()

        app._voice_command("fan_off", "zh")

        self.assertEqual(servo.angle, 220.0)
        self.assertFalse(servo._enabled)
        self.assertFalse(fan.enabled)
        app.vision.pause.assert_called_once_with()
        app.speaker.announce.assert_called_once_with("fan_off")

    def test_wake_word_and_command(self):
        commands = []
        wakes = []
        voice = VoiceListener(
            dict(DEFAULTS["voice"]),
            lambda command, language: commands.append(command),
            lambda language: wakes.append(language),
        )
        voice._handle_text("打开 风扇")
        self.assertEqual(commands, [])
        voice._handle_text("小风 小风")
        self.assertEqual(wakes, ["zh"])
        voice._handle_text("打开 风扇")
        self.assertEqual(commands, ["fan_on"])
        voice._last_trigger["zh"] -= 2.0
        voice._handle_text("小风 小风 关闭 风扇")
        self.assertEqual(commands, ["fan_on", "fan_off"])

    def test_playback_blocks_microphone_results(self):
        commands = []
        wakes = []
        blocked = True
        voice = VoiceListener(
            dict(DEFAULTS["voice"]),
            lambda command, language: commands.append(command),
            lambda language: wakes.append(language),
            playback_active=lambda: blocked,
        )
        voice._handle_text("小风 小风 打开 风扇", peak=4000, rms=800, active_sec=1.5)
        self.assertEqual(commands, [])
        self.assertEqual(wakes, [])

    def test_low_level_and_short_results_are_ignored(self):
        commands = []
        voice = VoiceListener(
            dict(DEFAULTS["voice"]),
            lambda command, language: commands.append(command),
        )
        voice._handle_text("小风 小风 打开 风扇", peak=300, rms=80, active_sec=1.0)
        voice._handle_text("小风 小风 打开 风扇", peak=4000, rms=800, active_sec=0.1)
        self.assertEqual(commands, [])
        voice._handle_text("小风 小风 打开 风扇", peak=4000, rms=800, active_sec=1.0)
        self.assertEqual(commands, ["fan_on"])

    def test_english_wake_and_command(self):
        commands = []
        wakes = []
        voice = VoiceListener(
            dict(DEFAULTS["voice"]),
            lambda command, language: commands.append((language, command)),
            lambda language: wakes.append(language),
        )
        voice._handle_text(
            "hey fan", language="en", peak=4000, rms=800, active_sec=0.8
        )
        self.assertEqual(wakes, ["en"])
        voice._handle_text(
            "level two", language="en", peak=4000, rms=800, active_sec=1.0
        )
        self.assertEqual(commands, [("en", "level_medium")])

    def test_full_english_wake_and_natural_aliases(self):
        commands = []
        wakes = []
        voice = VoiceListener(
            dict(DEFAULTS["voice"]),
            lambda command, language: commands.append((language, command)),
            lambda language: wakes.append(language),
        )
        voice._handle_text("hi fan", language="en", peak=900, rms=300, active_sec=0.25)
        self.assertEqual(wakes, ["en"])
        voice._handle_text("hey", language="en", peak=1400, rms=500, active_sec=0.4)
        self.assertEqual(wakes, ["en"])
        voice._handle_text(
            "hello fan", language="en", peak=1100, rms=500, active_sec=0.8
        )
        self.assertEqual(wakes, ["en", "en"])
        voice._handle_text(
            "turn off auto shutdown", language="en", peak=700, rms=300, active_sec=1.0
        )
        self.assertEqual(commands, [("en", "auto_off_off")])

    def test_english_truncated_results_are_still_usable(self):
        self.assertEqual(phrase_to_command("hello fan on", "en"), "fan_on")
        self.assertEqual(phrase_to_command("hey fan turn on", "en"), "fan_on")
        self.assertEqual(phrase_to_command("hello fan off", "en"), "fan_off")
        self.assertEqual(phrase_to_command("hi fans level three", "en"), "level_high")
        self.assertEqual(
            phrase_to_command("hey fan turn on an the fan", "en"), "fan_on"
        )
        self.assertEqual(phrase_to_command("fan half", "en"), "fan_off")
        self.assertIsNone(phrase_to_command("turn half", "en"))
        self.assertIsNone(phrase_to_command("hello fan switch", "en"))

    def test_partial_dispatch_waits_for_timer_phrase_suffix(self):
        voice = VoiceListener(
            dict(DEFAULTS["voice"]),
            lambda command, language: None,
        )
        self.assertFalse(voice._partial_is_safe("hey fan turn off the fan", "en"))
        self.assertFalse(voice._partial_is_safe("hey fan turn the fan off", "en"))
        self.assertTrue(
            voice._partial_is_safe(
                "hey fan turn off the fan in ten minutes", "en"
            )
        )
        self.assertFalse(voice._partial_is_safe("hey fan", "en"))

    def test_english_grammar_contains_wake_and_command_aliases(self):
        self.assertIn("hello fans", WAKE_ALIASES_EN)
        self.assertIn("hey fan turn on", GRAMMAR_EN)
        self.assertIn("hello fan on", GRAMMAR_EN)
        self.assertIn("hi fan timer thirty minutes", GRAMMAR_EN)

    def test_unrecognized_speech_gets_feedback_and_extends_wake_window(self):
        feedback = []
        cfg = dict(DEFAULTS["voice"])
        cfg["wake_timeout_sec_en"] = 1.0
        cfg["wake_retry_sec_en"] = 4.0
        voice = VoiceListener(
            cfg,
            lambda command, language: None,
            on_unrecognized=lambda language: feedback.append(language),
        )
        voice._handle_text("hello fan", language="en", peak=1200, active_sec=0.8)
        before = voice._wake_until["en"]
        voice._handle_text("something unclear", language="en", peak=1200, active_sec=1.0)
        self.assertEqual(feedback, ["en"])
        self.assertGreater(voice._wake_until["en"], before)

    def test_status_reports_english_awake_state(self):
        voice = VoiceListener(
            dict(DEFAULTS["voice"]),
            lambda command, language: None,
        )
        voice._handle_text("hello fan", language="en", peak=1200, active_sec=0.8)
        status = voice.status()
        self.assertTrue(status["awake"])
        self.assertEqual(status["awake_language"], "en")
        self.assertGreater(status["wake_remaining_sec"], 0)

    def test_english_wake_acknowledgement_is_enabled_by_default(self):
        self.assertTrue(DEFAULTS["voice"]["announce_wake_en"])
        app = object.__new__(Application)
        app.cfg = {"voice": dict(DEFAULTS["voice"])}
        app.speaker = Mock()
        app._voice_wake("en")
        app.speaker.announce.assert_called_once_with("wake_en", replace=True)

    def test_unrecognized_callback_uses_english_phrase(self):
        app = object.__new__(Application)
        app.announcement_language = "zh"
        app.speaker = Mock()
        app._voice_unrecognized("en")
        self.assertEqual(app.announcement_language, "en")
        app.speaker.announce.assert_called_once_with("unrecognized_en")

    def test_voice_timers_require_fan_on_and_prompt_first(self):
        for command in ("timer_10m", "timer_half_hour", "timer_1h"):
            with self.subTest(command=command):
                app = object.__new__(Application)
                app.controller = Mock()
                app.controller.execute.return_value = False
                app.speaker = Mock()
                app._apply_output_state = Mock()

                app._voice_command(command, "zh")

                app.controller.execute.assert_called_once_with(
                    command, require_fan_on=True
                )
                app.speaker.announce.assert_called_once_with("fan_off_required")
                app._apply_output_state.assert_not_called()

    def test_english_timer_requires_fan_on_and_prompts_first(self):
        app = object.__new__(Application)
        app.controller = Mock()
        app.controller.execute.return_value = False
        app.speaker = Mock()
        app._apply_output_state = Mock()

        app._voice_command("timer_10m", "en")

        app.controller.execute.assert_called_once_with("timer_10m", require_fan_on=True)
        app.speaker.announce.assert_called_once_with("fan_off_required_en")
        app._apply_output_state.assert_not_called()

    def test_fan_only_command_gets_off_state_prompt(self):
        app = object.__new__(Application)
        app.controller = Mock()
        app.controller.execute.return_value = False
        app.speaker = Mock()
        app._apply_output_state = Mock()

        app._voice_command("level_high")

        app.controller.execute.assert_called_once_with("level_high", require_fan_on=True)
        app.speaker.announce.assert_called_once_with("fan_off_required")
        app._apply_output_state.assert_not_called()

    def test_english_fan_only_command_uses_english_prompt(self):
        app = object.__new__(Application)
        app.controller = Mock()
        app.controller.execute.return_value = False
        app.speaker = Mock()
        app._apply_output_state = Mock()

        app._voice_command("follow_off", "en")

        app.speaker.announce.assert_called_once_with("fan_off_required_en")
        app._apply_output_state.assert_not_called()

    def test_english_wake_is_silent_but_chinese_wake_speaks(self):
        app = object.__new__(Application)
        app.cfg = {"voice": {"announce_wake_en": False}}
        app.speaker = Mock()

        app._voice_wake("en")
        app.speaker.announce.assert_not_called()

        app._voice_wake("zh")
        app.speaker.announce.assert_called_once_with("wake", replace=True)

    def test_auto_off_web_command_is_silent(self):
        app = object.__new__(Application)
        app.controller = Mock()
        app.controller.execute.return_value = True
        app.controller.status.return_value = ControllerStatus(
            last_action="无人自动关机已关闭"
        )
        app.speaker = Mock()
        app._apply_output_state = Mock()

        ok, message, code = app._web_command("auto_off_off")

        self.assertTrue(ok)
        self.assertEqual(message, "无人自动关机已关闭")
        self.assertEqual(code, "")
        app.speaker.announce.assert_not_called()

    def test_web_success_uses_selected_language(self):
        app = object.__new__(Application)
        app.controller = Mock()
        app.controller.execute.return_value = True
        app.controller.status.return_value = ControllerStatus(last_action="风扇已打开")
        app.speaker = Mock()
        app._apply_output_state = Mock()

        ok, message, code = app._web_command("fan_on", "en")

        self.assertTrue(ok)
        self.assertEqual(message, "风扇已打开")
        self.assertEqual(code, "")
        self.assertEqual(app.announcement_language, "en")
        app.speaker.announce.assert_called_once_with("fan_on_en")

    def test_web_level_command_requires_fan_on(self):
        app = object.__new__(Application)
        app.controller = Mock()
        app.controller.execute.return_value = False
        app.speaker = Mock()

        ok, message, code = app._web_command("level_high", "en", True)

        self.assertFalse(ok)
        self.assertEqual(code, "fan_required")
        self.assertEqual(message, "The fan is off. Please turn it on first.")
        app.controller.execute.assert_called_once_with("level_high", require_fan_on=True)
        app.speaker.announce.assert_called_once_with("fan_off_required_en")

    def test_startup_failure_still_runs_shutdown(self):
        app = object.__new__(Application)
        app.cfg = {"device": {"name": "test"}}
        app.controller = Mock()
        app.controller.fan_on = False
        app.speaker = Mock()
        app.vision = Mock()
        app.voice = Mock()
        app.web = Mock()
        app.web.start.side_effect = OSError("port in use")
        app.shutdown = Mock()

        with self.assertRaises(OSError):
            app.run()

        app.shutdown.assert_called_once_with()



class FakeVoskLib:
    def __init__(self, partial: str, result: str = "") -> None:
        self.partial = partial
        self.result = result
        self.resets = 0

    def vosk_recognizer_accept_waveform(self, _recognizer, _pcm, _length):
        return 0

    def vosk_recognizer_partial_result(self, _recognizer):
        return json.dumps({"text": self.partial}).encode()

    def vosk_recognizer_result(self, _recognizer):
        return json.dumps({"text": self.result}).encode()

    def vosk_recognizer_reset(self, _recognizer):
        self.resets += 1


class TestVoiceEndpointing(unittest.TestCase):
    @staticmethod
    def pcm(level: int = 1200) -> bytes:
        return struct.pack("<3200h", *([level] * 3200))

    def test_complete_english_command_is_dispatched_from_stable_partial(self):
        commands = []
        voice = VoiceListener(
            dict(DEFAULTS["voice"]),
            lambda command, language: commands.append((language, command)),
        )
        fake = FakeVoskLib("hey fan turn on the fan")
        voice._lib = fake
        voice._recognizers = {"en": 1}

        voice._accept(self.pcm())
        self.assertEqual(commands, [])
        voice._accept(self.pcm())

        self.assertEqual(commands, [("en", "fan_on")])
        self.assertEqual(voice._endpoint_reason, "partial")
        self.assertGreaterEqual(fake.resets, 1)

    def test_long_running_result_is_forced_before_vosk_endpoint(self):
        commands = []
        cfg = dict(DEFAULTS["voice"])
        cfg["partial_confirm_chunks"] = 100
        cfg["max_utterance_sec"] = 0.5
        voice = VoiceListener(
            cfg,
            lambda command, language: commands.append((language, command)),
        )
        fake = FakeVoskLib("hello fan switch", "hello fan on")
        voice._lib = fake
        voice._recognizers = {"en": 1}

        for _ in range(3):
            voice._accept(self.pcm())

        self.assertEqual(commands, [("en", "fan_on")])
        self.assertEqual(voice._endpoint_reason, "max_duration")
        self.assertGreaterEqual(fake.resets, 1)

class TestVoicePhrases(unittest.TestCase):
    def test_every_english_alias_accepts_wake_prefix(self):
        for phrase, command in EN_COMMANDS.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(phrase_to_command(phrase, "en"), command)
                self.assertEqual(
                    phrase_to_command(f"Hey Fan, {phrase}.", "en"), command
                )

    def test_english_natural_timer_phrases(self):
        self.assertEqual(
            phrase_to_command("Hey Fan, turn off the fan in ten minutes.", "en"),
            "timer_10m",
        )
        self.assertEqual(
            phrase_to_command("Hey Fan, set a timer for half an hour.", "en"),
            "timer_half_hour",
        )
        self.assertEqual(
            phrase_to_command("Hello Fan, shut the fan off after an hour.", "en"),
            "timer_1h",
        )
        self.assertEqual(
            phrase_to_command("Hey Fan, turn off fan in half an hour.", "en"),
            "timer_half_hour",
        )

    def test_english_parser_tolerates_vosk_fillers_and_word_order(self):
        self.assertEqual(
            phrase_to_command(
                "hey fan in turn off the fan the half an hour", "en"
            ),
            "timer_half_hour",
        )
        self.assertEqual(
            phrase_to_command("hey fan the fan off in ten minutes", "en"),
            "timer_10m",
        )
        self.assertEqual(
            phrase_to_command("hey fan in turn off the fan", "en"), "fan_off"
        )
        self.assertEqual(
            phrase_to_command("hey fan fan speed is three", "en"), "level_high"
        )

    def test_commands(self):
        self.assertEqual(phrase_to_command("小风 小风 打开 风扇"), "fan_on")
        self.assertEqual(phrase_to_command("关闭 风扇"), "fan_off")
        self.assertEqual(phrase_to_command("小风小风三档"), "level_high")
        self.assertEqual(phrase_to_command("小风小风四档"), "level_max")
        self.assertEqual(phrase_to_command("小风 小风 定时 十分钟"), "timer_10m")
        self.assertEqual(phrase_to_command("小风小风定时十分钟后关闭"), "timer_10m")
        self.assertEqual(phrase_to_command("小风小风定时半小时后关闭"), "timer_half_hour")
        self.assertEqual(phrase_to_command("小风小风定时一小时后关闭"), "timer_1h")
        self.assertEqual(phrase_to_command("小风 小风 开启 自动 关机"), "auto_off_on")
        self.assertEqual(phrase_to_command("小风 小风 打开 自动 关机"), "auto_off_on")
        self.assertEqual(phrase_to_command("小风小风关闭自动关机"), "auto_off_off")
        self.assertEqual(phrase_to_command("停止自动关机"), "auto_off_off")
        self.assertEqual(phrase_to_command("hey fan level three", "en"), "level_high")
        self.assertEqual(phrase_to_command("disable auto shutdown", "en"), "auto_off_off")
        self.assertEqual(phrase_to_command("hello fan turn on the fan", "en"), "fan_on")
        self.assertEqual(phrase_to_command("hey fan stop tracking", "en"), "follow_off")
        self.assertEqual(phrase_to_command("okay fan switch on the fan", "en"), "fan_on")
        self.assertEqual(phrase_to_command("hello fan on", "en"), "fan_on")
        self.assertIsNone(phrase_to_command("hey fan switch", "en"))
        self.assertIsNone(phrase_to_command("今天天气不错"))


if __name__ == "__main__":
    unittest.main()
