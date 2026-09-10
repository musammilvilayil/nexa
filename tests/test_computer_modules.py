import sys
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from computer.contracts import ScreenshotResult, WindowInfo, Point, ActionResult, MouseButton, FailsafeTriggered, FailsafeMonitor
from computer.screen import ScreenCapture
from computer.mouse import MouseController
from computer.keyboard import KeyboardController
from computer.clipboard import ClipboardManager
from computer.window import WindowManager

class DummyFailsafe:
    def check_before_action(self, **kwargs):
        if kwargs.get('mouse_x') == 9999:
            raise FailsafeTriggered("Mouse failsafe")
        if kwargs.get('trigger_keyboard'):
            raise FailsafeTriggered("Keyboard failsafe")

class TestComputerModules(unittest.TestCase):
    
    def test_screenshot_result_dataclass(self):
        sr = ScreenshotResult(image_bytes=b"123", width=10, height=10)
        self.assertEqual(sr.width, 10)
        self.assertEqual(sr.format, "png")
    
    def test_window_info_dataclass(self):
        wi = WindowInfo(handle=1, title="Test")
        self.assertEqual(wi.title, "Test")
        self.assertEqual(wi.is_visible, True)
        
    def test_point_dataclass(self):
        p = Point(x=1, y=2)
        self.assertEqual(p.x, 1)
        self.assertEqual(p.y, 2)
        
    def test_action_result_dataclass(self):
        ar = ActionResult(success=True, message="OK")
        self.assertTrue(ar.success)
        self.assertEqual(ar.message, "OK")
        
    def test_screen_capture_requires_mss(self):
        sc = ScreenCapture()
        with patch.dict('sys.modules', {'mss': None}):
            with self.assertRaises(RuntimeError):
                sc._get_mss()
                
    def test_mouse_failsafe_check(self):
        fs = DummyFailsafe()
        mc = MouseController(failsafe=fs)
        with patch.object(mc, '_get_controller', return_value=MagicMock()):
            with self.assertRaises(FailsafeTriggered):
                mc.move_to(9999, 0)
                
    def test_mouse_click_calls_failsafe(self):
        fs = MagicMock()
        mc = MouseController(failsafe=fs)
        
        # Mock pynput out entirely
        mc._get_controller = MagicMock()
        mc._pynput_mouse = MagicMock()
        
        mc.click(10, 20)
        fs.check_before_action.assert_called_with(mouse_x=10, mouse_y=20)
        
    def test_keyboard_failsafe_check(self):
        fs = MagicMock()
        fs.check_before_action.side_effect = FailsafeTriggered("Kbd failsafe")
        kc = KeyboardController(failsafe=fs)
        
        with patch.object(kc, '_get_controller', return_value=MagicMock()):
            with self.assertRaises(FailsafeTriggered):
                kc.press("enter")
                
    def test_keyboard_secret_protection(self):
        kc = KeyboardController()
        with self.assertRaises(ValueError):
            kc.type_text("MY_SECRET_KEY123")
            
    @patch('sys.platform', 'win32')
    def test_clipboard_manager_creation(self):
        try:
            cm = ClipboardManager()
        except RuntimeError as e:
            self.fail(f"Creation failed: {e}")
            
    @patch('sys.platform', 'win32')
    def test_window_manager_creation(self):
        try:
            wm = WindowManager()
        except RuntimeError as e:
            self.fail(f"Creation failed: {e}")
            
    def test_mouse_button_enum(self):
        self.assertEqual(MouseButton.LEFT.value, "left")
        self.assertEqual(MouseButton.RIGHT.value, "right")
        self.assertEqual(MouseButton.MIDDLE.value, "middle")

if __name__ == '__main__':
    unittest.main()
