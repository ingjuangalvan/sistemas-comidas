import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command, get_commands, load_command_class
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from orders.models import (
    CashSession,
    Category,
    Order,
    OrderItem,
    OrderStatusLog,
    Product,
    ProductExtra,
)


@override_settings(BUSINESS_TAX_RATE="10", BUSINESS_DELIVERY_FEE="5000")
class OrderingTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Hamburguesas")
        self.product = Product.objects.create(
            category=self.category, name="Clásica", price=Decimal("10000")
        )
        cashier = get_user_model().objects.create_user(
            username="cashier", password="SafeCashPassword!23"
        )
        CashSession.objects.create(opened_by=cashier, opening_amount=Decimal("0"))

    def test_customer_order_calculates_delivery_and_tax(self):
        response = self.client.post(
            reverse("orders-api"),
            data=json.dumps(
                {
                    "customer_name": "Ana",
                    "phone": "3001234567",
                    "kind": "delivery",
                    "address": "Calle 1",
                    "items": [{"product_id": self.product.id, "quantity": 2}],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        order = Order.objects.get()
        self.assertEqual(order.subtotal, Decimal("20000.00"))
        self.assertEqual(order.tax, Decimal("2000.00"))
        self.assertEqual(order.delivery_fee, Decimal("5000.00"))
        self.assertEqual(order.total, Decimal("27000.00"))
        self.assertEqual(order.items.count(), 1)
        receipt = response.json()["order"]
        self.assertEqual(receipt["customer_name"], "Ana")
        self.assertEqual(receipt["phone"], "3001234567")
        self.assertEqual(receipt["address"], "Calle 1")
        self.assertEqual(receipt["kind_label"], "Domicilio")
        self.assertEqual(receipt["payment_status_label"], "Pendiente")
        self.assertTrue(receipt["created_at"])
        self.assertIsNone(receipt["paid_at"])
        self.assertEqual(receipt["items"][0]["name"], "Clásica")
        self.assertEqual(receipt["items"][0]["quantity"], 2)

    def test_delivery_requires_customer_phone(self):
        response = self.client.post(
            reverse("orders-api"),
            data=json.dumps(
                {
                    "customer_name": "Ana",
                    "kind": "delivery",
                    "address": "Calle 1",
                    "items": [{"product_id": self.product.id, "quantity": 1}],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("teléfono", response.json()["error"].lower())
        self.assertEqual(Order.objects.count(), 0)

    def test_table_order_requires_customer_name_and_table_number(self):
        missing_name = self.client.post(
            reverse("orders-api"),
            data=json.dumps(
                {
                    "customer_name": "",
                    "kind": "table",
                    "table_number": "4",
                    "items": [{"product_id": self.product.id, "quantity": 1}],
                }
            ),
            content_type="application/json",
        )
        missing_table = self.client.post(
            reverse("orders-api"),
            data=json.dumps(
                {
                    "customer_name": "Ana",
                    "kind": "table",
                    "items": [{"product_id": self.product.id, "quantity": 1}],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(missing_name.status_code, 400)
        self.assertEqual(missing_table.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    @override_settings(BUSINESS_WHATSAPP="")
    def test_public_menu_api_includes_business_details_for_order_sharing(self):
        response = self.client.get(reverse("menu-api"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["business_name"], "La Esquina Rápida")
        self.assertEqual(response.json()["whatsapp"], "")

    @override_settings(BUSINESS_WHATSAPP="573001234567")
    def test_public_menu_api_exposes_configured_business_whatsapp(self):
        response = self.client.get(reverse("menu-api"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["whatsapp"], "573001234567")

    def test_invalid_delivery_without_address_is_rejected(self):
        response = self.client.post(
            reverse("orders-api"),
            data=json.dumps(
                {
                    "customer_name": "Ana",
                    "kind": "delivery",
                    "items": [{"product_id": self.product.id, "quantity": 1}],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_selected_extra_is_priced_and_saved_as_a_snapshot(self):
        extra = ProductExtra.objects.create(
            product=self.product, name="Tocineta", price=Decimal("2500")
        )
        response = self.client.post(
            reverse("orders-api"),
            data=json.dumps(
                {
                    "customer_name": "Ana",
                    "kind": "takeaway",
                    "items": [
                        {
                            "product_id": self.product.id,
                            "quantity": 1,
                            "extra_ids": [extra.id],
                            "instructions": "Sin cebolla",
                        }
                    ],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        order = Order.objects.get()
        self.assertEqual(order.subtotal, Decimal("12500.00"))
        self.assertEqual(order.tax, Decimal("1250.00"))
        self.assertEqual(order.total, Decimal("13750.00"))
        self.assertEqual(order.items.get().line_total, Decimal("12500.00"))
        self.assertEqual(order.items.get().extras_snapshot[0]["name"], "Tocineta")
        self.assertEqual(order.items.get().instructions, "Sin cebolla")
        self.assertEqual(response.json()["order"]["items"][0]["instructions"], "Sin cebolla")

    def test_extra_from_another_product_is_rejected(self):
        other = Product.objects.create(
            category=self.category, name="Otra", price=Decimal("1000")
        )
        extra = ProductExtra.objects.create(
            product=other, name="No corresponde", price=Decimal("500")
        )
        response = self.client.post(
            reverse("orders-api"),
            data=json.dumps(
                {
                    "customer_name": "Ana",
                    "kind": "takeaway",
                    "items": [
                        {
                            "product_id": self.product.id,
                            "quantity": 1,
                            "extra_ids": [extra.id],
                        }
                    ],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    @override_settings(BUSINESS_ORDERS_OPEN=False)
    def test_paused_business_rejects_new_orders(self):
        response = self.client.post(
            reverse("orders-api"),
            data=json.dumps(
                {
                    "customer_name": "Ana",
                    "kind": "takeaway",
                    "items": [{"product_id": self.product.id, "quantity": 1}],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(Order.objects.count(), 0)

    def test_new_orders_are_blocked_until_a_cash_session_is_open(self):
        CashSession.objects.all().delete()

        response = self.client.post(
            reverse("orders-api"),
            data=json.dumps(
                {
                    "customer_name": "Ana",
                    "kind": "takeaway",
                    "items": [{"product_id": self.product.id, "quantity": 1}],
                }
            ),
            content_type="application/json",
        )
        menu = self.client.get(reverse("menu-api"))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(Order.objects.count(), 0)
        self.assertFalse(menu.json()["accepting_orders"])

    def test_public_menu_explains_when_cash_is_closed(self):
        CashSession.objects.all().delete()

        response = self.client.get(reverse("menu"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["orders_open"])
        self.assertContains(response, "La Esquina Rápida")
        self.assertNotContains(response, "{{ business_name")
        self.assertContains(response, "Pedidos pausados: caja cerrada")
        self.assertContains(response, "disabled")

    def test_public_menu_accepts_orders_when_cash_is_open(self):
        response = self.client.get(reverse("menu-api"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["accepting_orders"])


class CashAndAuditTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="admin", password="SafeTestPassword!23", is_staff=True
        )
        self.client.force_login(self.user)
        self.category = Category.objects.create(name="Bebidas")
        self.product = Product.objects.create(
            category=self.category, name="Limonada", price=Decimal("6000")
        )

    def test_order_api_filters_history_by_number_and_date_range(self):
        today = timezone.localdate()
        matching = Order.objects.create(
            customer_name="Ana",
            kind=Order.Kind.TAKEAWAY,
            total=Decimal("6000"),
            created_at=timezone.now(),
        )
        Order.objects.create(
            customer_name="Leo",
            kind=Order.Kind.TAKEAWAY,
            total=Decimal("6000"),
            created_at=timezone.now() - timedelta(days=2),
        )

        response = self.client.get(
            reverse("orders-api"),
            {
                "number": matching.number[-4:],
                "date_from": today.isoformat(),
                "date_to": today.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [order["number"] for order in response.json()["orders"]],
            [matching.number],
        )

    def test_order_api_rejects_reversed_date_range(self):
        response = self.client.get(
            reverse("orders-api"),
            {"date_from": "2026-10-17", "date_to": "2026-10-16"},
        )

        self.assertEqual(response.status_code, 400)

    def test_cash_history_includes_all_closed_sessions_for_printing(self):
        for _ in range(13):
            CashSession.objects.create(
                opened_by=self.user,
                opening_amount=Decimal("10000"),
                closed_at=timezone.now(),
                counted_amount=Decimal("10000"),
                closed_by=self.user,
                payment_totals_snapshot={},
            )

        response = self.client.get(reverse("cash-api"))

        self.assertEqual(response.status_code, 200)
        history = response.json()["history"]
        self.assertEqual(len(history), 13)
        self.assertEqual(history[0]["opened_by"], self.user.username)
        self.assertEqual(history[0]["closed_by"], self.user.username)
        self.assertIsNotNone(history[0]["closed_at"])
        self.assertIn("reconciliation", history[0])

    def test_cash_close_groups_paid_sales_and_records_difference(self):
        opened = self.client.post(
            reverse("cash-api"),
            data=json.dumps({"action": "open", "amount": "20000"}),
            content_type="application/json",
        )
        self.assertEqual(opened.status_code, 201)
        order = Order.objects.create(
            customer_name="Ana",
            kind=Order.Kind.TAKEAWAY,
            subtotal=Decimal("12000"),
            total=Decimal("12000"),
            payment_method=Order.PaymentMethod.CASH,
            payment_status=Order.PaymentStatus.PAID,
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            product_name=self.product.name,
            unit_price=self.product.price,
            quantity=2,
        )
        response = self.client.post(
            reverse("cash-api"),
            data=json.dumps({"action": "close", "counted_amount": "31000"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session"]["expected_cash"], "32000.00")
        self.assertEqual(response.json()["session"]["difference"], "-1000.00")
        session = CashSession.objects.get()
        self.assertIsNotNone(session.closed_at)

        later_order = Order.objects.create(
            customer_name="Leo",
            kind=Order.Kind.TAKEAWAY,
            subtotal=Decimal("8000"),
            total=Decimal("8000"),
            payment_method=Order.PaymentMethod.CASH,
            payment_status=Order.PaymentStatus.PAID,
        )
        OrderItem.objects.create(
            order=later_order,
            product=self.product,
            product_name=self.product.name,
            unit_price=self.product.price,
            quantity=1,
        )
        session.refresh_from_db()
        self.assertEqual(session.expected_cash, Decimal("32000.00"))

    def test_cash_close_sums_colombian_denominations_and_saves_breakdown(self):
        self.client.post(
            reverse("cash-api"),
            data=json.dumps({"action": "open", "amount": "0"}),
            content_type="application/json",
        )
        denominations = {
            "100": 2,
            "200": 3,
            "500": 4,
            "1000": 5,
            "2000": 1,
            "5000": 1,
            "10000": 2,
            "20000": 1,
            "50000": 1,
            "100000": 1,
        }
        response = self.client.post(
            reverse("cash-api"),
            data=json.dumps(
                {
                    "action": "close",
                    "denominations": denominations,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Decimal(response.json()["session"]["counted_amount"]), Decimal("204800")
        )
        self.assertEqual(
            response.json()["session"]["counted_denominations"], denominations
        )
        self.assertEqual(
            Decimal(response.json()["session"]["difference"]), Decimal("204800")
        )
        self.assertEqual(
            response.json()["session"]["reconciliation"]["status"], "surplus"
        )
        self.assertIn(
            "Sobrante", response.json()["session"]["reconciliation"]["reason"]
        )

    def test_cash_close_rejects_fractional_denomination_count(self):
        self.client.post(
            reverse("cash-api"),
            data=json.dumps({"action": "open", "amount": "0"}),
            content_type="application/json",
        )
        response = self.client.post(
            reverse("cash-api"),
            data=json.dumps(
                {
                    "action": "close",
                    "denominations": {"100": 1.5},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(CashSession.objects.get().is_open)

    def test_cash_close_reconciles_each_payment_method_and_total(self):
        self.client.post(
            reverse("cash-api"),
            data=json.dumps({"action": "open", "amount": "5000"}),
            content_type="application/json",
        )
        for method, amount in (
            (Order.PaymentMethod.CASH, "10000"),
            (Order.PaymentMethod.BANCOLOMBIA, "20000"),
            (Order.PaymentMethod.NEQUI, "15000"),
            (Order.PaymentMethod.CARD, "8000"),
        ):
            Order.objects.create(
                customer_name="Ana",
                kind=Order.Kind.TAKEAWAY,
                total=Decimal(amount),
                payment_method=method,
                payment_status=Order.PaymentStatus.PAID,
            )

        response = self.client.post(
            reverse("cash-api"),
            data=json.dumps(
                {
                    "action": "close",
                    "denominations": {"5000": 3},
                    "verified_payments": {
                        "Bancolombia": "21000",
                        "Nequi": "12000",
                        "Tarjeta": "8000",
                    },
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        reconciliation = response.json()["session"]["reconciliation"]
        self.assertTrue(reconciliation["complete"])
        self.assertEqual(Decimal(reconciliation["expected_sales"]), Decimal("53000"))
        self.assertEqual(Decimal(reconciliation["actual_sales"]), Decimal("51000"))
        self.assertEqual(Decimal(reconciliation["difference"]), Decimal("-2000"))
        self.assertEqual(reconciliation["status"], "shortage")
        methods = {row["method"]: row for row in reconciliation["methods"]}
        self.assertEqual(Decimal(methods["Efectivo"]["difference"]), Decimal("0"))
        self.assertEqual(Decimal(methods["Bancolombia"]["difference"]), Decimal("1000"))
        self.assertEqual(Decimal(methods["Nequi"]["difference"]), Decimal("-3000"))
        self.assertEqual(methods["Nequi"]["status"], "shortage")
        self.assertIn("Faltante", reconciliation["reason"])

    def test_cash_close_requires_actual_amount_for_methods_with_sales(self):
        self.client.post(
            reverse("cash-api"),
            data=json.dumps({"action": "open", "amount": "0"}),
            content_type="application/json",
        )
        Order.objects.create(
            customer_name="Ana",
            kind=Order.Kind.TAKEAWAY,
            total=Decimal("9000"),
            payment_method=Order.PaymentMethod.NEQUI,
            payment_status=Order.PaymentStatus.PAID,
        )

        response = self.client.post(
            reverse("cash-api"),
            data=json.dumps(
                {
                    "action": "close",
                    "denominations": {},
                    "verified_payments": {},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(CashSession.objects.get().is_open)

    def test_cash_close_rejects_fractional_cop_payment_verification(self):
        self.client.post(
            reverse("cash-api"),
            data=json.dumps({"action": "open", "amount": "0"}),
            content_type="application/json",
        )
        Order.objects.create(
            customer_name="Ana",
            kind=Order.Kind.TAKEAWAY,
            total=Decimal("9000"),
            payment_method=Order.PaymentMethod.NEQUI,
            payment_status=Order.PaymentStatus.PAID,
        )

        response = self.client.post(
            reverse("cash-api"),
            data=json.dumps(
                {
                    "action": "close",
                    "denominations": {},
                    "verified_payments": {"Nequi": "9000.50"},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(CashSession.objects.get().is_open)

    def test_payment_is_assigned_to_shift_when_it_is_paid_not_when_order_was_created(
        self,
    ):
        order = Order.objects.create(
            customer_name="Ana",
            kind=Order.Kind.TAKEAWAY,
            total=Decimal("12000"),
            payment_method=Order.PaymentMethod.CASH,
        )
        self.client.post(
            reverse("cash-api"),
            data=json.dumps({"action": "open", "amount": "0"}),
            content_type="application/json",
        )

        response = self.client.post(
            reverse("order-payment-api", args=[order.id]),
            data=json.dumps(
                {
                    "payment_method": "cash",
                    "paid": True,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()["order"]["paid_at"])
        self.assertEqual(
            response.json()["order"]["payment_method_label"], "Efectivo"
        )
        self.assertEqual(
            response.json()["order"]["payment_status_label"], "Pagado"
        )

        cash = self.client.get(reverse("cash-api")).json()["session"]
        self.assertEqual(Decimal(cash["payment_totals"]["Efectivo"]), Decimal("12000"))

    def test_historical_close_can_be_reconciled_without_changing_cash_count(self):
        session = CashSession.objects.create(
            opened_by=self.user,
            opening_amount=Decimal("0"),
            closed_at=timezone.now(),
            counted_amount=Decimal("5000"),
            counted_denominations={"1000": 5},
            payment_totals_snapshot={"Tarjeta": "6000"},
        )

        response = self.client.post(
            reverse("cash-reconciliation-api", args=[session.id]),
            data=json.dumps(
                {
                    "verified_payments": {"Tarjeta": "6000"},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()["session"]
        self.assertTrue(result["reconciliation"]["complete"])
        self.assertEqual(
            Decimal(result["reconciliation"]["difference"]), Decimal("5000")
        )
        self.assertEqual(result["reconciliation"]["status"], "surplus")
        self.assertEqual(Decimal(result["counted_amount"]), Decimal("5000"))
        self.assertEqual(result["reconciled_by"], self.user.username)

        repeated = self.client.post(
            reverse("cash-reconciliation-api", args=[session.id]),
            data=json.dumps(
                {
                    "verified_payments": {"Tarjeta": "6000"},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(repeated.status_code, 409)

    def test_status_change_is_audited(self):
        order = Order.objects.create(customer_name="Ana", kind=Order.Kind.TAKEAWAY)
        response = self.client.post(
            reverse("order-status-api", args=[order.id]),
            data=json.dumps({"status": "preparing"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        history = OrderStatusLog.objects.get(order=order)
        self.assertEqual(history.previous_status, Order.Status.RECEIVED)
        self.assertEqual(history.new_status, Order.Status.PREPARING)
        self.assertEqual(history.changed_by, self.user)

    def test_payment_method_and_paid_status_are_saved(self):
        order = Order.objects.create(
            customer_name="Ana", kind=Order.Kind.TAKEAWAY, total=Decimal("6000")
        )
        response = self.client.post(
            reverse("order-payment-api", args=[order.id]),
            data=json.dumps(
                {
                    "payment_method": "bancolombia",
                    "paid": True,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(order.payment_method, Order.PaymentMethod.BANCOLOMBIA)

    def test_cash_totals_group_bancolombia_and_nequi_separately(self):
        CashSession.objects.create(opened_by=self.user, opening_amount=Decimal("0"))
        for method in (Order.PaymentMethod.BANCOLOMBIA, Order.PaymentMethod.NEQUI):
            Order.objects.create(
                customer_name="Ana",
                kind=Order.Kind.TAKEAWAY,
                total=Decimal("6000"),
                payment_method=method,
                payment_status=Order.PaymentStatus.PAID,
            )

        response = self.client.get(reverse("cash-api"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Decimal(response.json()["session"]["payment_totals"]["Bancolombia"]),
            Decimal("6000"),
        )
        self.assertEqual(
            Decimal(response.json()["session"]["payment_totals"]["Nequi"]),
            Decimal("6000"),
        )

    def test_removed_generic_payment_methods_are_rejected(self):
        order = Order.objects.create(customer_name="Ana", kind=Order.Kind.TAKEAWAY)
        response = self.client.post(
            reverse("order-payment-api", args=[order.id]),
            data=json.dumps(
                {
                    "payment_method": "transfer",
                    "paid": True,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_empty_closed_cash_keeps_its_original_totals(self):
        self.client.post(
            reverse("cash-api"),
            data=json.dumps({"action": "open", "amount": "5000"}),
            content_type="application/json",
        )
        self.client.post(
            reverse("cash-api"),
            data=json.dumps({"action": "close", "counted_amount": "5000"}),
            content_type="application/json",
        )
        Order.objects.create(
            customer_name="Posterior",
            kind=Order.Kind.TAKEAWAY,
            total=Decimal("9000"),
            payment_method=Order.PaymentMethod.CASH,
            payment_status=Order.PaymentStatus.PAID,
        )
        session = CashSession.objects.get()

        self.assertEqual(session.payment_totals(), {})
        self.assertEqual(session.expected_cash, Decimal("5000.00"))


class ReportsTests(TestCase):
    def setUp(self):
        admin_user = get_user_model().objects.create_superuser(
            username="reports-admin",
            email="reports@example.test",
            password="SafeReportsPassword!23",
        )
        self.client.force_login(admin_user)
        category = Category.objects.create(name="Comidas")
        self.burger = Product.objects.create(
            category=category, name="Hamburguesa", price=Decimal("10000")
        )
        self.juice = Product.objects.create(
            category=category, name="Jugo", price=Decimal("6000")
        )
        self.soda = Product.objects.create(
            category=category, name="Gaseosa", price=Decimal("4000")
        )

    def test_report_returns_daily_sales_and_most_and_least_sold_products(self):
        burger_order = Order.objects.create(
            customer_name="Ana",
            kind=Order.Kind.TAKEAWAY,
            total=Decimal("33000"),
            payment_method=Order.PaymentMethod.CASH,
            payment_status=Order.PaymentStatus.PAID,
        )
        OrderItem.objects.create(
            order=burger_order,
            product=self.burger,
            product_name=self.burger.name,
            unit_price=self.burger.price,
            extra_total=Decimal("1000"),
            quantity=3,
        )
        juice_order = Order.objects.create(
            customer_name="Luis",
            kind=Order.Kind.TAKEAWAY,
            total=Decimal("12000"),
            payment_method=Order.PaymentMethod.NEQUI,
            payment_status=Order.PaymentStatus.PAID,
        )
        OrderItem.objects.create(
            order=juice_order,
            product=self.juice,
            product_name=self.juice.name,
            unit_price=self.juice.price,
            quantity=2,
        )
        today = timezone.localdate().isoformat()

        response = self.client.get(
            reverse("reports-api"), {"start": today, "end": today}
        )

        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertEqual(Decimal(report["sales_total"]), Decimal("45000"))
        self.assertEqual(report["daily_sales"], [{"date": today, "total": "45000"}])
        self.assertEqual(report["top_products"][0]["name"], "Hamburguesa")
        self.assertEqual(report["top_products"][0]["quantity"], 3)
        self.assertEqual(
            Decimal(report["top_products"][0]["revenue"]), Decimal("33000")
        )
        self.assertEqual(report["least_products"][0]["name"], "Gaseosa")
        self.assertEqual(report["least_products"][0]["quantity"], 0)


class WhatsAppWebhookTests(TestCase):
    @override_settings(WHATSAPP_VERIFY_TOKEN="local-test-token")
    def test_meta_webhook_verification(self):
        response = self.client.get(
            reverse("whatsapp-webhook"),
            {
                "hub.mode": "subscribe",
                "hub.verify_token": "local-test-token",
                "hub.challenge": "challenge-123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "challenge-123")

    def test_login_shows_business_name_instead_of_template_expression(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "La Esquina Rápida")
        self.assertNotContains(response, "{{ business_name")


class ProductAdminTests(TestCase):
    def setUp(self):
        self.admin_user = get_user_model().objects.create_superuser(
            username="carta-admin",
            email="admin@example.test",
            password="SafeAdminPassword!23",
        )
        self.client.force_login(self.admin_user)
        self.category = Category.objects.create(name="Hamburguesas")

    def test_product_admin_changelist_and_add_form_are_available_in_spanish(self):
        listing = self.client.get(reverse("admin:orders_product_changelist"))
        add_form = self.client.get(reverse("admin:orders_product_add"))

        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, "Productos de la carta")
        self.assertEqual(add_form.status_code, 200)
        self.assertContains(add_form, "Nombre del producto")
        self.assertContains(add_form, "Precio en COP")
        self.assertContains(add_form, "Disponible para pedir")

    def test_panel_category_filter_renders_all_categories_and_refreshes_panel_script(self):
        inactive_category = Category.objects.create(name="Bebidas", active=False)

        response = self.client.get(reverse("panel"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<option value="">Todas las categorías</option>', html=False)
        self.assertContains(response, f'<option value="{self.category.id}">Hamburguesas</option>', html=False)
        self.assertContains(response, f'<option value="{inactive_category.id}">Bebidas (inactiva)</option>', html=False)
        self.assertContains(response, 'id="order-number-filter"', html=False)
        self.assertContains(response, 'id="order-date-from"', html=False)
        self.assertContains(response, 'id="order-date-to"', html=False)
        self.assertContains(response, "js/panel.js?v=11", html=False)

    def test_admin_can_create_mark_sold_out_and_delete_unsold_product(self):
        response = self.client.post(
            reverse("admin:orders_product_add"),
            {
                "name": "Hamburguesa de prueba",
                "category": self.category.pk,
                "description": "Producto de prueba",
                "price": "15000",
                "available": "on",
                "featured": "",
                "extras-TOTAL_FORMS": "0",
                "extras-INITIAL_FORMS": "0",
                "extras-MIN_NUM_FORMS": "0",
                "extras-MAX_NUM_FORMS": "1000",
                "_save": "Guardar",
            },
        )
        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(name="Hamburguesa de prueba")

        self.client.post(
            reverse("admin:orders_product_changelist"),
            {
                "action": "mark_sold_out",
                "_selected_action": [product.pk],
                "index": "0",
            },
        )
        product.refresh_from_db()
        self.assertFalse(product.available)

        delete_response = self.client.post(
            reverse("admin:orders_product_delete", args=[product.pk]), {"post": "yes"}
        )
        self.assertEqual(delete_response.status_code, 302)
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())


class ProductPanelApiTests(TestCase):
    def setUp(self):
        self.admin_user = get_user_model().objects.create_superuser(
            username="panel-admin",
            email="panel@example.test",
            password="SafePanelPassword!23",
        )
        self.client.force_login(self.admin_user)
        self.category = Category.objects.create(name="Bebidas")

    def test_panel_can_create_edit_retire_and_delete_unsold_product(self):
        created = self.client.post(
            reverse("products-api"),
            data=json.dumps(
                {
                    "name": "Jugo de prueba",
                    "description": "Natural",
                    "category_id": self.category.id,
                    "price": "8500",
                    "available": True,
                    "featured": False,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 201)
        product_id = created.json()["product"]["id"]

        updated = self.client.patch(
            reverse("product-detail-api", args=[product_id]),
            data=json.dumps(
                {
                    "price": "9000",
                    "available": False,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["product"]["price"], "9000.00")
        self.assertFalse(updated.json()["product"]["available"])

        menu = self.client.get(reverse("menu-api")).json()
        self.assertFalse(
            any(
                item["name"] == "Jugo de prueba"
                for category in menu["categories"]
                for item in category["products"]
            )
        )

        deleted = self.client.delete(reverse("product-detail-api", args=[product_id]))
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(Product.objects.filter(pk=product_id).exists())

    def test_panel_retires_product_with_sales_and_preserves_order_history(self):
        product = Product.objects.create(
            category=self.category, name="Limonada", price=Decimal("6000")
        )
        order = Order.objects.create(customer_name="Ana", kind=Order.Kind.TAKEAWAY)
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            unit_price=product.price,
            quantity=1,
        )

        deleted = self.client.delete(reverse("product-detail-api", args=[product.id]))
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["archived"])
        self.assertFalse(deleted.json()["deleted"])
        product.refresh_from_db()
        self.assertFalse(product.available)
        self.assertEqual(product.sold_items.count(), 1)
        self.assertTrue(Order.objects.filter(pk=order.pk).exists())

        restored = self.client.patch(
            reverse("product-detail-api", args=[product.id]),
            data=json.dumps(
                {
                    "available": True,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(restored.status_code, 200)
        product.refresh_from_db()
        self.assertTrue(product.available)
        self.assertEqual(product.sold_items.count(), 1)


class DemoCatalogTests(TestCase):
    def test_seed_demo_uses_requested_categories_and_removes_classic_extras(self):
        call_command("seed_demo", verbosity=0)
        call_command("seed_demo", verbosity=0)

        expected_categories = {
            "Hamburguesas",
            "Perros",
            "Salchipapas",
            "Asados",
            "Patacones",
            "Para acompañar",
            "Bebidas",
        }
        self.assertEqual(
            set(Category.objects.values_list("name", flat=True)), expected_categories
        )
        self.assertFalse(
            ProductExtra.objects.filter(
                product__name="La Clásica",
                name__in=("Doble carne", "Queso extra", "Tocineta"),
            ).exists()
        )
        self.assertEqual(Product.objects.count(), 13)


class RunserverCommandTests(SimpleTestCase):
    def test_runserver_opens_login_in_browser_after_server_binds(self):
        self.assertEqual(get_commands()["runserver"], "orders")
        command = load_command_class("orders", "runserver")
        command.addr = "127.0.0.1"
        command._raw_ipv6 = False
        command.open_browser = True

        with (
            patch("orders.management.commands.runserver.Timer") as timer,
            patch(
                "orders.management.commands.runserver.webbrowser.open",
                return_value=True,
            ) as browser_open,
        ):
            command.on_bind(8000)
            timer.call_args.args[1](*timer.call_args.kwargs["args"])

        timer.assert_called_once()
        browser_open.assert_called_once_with("http://127.0.0.1:8000/login/")
        self.assertEqual(
            timer.call_args.kwargs["args"],
            ("http://127.0.0.1:8000/login/",),
        )
        timer.return_value.start.assert_called_once()

    def test_runserver_can_skip_opening_the_browser(self):
        command = load_command_class("orders", "runserver")
        parser = command.create_parser("manage.py", "runserver")

        options = parser.parse_args(["--nobrowser"])

        self.assertFalse(options.open_browser)
