import sys


def test_windows_runner_is_on_windows():
    assert sys.platform == "win32"
