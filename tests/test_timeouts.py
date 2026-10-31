import time
import unittest

from api.timeouts import attempt_deadline, request_timeout


class RequestTimeoutTest(unittest.TestCase):
    def test_defaults_without_deadline(self) -> None:
        self.assertEqual(request_timeout(), (5.0, 90.0))

    def test_read_timeout_shrinks_to_remaining_budget(self) -> None:
        with attempt_deadline(time.monotonic() + 30):
            connect_timeout, read_timeout = request_timeout()

        self.assertEqual(connect_timeout, 5.0)
        self.assertAlmostEqual(read_timeout, 30.0, places=1)

    def test_connect_timeout_shrinks_with_short_budget(self) -> None:
        with attempt_deadline(time.monotonic() + 2):
            connect_timeout, read_timeout = request_timeout()

        self.assertAlmostEqual(connect_timeout, 2.0, places=1)
        self.assertAlmostEqual(read_timeout, 2.0, places=1)

    def test_expired_deadline_uses_minimum(self) -> None:
        with attempt_deadline(time.monotonic() - 10):
            self.assertEqual(request_timeout(), (1.0, 1.0))

    def test_deadline_is_cleared_after_context_exit(self) -> None:
        with attempt_deadline(time.monotonic() + 10):
            self.assertNotEqual(request_timeout(), (5.0, 90.0))

        self.assertEqual(request_timeout(), (5.0, 90.0))


if __name__ == "__main__":
    unittest.main()
