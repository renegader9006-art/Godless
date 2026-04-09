import unittest
from pathlib import Path
from threading import Barrier, Thread
from unittest.mock import patch
from uuid import uuid4

from seo_ai_analyzer.billing import (
    ACTION_URL_AUDIT,
    cancel_checkout_order,
    check_and_consume,
    confirm_checkout_order,
    create_checkout_order,
    get_usage,
    has_active_subscription,
    init_billing_db,
    list_checkout_orders,
    set_subscription,
)


class BillingTests(unittest.TestCase):
    def _db_path(self) -> Path:
        root = Path("tests/.tmp_billing")
        root.mkdir(parents=True, exist_ok=True)
        return root / f"{uuid4().hex}.db"

    def test_demo_checkout_and_activation(self) -> None:
        db_path = self._db_path()
        init_billing_db(db_path)
        with patch.dict("os.environ", {"PAYMENT_PROVIDER": "demo"}, clear=False):
            ok, payload = create_checkout_order("user_01", "starter", path=db_path)
            self.assertTrue(ok)
            order = dict(payload)
            self.assertEqual(order["status"], "pending")
            self.assertEqual(order["provider"], "demo")

            ok, message = confirm_checkout_order("user_01", order["order_id"], path=db_path)
            self.assertTrue(ok)
            self.assertTrue(isinstance(message, str) and len(message) > 0)
            self.assertTrue(has_active_subscription("user_01", path=db_path))

    def test_payment_links_require_env(self) -> None:
        db_path = self._db_path()
        init_billing_db(db_path)
        with patch.dict("os.environ", {"PAYMENT_PROVIDER": "payment_links"}, clear=False):
            ok, payload = create_checkout_order("user_02", "starter", path=db_path)
            self.assertFalse(ok)
            self.assertIn("env", str(payload).lower())

    def test_payment_links_checkout_url(self) -> None:
        db_path = self._db_path()
        init_billing_db(db_path)
        with patch.dict(
            "os.environ",
            {
                "PAYMENT_PROVIDER": "payment_links",
                "PAYMENT_LINK_STARTER": "https://pay.example/starter",
                "PAYMENT_LINK_GROWTH": "https://pay.example/growth",
                "PAYMENT_LINK_PRO": "https://pay.example/pro",
                "PAYMENT_LINK_AGENCY": "https://pay.example/agency",
            },
            clear=False,
        ):
            ok, payload = create_checkout_order("user_03", "pro", path=db_path)
            self.assertTrue(ok)
            order = dict(payload)
            self.assertEqual(order["provider"], "payment_links")
            self.assertEqual(order["checkout_url"], "https://pay.example/pro")

    def test_cancel_order(self) -> None:
        db_path = self._db_path()
        init_billing_db(db_path)
        with patch.dict("os.environ", {"PAYMENT_PROVIDER": "demo"}, clear=False):
            ok, payload = create_checkout_order("user_04", "starter", path=db_path)
            self.assertTrue(ok)
            order = dict(payload)

            ok, message = cancel_checkout_order("user_04", order["order_id"], path=db_path)
            self.assertTrue(ok)
            self.assertTrue(isinstance(message, str) and len(message) > 0)

            orders = list_checkout_orders("user_04", path=db_path)
            self.assertEqual(orders[0]["status"], "cancelled")

            ok, message = confirm_checkout_order("user_04", order["order_id"], path=db_path)
            self.assertFalse(ok)
            self.assertTrue(isinstance(message, str) and len(message) > 0)

    def test_check_and_consume_rejects_non_positive_amount(self) -> None:
        db_path = self._db_path()
        init_billing_db(db_path)
        set_subscription("user_05", "starter", path=db_path)

        ok, message = check_and_consume("user_05", ACTION_URL_AUDIT, amount=0, path=db_path)
        self.assertFalse(ok)
        self.assertIn("amount", message)

        ok, message = check_and_consume("user_05", ACTION_URL_AUDIT, amount=-3, path=db_path)
        self.assertFalse(ok)
        self.assertIn("amount", message)

    def test_check_and_consume_is_atomic_under_parallel_calls(self) -> None:
        db_path = self._db_path()
        init_billing_db(db_path)
        set_subscription("user_06", "starter", path=db_path)

        gate = Barrier(2)
        results: list[tuple[bool, str]] = []

        def worker() -> None:
            gate.wait()
            results.append(check_and_consume("user_06", ACTION_URL_AUDIT, amount=50, path=db_path))

        t1 = Thread(target=worker)
        t2 = Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(sum(1 for ok, _ in results if ok), 1)
        self.assertEqual(get_usage("user_06", ACTION_URL_AUDIT, path=db_path), 50)


if __name__ == "__main__":
    unittest.main()
