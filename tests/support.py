"""Shared helpers for platform dependent tests."""
import os
import tempfile
import unittest

POSIX = os.name == "posix"


def _can_symlink() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.symlink(os.path.join(tmp, "target"), os.path.join(tmp, "link"))
        except (OSError, NotImplementedError):
            return False
    return True


CAN_SYMLINK = _can_symlink()

needs_symlinks = unittest.skipUnless(
    CAN_SYMLINK, "creating symlinks is not permitted here (Windows without developer mode)")
needs_posix_modes = unittest.skipUnless(
    POSIX, "Unix permission bits are not meaningful on Windows (chmod only sets read-only)")


def assert_mode(test, path, mode):
    """Assert Unix permission bits of path; a no-op where they do not exist."""
    if POSIX:
        test.assertEqual(path.stat().st_mode & 0o777, mode)
