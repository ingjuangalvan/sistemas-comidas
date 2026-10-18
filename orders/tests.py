import csv
import io
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import qrcode
from django.contrib.auth import get_user_model
from django.core.management import call_command, get_commands, load_command_class
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from qrcode.image.svg import SvgPathImage

from orders.models import (
    CashSession,
    Category,
    Expense,
    InvoiceCancellationRequest,
    Order,
    OrderInvoice,
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

    def test_beverage_stock_is_reserved_when_order_is_created(self):
        beverage_category = Category.objects.create(name="Bebidas")
        beverage = Product.objects.create(
            category=beverage_category,
            name="Gaseosa",
            price=Decimal("3000"),
            stock_tracked=True,
            stock_quantity=5,
        )
        response = self.client.post(
            reverse("orders-api"),
            data=json.dumps(
                {
                    "customer_name": "Ana",
                    "kind": "takeaway",
                    "items": [{"product_id": beverage.id, "quantity": 2}],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        beverage.refresh_from_db()
        self.assertEqual(beverage.stock_quantity, 3)
        self.assertTrue(OrderItem.objects.get().stock_reserved)

        insufficient = self.client.post(
            reverse("orders-api"),
            data=json.dumps(
                {
                    "customer_name": "Leo",
                    "kind": "takeaway",
                    "items": [{"product_id": beverage.id, "quantity": 4}],
                }
            ),
            content_type="application/json",
        )
        beverage.refresh_from_db()
        self.assertEqual(insufficient.status_code, 409)
        self.assertEqual(beverage.stock_quantity, 3)
        self.assertEqual(Order.objects.count(), 1)

    def test_beverage_with_unconfigured_stock_cannot_be_ordered(self):
        beverage = Product.objects.create(
            category=Category.objects.create(name="Bebidas"),
            name="Jugo",
            price=Decimal("4000"),
            stock_tracked=True,
        )
        response = self.client.post(
            reverse("orders-api"),
            data=json.dumps(
                {
                    "customer_name": "Ana",
                    "kind": "takeaway",
                    "items": [{"product_id": beverage.id, "quantity": 1}],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("existencias", response.json()["error"].lower())
        self.assertEqual(Order.objects.count(), 0)

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

    def test_table_orders_accept_only_tables_one_through_ten(self):
        valid_order = self.client.post(
            reverse("orders-api"),
            data=json.dumps(
                {
                    "customer_name": "Ana",
                    "kind": "table",
                    "table_number": "10",
                    "items": [{"product_id": self.product.id, "quantity": 1}],
                }
            ),
            content_type="application/json",
        )
        invalid_order = self.client.post(
            reverse("orders-api"),
            data=json.dumps(
                {
                    "customer_name": "Leo",
                    "kind": "table",
                    "table_number": "11",
                    "items": [{"product_id": self.product.id, "quantity": 1}],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(valid_order.status_code, 201)
        self.assertEqual(valid_order.json()["order"]["table_number"], "10")
        self.assertEqual(invalid_order.status_code, 400)
        self.assertIn("entre 1 y 10", invalid_order.json()["error"])
        self.assertEqual(Order.objects.count(), 1)

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

    def test_public_menu_api_includes_beverage_stock(self):
        beverage = Product.objects.create(
            category=Category.objects.create(name="Bebidas"),
            name="Agua",
            price=Decimal("2500"),
            stock_tracked=True,
            stock_quantity=4,
        )

        response = self.client.get(reverse("menu-api"))
        menu_product = next(
            product
            for category in response.json()["categories"]
            for product in category["products"]
            if product["id"] == beverage.id
        )

        self.assertTrue(menu_product["stock_tracked"])
        self.assertEqual(menu_product["stock_quantity"], 4)

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
        self.assertContains(response, "Mesa 10")
        self.assertNotContains(response, "Mesa 11")

    def test_read_only_menu_and_qr_are_public(self):
        menu_response = self.client.get(reverse("public-menu"))
        qr_response = self.client.get(
            reverse("public-menu-qr"),
            secure=True,
            HTTP_HOST="testserver",
        )

        self.assertEqual(menu_response.status_code, 200)
        self.assertContains(menu_response, "Carta informativa, sin pedidos en línea")
        self.assertNotContains(menu_response, 'id="checkout-form"')
        self.assertEqual(qr_response.status_code, 200)
        self.assertEqual(qr_response["Content-Type"], "image/svg+xml")
        qr = qrcode.QRCode(box_size=10, border=4)
        qr.add_data("https://testserver/carta/")
        qr.make(fit=True)
        expected_image = qr.make_image(image_factory=SvgPathImage)
        expected_output = io.BytesIO()
        expected_image.save(expected_output)
        self.assertEqual(qr_response.content, expected_output.getvalue())

    def test_missing_qr_dependency_does_not_break_application_startup(self):
        original_import = __import__

        def import_without_qrcode(name, *args, **kwargs):
            if name == "qrcode" or name.startswith("qrcode."):
                raise ImportError("qrcode unavailable")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=import_without_qrcode):
            response = self.client.get(reverse("public-menu-qr"))

        self.assertEqual(response.status_code, 503)
        self.assertIn("requirements.txt", response.json()["error"])

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
        self.assertEqual(response.json()["pagination"]["total"], 1)
        self.assertEqual(response.json()["summary"]["recent_orders"][0]["number"], matching.number)

    def test_active_order_scope_includes_old_open_orders_independent_of_history_dates(self):
        active_order = Order.objects.create(
            customer_name="Cocina",
            kind=Order.Kind.TAKEAWAY,
            status=Order.Status.PREPARING,
            created_at=timezone.now() - timedelta(days=3),
        )
        completed_order = Order.objects.create(
            customer_name="Historial",
            kind=Order.Kind.TAKEAWAY,
            status=Order.Status.DELIVERED,
            created_at=timezone.now() - timedelta(days=2),
        )

        response = self.client.get(reverse("orders-api"), {"scope": "active"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["id"] for row in response.json()["orders"]], [active_order.id]
        )
        self.assertEqual(response.json()["orders"][0]["status"], Order.Status.PREPARING)
        self.assertNotIn(completed_order.id, [row["id"] for row in response.json()["orders"]])

    def test_order_history_uses_server_side_pagination(self):
        Order.objects.bulk_create(
            [
                Order(
                    number=f"PAGE-{index:03}",
                    customer_name=f"Cliente {index}",
                    kind=Order.Kind.TAKEAWAY,
                )
                for index in range(51)
            ]
        )

        response = self.client.get(reverse("orders-api"), {"page": "2"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["orders"]), 10)
        self.assertEqual(
            response.json()["pagination"],
            {"page": 2, "pages": 6, "total": 51},
        )
        self.assertEqual(response.json()["orders"][0]["number"], "PAGE-040")

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
                    "cash_received": "12000",
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
        invoice_data = response.json()["order"]["invoice"]
        self.assertEqual(Decimal(invoice_data["cash_received"]), Decimal("12000"))
        self.assertEqual(Decimal(invoice_data["change_given"]), Decimal("0"))
        self.assertEqual(
            OrderInvoice.objects.get(order=order).cash_received, Decimal("12000")
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

    def test_cancelling_order_requires_and_displays_reason(self):
        order = Order.objects.create(
            customer_name="Ana", kind=Order.Kind.TAKEAWAY
        )
        url = reverse("order-status-api", args=[order.id])

        missing_reason = self.client.post(
            url,
            data=json.dumps({"status": Order.Status.CANCELLED, "reason": "  "}),
            content_type="application/json",
        )
        self.assertEqual(missing_reason.status_code, 400)
        self.assertFalse(OrderStatusLog.objects.filter(order=order).exists())

        cancelled = self.client.post(
            url,
            data=json.dumps(
                {
                    "status": Order.Status.CANCELLED,
                    "reason": "El cliente canceló el pedido",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(
            cancelled.json()["order"]["cancellation_reason"],
            "El cliente canceló el pedido",
        )
        self.assertEqual(
            OrderStatusLog.objects.get(order=order).reason,
            "El cliente canceló el pedido",
        )

        listed_order = self.client.get(reverse("orders-api")).json()["orders"][0]
        self.assertEqual(
            listed_order["cancellation_reason"],
            "El cliente canceló el pedido",
        )

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
        self.assertEqual(order.invoice.status, OrderInvoice.Status.ACTIVE)
        self.assertIsNone(order.invoice.cash_received)
        self.assertEqual(order.invoice.change_given, Decimal("0"))

    def test_cash_payment_records_received_amount_and_change_on_invoice(self):
        order = Order.objects.create(
            customer_name="Ana",
            kind=Order.Kind.TAKEAWAY,
            total=Decimal("12000"),
        )

        response = self.client.post(
            reverse("order-payment-api", args=[order.id]),
            data=json.dumps(
                {
                    "payment_method": "cash",
                    "paid": True,
                    "cash_received": "20000",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        invoice = OrderInvoice.objects.get(order=order)
        self.assertEqual(invoice.cash_received, Decimal("20000.00"))
        self.assertEqual(invoice.change_given, Decimal("8000.00"))
        self.assertEqual(
            Decimal(response.json()["order"]["invoice"]["change_given"]),
            Decimal("8000.00"),
        )

    def test_cash_payment_rejects_insufficient_or_missing_tender_without_charging(self):
        order = Order.objects.create(
            customer_name="Ana",
            kind=Order.Kind.TAKEAWAY,
            total=Decimal("12000"),
        )

        for payload in (
            {"payment_method": "cash", "paid": True, "cash_received": "11999"},
            {"payment_method": "cash", "paid": True},
            {"payment_method": "cash", "paid": True, "cash_received": "-1"},
            {"payment_method": "cash", "paid": True, "cash_received": "NaN"},
            {
                "payment_method": "cash",
                "paid": True,
                "cash_received": "999999999999",
            },
        ):
            response = self.client.post(
                reverse("order-payment-api", args=[order.id]),
                data=json.dumps(payload),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 400)

        order.refresh_from_db()
        self.assertEqual(order.payment_status, Order.PaymentStatus.PENDING)
        self.assertFalse(OrderInvoice.objects.filter(order=order).exists())

    def test_pending_received_order_can_add_and_remove_products(self):
        order = Order.objects.create(
            customer_name="Ana",
            kind=Order.Kind.TAKEAWAY,
            subtotal=Decimal("6000"),
            total=Decimal("6000"),
        )
        original_item = OrderItem.objects.create(
            order=order,
            product=self.product,
            product_name=self.product.name,
            unit_price=self.product.price,
            quantity=1,
        )
        second_product = Product.objects.create(
            category=self.category, name="Té", price=Decimal("3000")
        )

        response = self.client.patch(
            reverse("order-detail-api", args=[order.id]),
            data=json.dumps(
                {
                    "items": [
                        {
                            "item_id": original_item.id,
                            "product_id": self.product.id,
                            "quantity": 2,
                            "instructions": "Sin azúcar",
                        },
                        {"product_id": second_product.id, "quantity": 1},
                    ]
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.subtotal, Decimal("15000.00"))
        self.assertEqual(order.total, Decimal("15000.00"))
        self.assertEqual(order.items.count(), 2)
        original_item.refresh_from_db()
        self.assertEqual(original_item.quantity, 2)
        self.assertEqual(original_item.instructions, "Sin azúcar")
        self.assertEqual(response.json()["order"]["invoice"], None)

    def test_order_edit_and_delete_are_blocked_after_preparation_or_payment(self):
        for status, payment_status in (
            (Order.Status.PREPARING, Order.PaymentStatus.PENDING),
            (Order.Status.RECEIVED, Order.PaymentStatus.PAID),
        ):
            with self.subTest(status=status, payment_status=payment_status):
                order = Order.objects.create(
                    customer_name="Ana",
                    kind=Order.Kind.TAKEAWAY,
                    status=status,
                    payment_status=payment_status,
                )
                payload = json.dumps(
                    {"items": [{"product_id": self.product.id, "quantity": 2}]}
                )
                edit_response = self.client.patch(
                    reverse("order-detail-api", args=[order.id]),
                    data=payload,
                    content_type="application/json",
                )
                delete_response = self.client.delete(
                    reverse("order-detail-api", args=[order.id])
                )

                self.assertEqual(edit_response.status_code, 409)
                self.assertEqual(delete_response.status_code, 409)
                self.assertTrue(Order.objects.filter(pk=order.pk).exists())
                self.assertEqual(order.items.count(), 0)

    def test_pending_received_order_can_be_deleted(self):
        order = Order.objects.create(
            customer_name="Ana", kind=Order.Kind.TAKEAWAY
        )

        response = self.client.delete(reverse("order-detail-api", args=[order.id]))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Order.objects.filter(pk=order.pk).exists())

    def test_order_cannot_return_to_received_after_preparation_starts(self):
        order = Order.objects.create(
            customer_name="Ana",
            kind=Order.Kind.TAKEAWAY,
            status=Order.Status.PREPARING,
        )

        response = self.client.post(
            reverse("order-status-api", args=[order.id]),
            data=json.dumps({"status": Order.Status.RECEIVED}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 409)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PREPARING)

    def test_invoice_cancellation_requires_reason_and_is_immediate(self):
        order = Order.objects.create(
            customer_name="Ana",
            kind=Order.Kind.TAKEAWAY,
            total=Decimal("6000"),
            payment_status=Order.PaymentStatus.PAID,
        )
        invoice = OrderInvoice.objects.create(
            order=order, number=f"F-{order.number}"
        )

        missing_reason = self.client.post(
            reverse("invoice-cancellation-request-api", args=[order.id]),
            data=json.dumps({"reason": "  "}),
            content_type="application/json",
        )
        self.assertEqual(missing_reason.status_code, 400)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, OrderInvoice.Status.ACTIVE)
        self.assertFalse(InvoiceCancellationRequest.objects.exists())

        response = self.client.post(
            reverse("invoice-cancellation-request-api", args=[order.id]),
            data=json.dumps({"reason": "Registro duplicado"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["cancelled"])
        self.assertEqual(response.json()["invoice_number"], invoice.number)
        cancellation = InvoiceCancellationRequest.objects.get(invoice=invoice)
        self.assertEqual(cancellation.status, InvoiceCancellationRequest.Status.APPROVED)
        self.assertEqual(cancellation.reason, "Registro duplicado")
        self.assertEqual(cancellation.requested_by, self.user)
        self.assertIsNotNone(cancellation.decided_at)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, OrderInvoice.Status.VOIDED)
        self.assertIsNotNone(invoice.voided_at)
        self.assertEqual(response.json()["reason"], "Registro duplicado")
        self.assertFalse(response.json()["refunded"])

        repeated = self.client.post(
            reverse("invoice-cancellation-request-api", args=[order.id]),
            data=json.dumps({"reason": "Segundo intento"}),
            content_type="application/json",
        )
        self.assertEqual(repeated.status_code, 409)

    def test_orders_api_can_list_voided_invoices_separately(self):
        voided_order = Order.objects.create(
            customer_name="Ana",
            kind=Order.Kind.TAKEAWAY,
            payment_status=Order.PaymentStatus.PAID,
            status=Order.Status.DELIVERED,
        )
        active_order = Order.objects.create(
            customer_name="Luis",
            kind=Order.Kind.TAKEAWAY,
            payment_status=Order.PaymentStatus.PAID,
        )
        OrderInvoice.objects.create(
            order=voided_order,
            number=f"F-{voided_order.number}",
            status=OrderInvoice.Status.VOIDED,
        )
        OrderInvoice.objects.create(
            order=active_order,
            number=f"F-{active_order.number}",
        )

        response = self.client.get(
            reverse("orders-api"), {"invoice_status": OrderInvoice.Status.VOIDED}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["invoice"]["status"] for row in response.json()["orders"]],
            [OrderInvoice.Status.VOIDED],
        )
        self.assertEqual(
            response.json()["orders"][0]["number"], voided_order.number
        )
        self.assertTrue(response.json()["orders"][0]["invoice"]["not_refunded"])
        self.assertNotIn("voided_by", response.json()["orders"][0]["invoice"])

    def test_invoice_cancellation_does_not_require_email_configuration(self):
        order = Order.objects.create(
            customer_name="Ana",
            kind=Order.Kind.TAKEAWAY,
            payment_status=Order.PaymentStatus.PAID,
        )
        OrderInvoice.objects.create(order=order, number=f"F-{order.number}")

        response = self.client.post(
            reverse("invoice-cancellation-request-api", args=[order.id]),
            data=json.dumps({"reason": "Corrección"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(OrderInvoice.objects.get(order=order).status, OrderInvoice.Status.VOIDED)
        self.assertEqual(
            InvoiceCancellationRequest.objects.get(invoice__order=order).reason,
            "Corrección",
        )

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

    def test_cash_totals_keep_paid_orders_even_if_the_order_was_cancelled(self):
        session = CashSession.objects.create(
            opened_by=self.user,
            opened_at=timezone.now() - timedelta(minutes=5),
            opening_amount=Decimal("0"),
        )
        Order.objects.create(
            customer_name="Ana",
            kind=Order.Kind.TAKEAWAY,
            status=Order.Status.CANCELLED,
            total=Decimal("12000"),
            payment_method=Order.PaymentMethod.CASH,
            payment_status=Order.PaymentStatus.PAID,
        )

        self.assertEqual(
            session.payment_totals()["Efectivo"], Decimal("12000.00")
        )


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

    def test_report_separates_voided_receipts_without_removing_collected_sales(self):
        voided_order = Order.objects.create(
            customer_name="Ana",
            kind=Order.Kind.TAKEAWAY,
            status=Order.Status.DELIVERED,
            total=Decimal("10000"),
            payment_status=Order.PaymentStatus.PAID,
        )
        OrderInvoice.objects.create(
            order=voided_order,
            number=f"F-{voided_order.number}",
            status=OrderInvoice.Status.VOIDED,
        )
        cancelled_paid_order = Order.objects.create(
            customer_name="Luis",
            kind=Order.Kind.TAKEAWAY,
            status=Order.Status.CANCELLED,
            total=Decimal("2000"),
            payment_status=Order.PaymentStatus.PAID,
        )

        today = timezone.localdate().isoformat()
        response = self.client.get(
            reverse("reports-api"), {"start": today, "end": today}
        )

        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertEqual(Decimal(report["sales_total"]), Decimal("12000"))
        self.assertEqual(report["paid_order_count"], 2)
        self.assertEqual(report["order_count"], 1)
        self.assertEqual(report["cancelled_order_count"], 1)
        self.assertEqual(report["voided_invoice_count"], 1)
        self.assertEqual(Decimal(report["voided_invoice_total"]), Decimal("10000"))

    def test_report_and_monthly_metric_use_payment_date_not_order_creation_date(self):
        now = timezone.now()
        today = timezone.localdate()
        order = Order.objects.create(
            customer_name="María",
            kind=Order.Kind.DELIVERY,
            status=Order.Status.DELIVERED,
            created_at=now - timedelta(days=40),
            paid_at=now,
            payment_status=Order.PaymentStatus.PAID,
            subtotal=Decimal("10000"),
            delivery_fee=Decimal("5000"),
            tax=Decimal("1000"),
            total=Decimal("16000"),
        )
        OrderItem.objects.create(
            order=order,
            product=self.burger,
            product_name=self.burger.name,
            unit_price=self.burger.price,
            quantity=1,
        )

        report_response = self.client.get(reverse("reports-api"))
        summary_response = self.client.get(reverse("orders-api"))

        self.assertEqual(report_response.status_code, 200)
        report = report_response.json()
        self.assertEqual(report["start"], today.replace(day=1).isoformat())
        self.assertEqual(Decimal(report["sales_total"]), Decimal("16000"))
        self.assertEqual(report["paid_order_count"], 1)
        self.assertEqual(report["created_order_count"], 0)
        self.assertEqual(Decimal(report["average_ticket"]), Decimal("16000"))
        self.assertEqual(Decimal(report["subtotal_total"]), Decimal("10000"))
        self.assertEqual(Decimal(report["delivery_fee_total"]), Decimal("5000"))
        self.assertEqual(Decimal(report["tax_total"]), Decimal("1000"))
        self.assertEqual(
            Decimal(report["daily_sales"][today.day - 1]["total"]),
            Decimal("16000"),
        )
        self.assertEqual(summary_response.status_code, 200)
        self.assertEqual(
            Decimal(summary_response.json()["summary"]["month_sales_total"]),
            Decimal("16000"),
        )

    def test_report_includes_order_channel_pending_and_current_stock_control(self):
        paid_order = Order.objects.create(
            customer_name="Ana",
            kind=Order.Kind.TABLE,
            total=Decimal("10000"),
            payment_status=Order.PaymentStatus.PAID,
        )
        OrderItem.objects.create(
            order=paid_order,
            product=self.soda,
            product_name=self.soda.name,
            unit_price=self.soda.price,
            quantity=2,
        )
        pending_order = Order.objects.create(
            customer_name="Luis",
            kind=Order.Kind.TAKEAWAY,
            total=Decimal("6000"),
            payment_status=Order.PaymentStatus.PENDING,
        )
        beverage = Product.objects.create(
            category=Category.objects.create(name="Bebidas"),
            name="Agua",
            price=Decimal("2500"),
            stock_tracked=True,
            stock_quantity=0,
            available=False,
        )
        today = timezone.localdate().isoformat()

        response = self.client.get(
            reverse("reports-api"), {"start": today, "end": today}
        )

        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertEqual(report["by_order_type"][0]["kind"], "Mesa")
        self.assertEqual(Decimal(report["pending_total"]), Decimal("6000"))
        self.assertEqual(report["pending_order_count"], 1)
        self.assertEqual(report["out_of_stock_count"], 1)
        self.assertEqual(report["inventory"][0]["name"], beverage.name)
        self.assertEqual(report["inventory"][0]["stock_quantity"], 0)
        self.assertEqual(report["inventory"][0]["units_sold"], 0)

    def test_csv_exports_orders_by_creation_or_payment_date(self):
        now = timezone.now()
        order = Order.objects.create(
            customer_name="Ana",
            kind=Order.Kind.TAKEAWAY,
            created_at=now - timedelta(days=40),
            paid_at=now,
            payment_status=Order.PaymentStatus.PAID,
            total=Decimal("10000"),
        )

        response = self.client.get(reverse("reports-csv"))

        self.assertEqual(response.status_code, 200)
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
        self.assertEqual(rows[0][1:3], ["Fecha del pedido", "Fecha del pago"])
        self.assertEqual(rows[1][0], order.number)
        created_at = timezone.localtime(now - timedelta(days=40))
        self.assertTrue(rows[1][1].startswith(created_at.date().isoformat()))
        self.assertTrue(rows[1][2].startswith(timezone.localtime(now).date().isoformat()))

    def test_expenses_require_remodeling_description_and_support_edit_delete_and_filters(self):
        url = reverse("expenses-api")
        payload = {
            "expense_date": timezone.localdate().isoformat(),
            "category": Expense.Category.REMODELING,
            "description": "",
            "amount": "150000",
        }
        missing_description = self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(missing_description.status_code, 400)

        payload["description"] = "Pintura del local"
        created = self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 201)
        expense_id = created.json()["expense"]["id"]
        self.assertEqual(created.json()["expense"]["created_by"], "reports-admin")

        edited = self.client.patch(
            reverse("expense-detail-api", args=[expense_id]),
            data=json.dumps(
                {
                    "expense_date": timezone.localdate().isoformat(),
                    "category": Expense.Category.UTILITIES,
                    "description": "Factura de energía",
                    "amount": "75000",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(Decimal(edited.json()["expense"]["amount"]), Decimal("75000"))

        filtered = self.client.get(url, {"category": Expense.Category.UTILITIES})
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.json()["count"], 1)
        self.assertEqual(Decimal(filtered.json()["total"]), Decimal("75000"))

        deleted = self.client.delete(reverse("expense-detail-api", args=[expense_id]))
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(Expense.objects.count(), 0)

    def test_profit_report_crosses_collected_sales_and_expenses_by_month(self):
        current_month = timezone.localdate().replace(day=1)
        previous_month = date(
            current_month.year - (current_month.month == 1),
            12 if current_month.month == 1 else current_month.month - 1,
            1,
        )
        Order.objects.create(
            customer_name="Ana",
            kind=Order.Kind.TABLE,
            payment_status=Order.PaymentStatus.PAID,
            paid_at=timezone.make_aware(
                datetime.combine(current_month, datetime.min.time())
            ),
            total=Decimal("300000"),
        )
        Order.objects.create(
            customer_name="Luis",
            kind=Order.Kind.TAKEAWAY,
            payment_status=Order.PaymentStatus.PAID,
            paid_at=timezone.make_aware(
                datetime.combine(previous_month, datetime.min.time())
            ),
            total=Decimal("200000"),
        )
        Expense.objects.create(
            expense_date=current_month,
            category=Expense.Category.PURCHASE,
            description="Insumos",
            amount=Decimal("120000"),
            created_by=get_user_model().objects.get(username="reports-admin"),
        )
        Expense.objects.create(
            expense_date=previous_month,
            category=Expense.Category.EMPLOYEES,
            description="Nómina",
            amount=Decimal("80000"),
            created_by=get_user_model().objects.get(username="reports-admin"),
        )

        response = self.client.get(
            reverse("profits-api"),
            {
                "start_month": previous_month.strftime("%Y-%m"),
                "end_month": current_month.strftime("%Y-%m"),
            },
        )

        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertEqual(len(report["months"]), 2)
        self.assertEqual(Decimal(report["sales_total"]), Decimal("500000"))
        self.assertEqual(Decimal(report["expense_total"]), Decimal("200000"))
        self.assertEqual(Decimal(report["profit"]), Decimal("300000"))
        self.assertEqual(Decimal(report["months"][0]["profit"]), Decimal("120000"))
        self.assertEqual(Decimal(report["months"][1]["profit"]), Decimal("180000"))

    def test_profit_report_defaults_to_three_calendar_months(self):
        current_month = timezone.localdate().replace(day=1)
        third_month = (current_month - timedelta(days=1)).replace(day=1)
        third_month = (third_month - timedelta(days=1)).replace(day=1)

        response = self.client.get(reverse("profits-api"))

        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertEqual(report["start_month"], third_month.strftime("%Y-%m"))
        self.assertEqual(report["end_month"], current_month.strftime("%Y-%m"))
        previous_month = (current_month - timedelta(days=1)).replace(day=1)
        self.assertEqual(
            [row["month"] for row in report["months"]],
            [
                third_month.strftime("%Y-%m"),
                previous_month.strftime("%Y-%m"),
                current_month.strftime("%Y-%m"),
            ],
        )

    def test_all_sales_report_covers_older_paid_orders_with_monthly_trend(self):
        paid_at = timezone.now() - timedelta(days=400)
        Order.objects.create(
            customer_name="Ana",
            kind=Order.Kind.TAKEAWAY,
            payment_status=Order.PaymentStatus.PAID,
            paid_at=paid_at,
            total=Decimal("25000"),
        )

        response = self.client.get(reverse("reports-api"), {"all": "1"})

        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertEqual(Decimal(report["sales_total"]), Decimal("25000"))
        self.assertEqual(report["trend_interval"], "month")
        self.assertLessEqual(len(report["daily_sales"]), 14)


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
        self.assertContains(response, 'id="orders-pagination"', html=False)
        self.assertContains(response, 'name="cash_received"', html=False)
        self.assertContains(response, 'id="cash-change-preview"', html=False)
        self.assertContains(response, "VENTAS DEL MES", html=False)
        self.assertContains(response, 'data-report-range="month"', html=False)
        self.assertContains(response, 'data-report-range="all"', html=False)
        self.assertContains(response, 'data-view="expenses"', html=False)
        self.assertContains(response, 'data-view="profits"', html=False)
        self.assertContains(response, "GASTO (CATEGORÍA Y DESCRIPCIÓN)", html=False)
        self.assertContains(response, 'class="responsive-product-table"', html=False)
        self.assertContains(response, "css/panel-products.css?v=28", html=False)
        self.assertContains(response, "js/panel.js?v=28", html=False)
        self.assertContains(response, 'data-filter="cancelled"', html=False)
        self.assertContains(response, 'data-filter="invoices-voided"', html=False)

    def test_invoice_admin_does_not_display_cancellation_email(self):
        order = Order.objects.create(
            customer_name="Ana",
            kind=Order.Kind.TAKEAWAY,
            payment_status=Order.PaymentStatus.PAID,
        )
        invoice = OrderInvoice.objects.create(
            order=order,
            number=f"F-{order.number}",
            status=OrderInvoice.Status.VOIDED,
            voided_by_email="private@example.test",
        )
        InvoiceCancellationRequest.objects.create(
            invoice=invoice,
            requested_by=self.admin_user,
            reason="Corrección",
            status=InvoiceCancellationRequest.Status.APPROVED,
            decided_by_email="private@example.test",
        )

        invoice_page = self.client.get(reverse("admin:orders_orderinvoice_changelist"))
        cancellation_page = self.client.get(
            reverse("admin:orders_invoicecancellationrequest_changelist")
        )

        self.assertEqual(invoice_page.status_code, 200)
        self.assertNotContains(invoice_page, "private@example.test")
        self.assertEqual(cancellation_page.status_code, 200)
        self.assertNotContains(cancellation_page, "private@example.test")

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


class StockReservationManagementTests(TestCase):
    def setUp(self):
        admin_user = get_user_model().objects.create_superuser(
            username="stock-admin",
            email="stock@example.test",
            password="stock-test-password",
        )
        self.client.force_login(admin_user)
        self.category = Category.objects.create(name="Bebidas")
        self.product = Product.objects.create(
            category=self.category,
            name="Agua",
            price=Decimal("2000"),
            stock_tracked=True,
            stock_quantity=5,
        )

    def create_reserved_order(self, quantity=2):
        self.product.stock_quantity -= quantity
        if self.product.stock_quantity == 0:
            self.product.available = False
        self.product.save(update_fields=["stock_quantity", "available"])
        order = Order.objects.create(
            customer_name="Cliente",
            kind=Order.Kind.TAKEAWAY,
        )
        item = OrderItem.objects.create(
            order=order,
            product=self.product,
            product_name=self.product.name,
            unit_price=self.product.price,
            quantity=quantity,
            stock_reserved=True,
        )
        return order, item

    def test_editing_and_deleting_unpaid_order_adjusts_reserved_stock(self):
        order, item = self.create_reserved_order(quantity=2)

        increased = self.client.patch(
            reverse("order-detail-api", args=[order.id]),
            data=json.dumps(
                {
                    "items": [
                        {
                            "item_id": item.id,
                            "product_id": self.product.id,
                            "quantity": 3,
                        }
                    ]
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(increased.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 2)

        reduced = self.client.patch(
            reverse("order-detail-api", args=[order.id]),
            data=json.dumps(
                {
                    "items": [
                        {
                            "item_id": item.id,
                            "product_id": self.product.id,
                            "quantity": 1,
                        }
                    ]
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(reduced.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 4)

        deleted = self.client.delete(reverse("order-detail-api", args=[order.id]))
        self.assertEqual(deleted.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 5)

    def test_cancellation_returns_stock_only_before_preparation(self):
        first_order, _ = self.create_reserved_order(quantity=2)
        cancelled = self.client.post(
            reverse("order-status-api", args=[first_order.id]),
            data=json.dumps({"status": Order.Status.CANCELLED, "reason": "Cliente desistió"}),
            content_type="application/json",
        )
        self.assertEqual(cancelled.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 5)

        preparing_order, _ = self.create_reserved_order(quantity=2)
        started = self.client.post(
            reverse("order-status-api", args=[preparing_order.id]),
            data=json.dumps({"status": Order.Status.PREPARING}),
            content_type="application/json",
        )
        cancelled_after_start = self.client.post(
            reverse("order-status-api", args=[preparing_order.id]),
            data=json.dumps({"status": Order.Status.CANCELLED, "reason": "Ya preparado"}),
            content_type="application/json",
        )
        self.assertEqual(started.status_code, 200)
        self.assertEqual(cancelled_after_start.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 3)


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
                    "stock_quantity": 12,
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
                    "stock_quantity": 8,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["product"]["price"], "9000.00")
        self.assertFalse(updated.json()["product"]["available"])
        self.assertEqual(updated.json()["product"]["stock_quantity"], 8)
        self.assertTrue(updated.json()["product"]["stock_tracked"])

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

    def test_beverage_inventory_is_required_and_cannot_be_disabled(self):
        missing_quantity = self.client.post(
            reverse("products-api"),
            data=json.dumps(
                {
                    "name": "Agua",
                    "category_id": self.category.id,
                    "price": "2500",
                    "stock_tracked": False,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(missing_quantity.status_code, 400)
        self.assertIn("existencias", missing_quantity.json()["error"].lower())

        created = self.client.post(
            reverse("products-api"),
            data=json.dumps(
                {
                    "name": "Agua",
                    "category_id": self.category.id,
                    "price": "2500",
                    "stock_tracked": False,
                    "stock_quantity": "24",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(created.status_code, 201)
        self.assertTrue(created.json()["product"]["stock_tracked"])
        self.assertEqual(created.json()["product"]["stock_quantity"], 24)

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


class BootstrapAdminCommandTests(TestCase):
    def test_bootstrap_command_creates_admin_only_when_configured_and_is_idempotent(
        self,
    ):
        credentials = {
            "DJANGO_BOOTSTRAP_ADMIN_USERNAME": "firstadmin",
            "DJANGO_BOOTSTRAP_ADMIN_EMAIL": "firstadmin@example.com",
            "DJANGO_BOOTSTRAP_ADMIN_PASSWORD": "V8!xP2#qL9@rT4$wK6",
        }
        with patch.dict("os.environ", credentials):
            call_command("bootstrap_admin", verbosity=0)
            user = get_user_model().objects.get(username="firstadmin")
            original_password = user.password

            call_command("bootstrap_admin", verbosity=0)

        user.refresh_from_db()
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(
            user.check_password(credentials["DJANGO_BOOTSTRAP_ADMIN_PASSWORD"])
        )
        self.assertEqual(user.password, original_password)
        self.assertEqual(user.email, credentials["DJANGO_BOOTSTRAP_ADMIN_EMAIL"])

    def test_bootstrap_command_skips_when_credentials_are_not_configured(self):
        with patch.dict(
            "os.environ",
            {
                "DJANGO_BOOTSTRAP_ADMIN_USERNAME": "",
                "DJANGO_BOOTSTRAP_ADMIN_PASSWORD": "",
                "DJANGO_BOOTSTRAP_ADMIN_EMAIL": "",
            },
        ):
            call_command("bootstrap_admin", verbosity=0)

        self.assertFalse(
            get_user_model().objects.filter(username="firstadmin").exists()
        )


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
