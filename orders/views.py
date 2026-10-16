import csv
import hashlib
import hmac
import json
import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.db.models import Count, F, Sum
from django.db.models.functions import TruncDate
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .models import (
    CashSession,
    Category,
    Order,
    OrderItem,
    OrderStatusLog,
    Product,
    ProductExtra,
)

logger = logging.getLogger(__name__)
CASH_DENOMINATIONS = (100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000)
LEGACY_PAYMENT_LABELS = {
    "transfer": "Transferencia (anterior)",
    "other": "Otro (anterior)",
}


def _money(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _json_body(request):
    try:
        return json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _order_dict(order):
    legacy_payment_labels = {
        "transfer": "Transferencia (anterior)",
        "other": "Otro (anterior)",
    }
    return {
        "id": order.id,
        "number": order.number,
        "customer_name": order.customer_name,
        "phone": order.phone,
        "kind": order.kind,
        "kind_label": order.get_kind_display(),
        "table_number": order.table_number,
        "address": order.address,
        "note": order.note,
        "status": order.status,
        "status_label": order.get_status_display(),
        "payment_method": order.payment_method,
        "payment_method_label": legacy_payment_labels.get(
            order.payment_method, order.get_payment_method_display()
        ),
        "payment_status": order.payment_status,
        "payment_status_label": order.get_payment_status_display(),
        "subtotal": str(order.subtotal),
        "delivery_fee": str(order.delivery_fee),
        "tax": str(order.tax),
        "total": str(order.total),
        "created_at": timezone.localtime(order.created_at).isoformat(),
        "paid_at": (
            timezone.localtime(order.paid_at).isoformat() if order.paid_at else None
        ),
        "items": [
            {
                "name": item.product_name,
                "quantity": item.quantity,
                "price": str(item.unit_price),
                "line_total": str(item.line_total),
                "extras": item.extras_snapshot,
                "instructions": item.instructions,
            }
            for item in order.items.all()
        ],
    }


def menu(request):
    return render(request, "orders/menu.html", _business_context())


@staff_member_required
def panel(request):
    return render(
        request,
        "orders/panel.html",
        {
            **_business_context(),
            "product_categories": Category.objects.order_by("sort_order", "name"),
        },
    )


def _business_context():
    return {
        "business_name": settings.BUSINESS_NAME,
        "currency": settings.BUSINESS_CURRENCY,
        "currency_symbol": settings.BUSINESS_CURRENCY_SYMBOL,
        "whatsapp": settings.BUSINESS_WHATSAPP,
        "delivery_fee": settings.BUSINESS_DELIVERY_FEE,
        "orders_open": _can_accept_orders(),
        "hours_label": settings.BUSINESS_HOURS_LABEL,
    }


def _can_accept_orders():
    return (
        settings.BUSINESS_ORDERS_OPEN
        and CashSession.objects.filter(closed_at__isnull=True).exists()
    )


@require_GET
def menu_api(request):
    categories = Category.objects.filter(active=True).prefetch_related(
        "products__extras"
    )
    return JsonResponse(
        {
            "categories": [
                {
                    "id": category.id,
                    "name": category.name,
                    "products": [
                        {
                            "id": product.id,
                            "name": product.name,
                            "description": product.description,
                            "price": str(product.price),
                            "featured": product.featured,
                            "extras": [
                                {
                                    "id": extra.id,
                                    "name": extra.name,
                                    "price": str(extra.price),
                                }
                                for extra in product.extras.filter(active=True)
                            ],
                        }
                        for product in category.products.filter(available=True)
                    ],
                }
                for category in categories
            ],
            "currency": settings.BUSINESS_CURRENCY,
            "symbol": settings.BUSINESS_CURRENCY_SYMBOL,
            "business_name": settings.BUSINESS_NAME,
            "whatsapp": settings.BUSINESS_WHATSAPP,
            "tax_rate": str(settings.BUSINESS_TAX_RATE),
            "delivery_fee": str(settings.BUSINESS_DELIVERY_FEE),
            "accepting_orders": _can_accept_orders(),
            "hours_label": settings.BUSINESS_HOURS_LABEL,
        }
    )


def _product_dict(product):
    return {
        "id": product.id,
        "name": product.name,
        "description": product.description,
        "category_id": product.category_id,
        "category_name": product.category.name,
        "price": str(product.price),
        "available": product.available,
        "featured": product.featured,
        "sold_count": product.sold_count,
    }


def _update_product(product, data, creating=False):
    if not isinstance(data, dict):
        return "Los datos del producto no son válidos."

    if creating or "name" in data:
        name = str(data.get("name", "")).strip()
        if not name:
            return "Escribe el nombre del producto."
        product.name = name[:120]
    if creating or "description" in data:
        product.description = str(data.get("description", "")).strip()[:240]
    if creating or "category_id" in data:
        try:
            product.category = Category.objects.get(pk=int(data.get("category_id")))
        except (Category.DoesNotExist, TypeError, ValueError):
            return "Selecciona una categoría válida."
    if creating or "price" in data:
        try:
            price = Decimal(str(data.get("price")))
            if not price.is_finite() or price < 0 or price > Decimal("99999999.99"):
                return "El precio debe ser un importe válido en COP."
            product.price = price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, TypeError, ValueError):
            return "Escribe un precio válido en COP."
    for field in ("available", "featured"):
        if creating or field in data:
            value = data.get(field, field == "available")
            if not isinstance(value, bool):
                return "La disponibilidad y el destacado deben ser valores de sí/no."
            setattr(product, field, value)
    product.save()
    return None


@staff_member_required
@require_http_methods(["GET", "POST"])
def products_api(request):
    if request.method == "GET":
        categories = Category.objects.order_by("sort_order", "name")
        products = Product.objects.select_related("category").annotate(
            sold_count=Count("sold_items", distinct=True)
        )
        return JsonResponse(
            {
                "categories": [
                    {
                        "id": category.id,
                        "name": category.name,
                        "active": category.active,
                    }
                    for category in categories
                ],
                "products": [_product_dict(product) for product in products],
            }
        )

    data = _json_body(request)
    product = Product()
    error = _update_product(product, data, creating=True)
    if error:
        return JsonResponse({"error": error}, status=400)
    product.sold_count = 0
    return JsonResponse({"product": _product_dict(product)}, status=201)


@staff_member_required
@require_http_methods(["PATCH", "PUT", "DELETE"])
def product_detail_api(request, product_id):
    product = get_object_or_404(
        Product.objects.select_related("category").annotate(
            sold_count=Count("sold_items", distinct=True)
        ),
        pk=product_id,
    )
    if request.method == "DELETE":
        if product.sold_count:
            product.available = False
            product.save(update_fields=["available"])
            return JsonResponse({"deleted": False, "archived": True})
        product.delete()
        return JsonResponse({"deleted": True, "archived": False})

    data = _json_body(request)
    error = _update_product(product, data, creating=False)
    if error:
        return JsonResponse({"error": error}, status=400)
    return JsonResponse({"product": _product_dict(product)})


@require_http_methods(["GET", "POST"])
def orders_api(request):
    if request.method == "GET":
        if not request.user.is_authenticated or not request.user.is_staff:
            return JsonResponse({"error": "No autorizado"}, status=403)
        queryset = Order.objects.prefetch_related("items")
        number = request.GET.get("number", "").strip()[:16]
        date_from_value = request.GET.get("date_from", "").strip()
        date_to_value = request.GET.get("date_to", "").strip()
        try:
            date_from = parse_date(date_from_value) if date_from_value else None
            date_to = parse_date(date_to_value) if date_to_value else None
        except ValueError:
            return JsonResponse({"error": "El rango de fechas no es válido."}, status=400)
        if (date_from_value and date_from is None) or (date_to_value and date_to is None):
            return JsonResponse({"error": "El rango de fechas no es válido."}, status=400)
        if date_from and date_to and date_from > date_to:
            return JsonResponse(
                {"error": "La fecha inicial no puede ser posterior a la fecha final."},
                status=400,
            )
        if number:
            queryset = queryset.filter(number__icontains=number)
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)
        if not (number or date_from or date_to):
            queryset = queryset[:100]
        orders = list(queryset)
        return JsonResponse({"orders": [_order_dict(order) for order in orders]})

    data = _json_body(request)
    if not _can_accept_orders():
        return JsonResponse(
            {
                "error": "No estamos recibiendo pedidos: el administrador debe abrir la caja del turno primero."
            },
            status=503,
        )
    if not isinstance(data, dict):
        return JsonResponse(
            {"error": "El pedido no tiene un formato válido."}, status=400
        )
    name = str(data.get("customer_name", "")).strip()[:120]
    kind = data.get("kind")
    items = data.get("items")
    if (
        not name
        or kind not in Order.Kind.values
        or not isinstance(items, list)
        or not items
    ):
        return JsonResponse(
            {"error": "Completa tu nombre, el tipo de pedido y al menos un producto."},
            status=400,
        )
    if kind == Order.Kind.TABLE and not str(data.get("table_number", "")).strip():
        return JsonResponse({"error": "Indica el número de mesa."}, status=400)
    if kind == Order.Kind.DELIVERY and not str(data.get("address", "")).strip():
        return JsonResponse({"error": "Indica la dirección de entrega."}, status=400)
    phone = str(data.get("phone", "")).strip()
    if kind == Order.Kind.DELIVERY and not phone:
        return JsonResponse(
            {"error": "Indica el teléfono de contacto para el domicilio."}, status=400
        )

    if len(items) > 50 or any(not isinstance(row, dict) for row in items):
        return JsonResponse(
            {"error": "El pedido contiene demasiados productos o datos no válidos."},
            status=400,
        )
    try:
        product_ids = {int(row.get("product_id")) for row in items}
        for row in items:
            extra_ids = row.get("extra_ids", [])
            if not isinstance(extra_ids, list) or len(extra_ids) > 10:
                raise ValueError
            row["extra_ids"] = [int(extra_id) for extra_id in extra_ids]
    except (TypeError, ValueError):
        return JsonResponse(
            {"error": "Revisa los productos y extras seleccionados."}, status=400
        )
    products = {
        product.id: product
        for product in Product.objects.filter(id__in=product_ids, available=True)
    }
    if len(products) != len(product_ids):
        return JsonResponse(
            {
                "error": "Uno de los productos ya no está disponible. Actualiza la carta."
            },
            status=400,
        )

    parsed_items = []
    subtotal = Decimal("0")
    try:
        for row in items:
            product = products[int(row["product_id"])]
            quantity = int(row.get("quantity", 1))
            if quantity < 1 or quantity > 30:
                raise ValueError
            extra_ids = row["extra_ids"]
            extras = list(
                ProductExtra.objects.filter(
                    product=product, active=True, id__in=extra_ids
                )
            )
            if len(extras) != len(set(extra_ids)):
                return JsonResponse(
                    {"error": "Uno de los extras seleccionados ya no está disponible."},
                    status=400,
                )
            extra_total = sum((extra.price for extra in extras), Decimal("0"))
            instructions = str(row.get("instructions", "")).strip()[:180]
            parsed_items.append((product, quantity, instructions, extras, extra_total))
            subtotal += (product.price + extra_total) * quantity
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return JsonResponse({"error": "Revisa las cantidades del pedido."}, status=400)

    delivery_fee = (
        _money(settings.BUSINESS_DELIVERY_FEE)
        if kind == Order.Kind.DELIVERY
        else Decimal("0")
    )
    tax_rate = Decimal(settings.BUSINESS_TAX_RATE)
    tax = _money(subtotal * tax_rate / Decimal("100"))
    subtotal = _money(subtotal)
    total = subtotal + delivery_fee + tax
    with transaction.atomic():
        order = Order.objects.create(
            customer_name=name,
            phone=phone[:32],
            kind=kind,
            table_number=str(data.get("table_number", "")).strip()[:12],
            address=str(data.get("address", "")).strip()[:240],
            note=str(data.get("note", "")).strip()[:300],
            payment_method=(
                data.get("payment_method")
                if data.get("payment_method") in Order.PaymentMethod.values
                else Order.PaymentMethod.CASH
            ),
            subtotal=subtotal,
            delivery_fee=delivery_fee,
            tax=tax,
            total=total,
        )
        OrderItem.objects.bulk_create(
            [
                OrderItem(
                    order=order,
                    product=product,
                    product_name=product.name,
                    unit_price=product.price,
                    extra_total=extra_total,
                    extras_snapshot=[
                        {"name": extra.name, "price": str(extra.price)}
                        for extra in extras
                    ],
                    quantity=quantity,
                    instructions=instructions,
                )
                for product, quantity, instructions, extras, extra_total in parsed_items
            ]
        )
    return JsonResponse({"order": _order_dict(order)}, status=201)


@staff_member_required
@require_POST
def order_status_api(request, order_id):
    data = _json_body(request)
    if not isinstance(data, dict) or data.get("status") not in Order.Status.values:
        return JsonResponse({"error": "Estado no válido."}, status=400)
    order = Order.objects.get(pk=order_id)
    old_status = order.status
    order.status = data["status"]
    with transaction.atomic():
        order.save(update_fields=["status", "updated_at"])
        OrderStatusLog.objects.create(
            order=order,
            previous_status=old_status,
            new_status=order.status,
            changed_by=request.user,
        )
    return JsonResponse({"order": _order_dict(order)})


@staff_member_required
@require_POST
def order_payment_api(request, order_id):
    data = _json_body(request)
    if not isinstance(data, dict):
        return JsonResponse({"error": "Solicitud no válida."}, status=400)
    order = Order.objects.get(pk=order_id)
    method = data.get("payment_method")
    if method not in Order.PaymentMethod.values:
        return JsonResponse({"error": "Método de pago no válido."}, status=400)
    order.payment_method = method
    order.payment_status = (
        Order.PaymentStatus.PAID if data.get("paid") else Order.PaymentStatus.PENDING
    )
    order.paid_at = timezone.now() if data.get("paid") else None
    order.save(
        update_fields=["payment_method", "payment_status", "paid_at", "updated_at"]
    )
    return JsonResponse({"order": _order_dict(order)})


@staff_member_required
@require_http_methods(["GET", "POST"])
def cash_api(request):
    if request.method == "GET":
        session = CashSession.objects.filter(closed_at__isnull=True).first()
        if not session:
            return JsonResponse({"session": None, "history": _cash_history()})
        return JsonResponse(
            {"session": _cash_dict(session), "history": _cash_history()}
        )
    data = _json_body(request)
    if not isinstance(data, dict):
        return JsonResponse({"error": "Solicitud no válida."}, status=400)
    try:
        with transaction.atomic():
            session = CashSession.objects.filter(closed_at__isnull=True).first()
            if data.get("action") == "open":
                if session:
                    return JsonResponse(
                        {"error": "Ya hay una caja abierta."}, status=409
                    )
                amount = _money(data.get("amount", "0"))
                if amount < 0:
                    raise InvalidOperation
                session = CashSession.objects.create(
                    opened_by=request.user, opening_amount=amount
                )
                return JsonResponse({"session": _cash_dict(session)}, status=201)
            if data.get("action") == "close":
                if not session:
                    return JsonResponse(
                        {"error": "No hay una caja abierta."}, status=409
                    )
                denomination_counts = data.get("denominations")
                if denomination_counts is not None:
                    if not isinstance(denomination_counts, dict):
                        return JsonResponse(
                            {"error": "El desglose de denominaciones no es válido."},
                            status=400,
                        )
                    normalized_counts = {}
                    for denomination in CASH_DENOMINATIONS:
                        count = denomination_counts.get(str(denomination), 0)
                        if (
                            isinstance(count, bool)
                            or not isinstance(count, int)
                            or count < 0
                            or count > 1000000
                        ):
                            return JsonResponse(
                                {
                                    "error": "Ingresa cantidades enteras no negativas para cada denominación."
                                },
                                status=400,
                            )
                        normalized_counts[str(denomination)] = count
                    if any(
                        str(key) not in {str(value) for value in CASH_DENOMINATIONS}
                        for key in denomination_counts
                    ):
                        return JsonResponse(
                            {
                                "error": "Se recibió una denominación de efectivo no permitida."
                            },
                            status=400,
                        )
                    amount = Decimal(
                        sum(
                            int(denomination) * count
                            for denomination, count in normalized_counts.items()
                        )
                    )
                    session.counted_denominations = normalized_counts
                else:
                    amount = _money(data.get("counted_amount", "0"))
                if amount < 0:
                    raise InvalidOperation
                expected_payments = session.payment_totals()
                verified_payments = data.get("verified_payments", {})
                if not isinstance(verified_payments, dict):
                    return JsonResponse(
                        {
                            "error": "Los importes comprobados por medio de pago no son válidos."
                        },
                        status=400,
                    )
                allowed_payment_labels = {
                    label
                    for _, label in Order.PaymentMethod.choices
                    if label != "Efectivo"
                } | set(LEGACY_PAYMENT_LABELS.values())
                if any(
                    label not in allowed_payment_labels for label in verified_payments
                ):
                    return JsonResponse(
                        {"error": "Se recibió un método de pago no reconocido."},
                        status=400,
                    )
                normalized_verified = {}
                for label in allowed_payment_labels:
                    raw_value = verified_payments.get(label)
                    expected_value = expected_payments.get(label, Decimal("0"))
                    if raw_value in (None, ""):
                        if expected_value > 0:
                            return JsonResponse(
                                {"error": f"Confirma el valor comprobado de {label}."},
                                status=400,
                            )
                        actual_value = Decimal("0")
                    else:
                        actual_value = _money(raw_value)
                    if actual_value != actual_value.to_integral_value():
                        return JsonResponse(
                            {
                                "error": f"El valor comprobado de {label} debe expresarse en pesos enteros (COP)."
                            },
                            status=400,
                        )
                    if actual_value < 0 or actual_value > Decimal("999999999999"):
                        return JsonResponse(
                            {
                                "error": f"El valor de {label} debe ser un importe válido y no negativo."
                            },
                            status=400,
                        )
                    normalized_verified[label] = str(actual_value)
                session.payment_totals_snapshot = {
                    key: str(value) for key, value in expected_payments.items()
                }
                session.verified_payment_totals = normalized_verified
                session.counted_amount = amount
                session.closed_at = timezone.now()
                session.closed_by = request.user
                session.reconciled_at = session.closed_at
                session.reconciled_by = request.user
                session.save(
                    update_fields=[
                        "counted_denominations",
                        "payment_totals_snapshot",
                        "verified_payment_totals",
                        "counted_amount",
                        "closed_at",
                        "closed_by",
                        "reconciled_at",
                        "reconciled_by",
                    ]
                )
                return JsonResponse({"session": _cash_dict(session)})
    except (InvalidOperation, TypeError, ValueError):
        return JsonResponse({"error": "Ingresa un importe válido."}, status=400)
    return JsonResponse({"error": "Acción no válida."}, status=400)


@staff_member_required
@require_POST
def cash_reconciliation_api(request, session_id):
    data = _json_body(request)
    if not isinstance(data, dict) or not isinstance(
        data.get("verified_payments"), dict
    ):
        return JsonResponse(
            {"error": "Los importes comprobados no son válidos."}, status=400
        )
    session = get_object_or_404(CashSession, pk=session_id)
    if session.is_open:
        return JsonResponse(
            {"error": "Este turno sigue abierto; usa el cierre de caja."}, status=409
        )
    if session.reconciled_at:
        return JsonResponse(
            {"error": "Este cierre ya tiene una conciliación guardada."}, status=409
        )

    expected_payments = session.payment_totals()
    allowed_labels = {
        label for _, label in Order.PaymentMethod.choices if label != "Efectivo"
    }
    allowed_labels.update(LEGACY_PAYMENT_LABELS.values())
    supplied = data["verified_payments"]
    if any(label not in allowed_labels for label in supplied):
        return JsonResponse(
            {"error": "Se recibió un método de pago no reconocido."}, status=400
        )

    normalized = {}
    try:
        for label in allowed_labels:
            expected = expected_payments.get(label, Decimal("0"))
            raw_value = supplied.get(label)
            if raw_value in (None, ""):
                if expected > 0:
                    return JsonResponse(
                        {"error": f"Confirma el valor comprobado de {label}."},
                        status=400,
                    )
                amount = Decimal("0")
            else:
                amount = _money(raw_value)
            if amount != amount.to_integral_value():
                return JsonResponse(
                    {
                        "error": f"El valor comprobado de {label} debe expresarse en pesos enteros (COP)."
                    },
                    status=400,
                )
            if amount < 0 or amount > Decimal("999999999999"):
                return JsonResponse(
                    {
                        "error": f"El valor de {label} debe ser un importe válido y no negativo."
                    },
                    status=400,
                )
            normalized[label] = str(amount)
    except (InvalidOperation, TypeError, ValueError):
        return JsonResponse(
            {"error": "Ingresa importes válidos en pesos colombianos."}, status=400
        )

    session.verified_payment_totals = normalized
    session.reconciled_at = timezone.now()
    session.reconciled_by = request.user
    session.save(
        update_fields=["verified_payment_totals", "reconciled_at", "reconciled_by"]
    )
    return JsonResponse({"session": _cash_dict(session)})


def _cash_reconciliation(session):
    expected_sales = {
        key: Decimal(value) for key, value in session.payment_totals().items()
    }
    verified_sales = {
        key: Decimal(value) for key, value in session.verified_payment_totals.items()
    }
    method_labels = [label for _, label in Order.PaymentMethod.choices]
    method_labels.extend(
        label for label in LEGACY_PAYMENT_LABELS.values() if label in expected_sales
    )
    method_labels.extend(
        label for label in expected_sales if label not in method_labels
    )
    closed = not session.is_open
    rows = []

    for label in method_labels:
        sales_expected = expected_sales.get(label, Decimal("0"))
        is_cash = label == "Efectivo"
        expected = (
            session.opening_amount + sales_expected if is_cash else sales_expected
        )
        if is_cash:
            actual = session.counted_amount if closed else None
        elif not closed:
            actual = None
        elif label in verified_sales:
            actual = verified_sales[label]
        elif sales_expected == 0:
            actual = Decimal("0")
        else:
            actual = None
        difference = actual - expected if actual is not None else None
        rows.append(
            {
                "method": label,
                "expected": str(expected),
                "actual": str(actual) if actual is not None else None,
                "difference": str(difference) if difference is not None else None,
                "status": (
                    _difference_status(difference)
                    if difference is not None
                    else "pending"
                ),
                "reason": (
                    _difference_reason(label, difference)
                    if difference is not None
                    else "Falta el importe verificado para este medio."
                ),
            }
        )

    missing_verification = any(
        row["method"] != "Efectivo"
        and Decimal(row["expected"]) > 0
        and row["actual"] is None
        for row in rows
    )
    expected_total = sum(expected_sales.values(), Decimal("0"))
    actual_total = None
    total_difference = None
    if closed and not missing_verification and session.counted_amount is not None:
        actual_total = session.counted_amount - session.opening_amount
        actual_total += sum(
            (
                verified_sales.get(row["method"], Decimal("0"))
                for row in rows
                if row["method"] != "Efectivo"
            ),
            Decimal("0"),
        )
        total_difference = actual_total - expected_total

    return {
        "complete": closed and not missing_verification,
        "expected_sales": str(expected_total),
        "actual_sales": str(actual_total) if actual_total is not None else None,
        "difference": str(total_difference) if total_difference is not None else None,
        "status": (
            _difference_status(total_difference)
            if total_difference is not None
            else "pending"
        ),
        "reason": (
            _difference_reason("total", total_difference)
            if total_difference is not None
            else "Conciliación pendiente de importes comprobados."
        ),
        "methods": rows,
    }


def _difference_status(difference):
    if difference > 0:
        return "surplus"
    if difference < 0:
        return "shortage"
    return "matched"


def _difference_reason(method, difference):
    if difference == 0:
        return "El valor comprobado coincide con el valor esperado."
    if method == "Efectivo":
        if difference > 0:
            return "Sobrante: puede haber cambio no entregado, una venta no registrada, un fondo inicial incorrecto o un error de conteo."
        return "Faltante: revisa cambio entregado, conteo, cobros pendientes o pagos marcados en efectivo que no ingresaron a la caja."
    if difference > 0:
        return "Sobrante: revisa pagos duplicados, ventas no registradas o un importe/método asignado incorrectamente."
    return "Faltante: revisa pagos rechazados o pendientes, devoluciones, método asignado y comisiones. Compara el valor bruto, no el depósito neto."


def _cash_dict(session):
    return {
        "id": session.id,
        "opened_at": timezone.localtime(session.opened_at).isoformat(),
        "opened_by": session.opened_by.username if session.opened_by else None,
        "closed_at": (
            timezone.localtime(session.closed_at).isoformat()
            if session.closed_at
            else None
        ),
        "closed_by": session.closed_by.username if session.closed_by else None,
        "opening_amount": str(session.opening_amount),
        "is_open": session.is_open,
        "expected_cash": str(session.expected_cash),
        "counted_amount": str(session.counted_amount or 0),
        "counted_denominations": session.counted_denominations,
        "verified_payment_totals": session.verified_payment_totals,
        "reconciled_at": (
            timezone.localtime(session.reconciled_at).isoformat()
            if session.reconciled_at
            else None
        ),
        "reconciled_by": (
            session.reconciled_by.username if session.reconciled_by else None
        ),
        "reconciliation": _cash_reconciliation(session),
        "difference": str(session.difference or 0),
        "payment_totals": {k: str(v) for k, v in session.payment_totals().items()},
    }


def _cash_history():
    return [
        _cash_dict(row)
        for row in CashSession.objects.filter(closed_at__isnull=False)
    ]


def _report_data(start, end):
    orders = Order.objects.filter(
        created_at__date__gte=start, created_at__date__lte=end
    ).exclude(status=Order.Status.CANCELLED)
    paid = orders.filter(payment_status=Order.PaymentStatus.PAID)
    by_method = paid.values("payment_method").annotate(
        total=Sum("total"), count=Count("id")
    )
    labels = dict(Order.PaymentMethod.choices)
    labels.update({"transfer": "Transferencia (anterior)", "other": "Otro (anterior)"})
    product_sales = list(
        OrderItem.objects.filter(order__in=paid)
        .values("product_name")
        .annotate(
            units_sold=Sum("quantity"),
            revenue=Sum((F("unit_price") + F("extra_total")) * F("quantity")),
        )
    )
    top_products = sorted(
        product_sales, key=lambda row: (-row["units_sold"], row["product_name"])
    )[:8]
    sold_names = {row["product_name"] for row in product_sales}
    least_candidates = product_sales + [
        {"product_name": name, "units_sold": 0, "revenue": Decimal("0")}
        for name in Product.objects.values_list("name", flat=True).distinct()
        if name not in sold_names
    ]
    least_products = sorted(
        least_candidates, key=lambda row: (row["units_sold"], row["product_name"])
    )[:8]
    daily_rows = (
        paid.annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(total=Sum("total"))
    )
    daily_totals = {str(row["day"]): row["total"] or Decimal("0") for row in daily_rows}
    daily_sales = [
        {
            "date": (start + timedelta(days=offset)).isoformat(),
            "total": str(
                daily_totals.get(
                    (start + timedelta(days=offset)).isoformat(), Decimal("0")
                )
            ),
        }
        for offset in range((end - start).days + 1)
    ]
    return {
        "start": str(start),
        "end": str(end),
        "order_count": orders.count(),
        "sales_total": str(paid.aggregate(total=Sum("total"))["total"] or Decimal("0")),
        "pending_total": str(
            orders.filter(payment_status=Order.PaymentStatus.PENDING).aggregate(
                total=Sum("total")
            )["total"]
            or Decimal("0")
        ),
        "by_method": [
            {
                "method": labels[row["payment_method"]],
                "total": str(row["total"] or 0),
                "count": row["count"],
            }
            for row in by_method
        ],
        "daily_sales": daily_sales,
        "top_products": [
            {
                "name": row["product_name"],
                "quantity": row["units_sold"],
                "revenue": str(row["revenue"] or 0),
            }
            for row in top_products
        ],
        "least_products": [
            {
                "name": row["product_name"],
                "quantity": row["units_sold"],
                "revenue": str(row["revenue"] or 0),
            }
            for row in least_products
        ],
    }


@staff_member_required
@require_GET
def reports_api(request):
    today = timezone.localdate()
    try:
        start = date.fromisoformat(
            request.GET.get("start", str(today - timedelta(days=6)))
        )
        end = date.fromisoformat(request.GET.get("end", str(today)))
        if end < start or (end - start).days > 366:
            raise ValueError
    except ValueError:
        return JsonResponse(
            {"error": "Selecciona un rango válido de hasta un año."}, status=400
        )
    return JsonResponse(_report_data(start, end))


@staff_member_required
@require_GET
def reports_csv(request):
    today = timezone.localdate()
    try:
        start = date.fromisoformat(
            request.GET.get("start", str(today - timedelta(days=6)))
        )
        end = date.fromisoformat(request.GET.get("end", str(today)))
        if end < start or (end - start).days > 366:
            raise ValueError
    except ValueError:
        return HttpResponse("Rango de fechas no válido", status=400)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="ventas-{start}-{end}.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(
        [
            "Pedido",
            "Fecha",
            "Cliente",
            "Tipo",
            "Estado",
            "Método de pago",
            "Pago",
            "Total",
        ]
    )
    for order in Order.objects.filter(
        created_at__date__gte=start, created_at__date__lte=end
    ).order_by("created_at"):
        writer.writerow(
            [
                order.number,
                timezone.localtime(order.created_at).strftime("%Y-%m-%d %H:%M"),
                order.customer_name,
                order.get_kind_display(),
                order.get_status_display(),
                order.get_payment_method_display(),
                order.get_payment_status_display(),
                order.total,
            ]
        )
    return response


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp_webhook(request):
    if request.method == "GET":
        if not settings.WHATSAPP_VERIFY_TOKEN:
            return HttpResponse("Webhook de WhatsApp no configurado", status=503)
        if request.GET.get("hub.mode") == "subscribe" and hmac.compare_digest(
            request.GET.get("hub.verify_token", ""), settings.WHATSAPP_VERIFY_TOKEN
        ):
            return HttpResponse(
                request.GET.get("hub.challenge", ""), content_type="text/plain"
            )
        return HttpResponse("Verificación inválida", status=403)

    if (
        not settings.WHATSAPP_APP_SECRET
        or not settings.WHATSAPP_ACCESS_TOKEN
        or not settings.WHATSAPP_PHONE_NUMBER_ID
    ):
        return HttpResponse(status=503)
    signature = request.headers.get("X-Hub-Signature-256", "")
    expected = (
        "sha256="
        + hmac.new(
            settings.WHATSAPP_APP_SECRET.encode(), request.body, hashlib.sha256
        ).hexdigest()
    )
    if not hmac.compare_digest(signature, expected):
        return HttpResponse(status=403)
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse(status=400)

    recipients = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for message in change.get("value", {}).get("messages", []):
                if message.get("from"):
                    recipients.append(message["from"])
    for recipient in recipients:
        message = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {
                "preview_url": True,
                "body": f"¡Hola! Aquí puedes consultar nuestra carta y hacer tu pedido: {settings.PUBLIC_SITE_URL}/",
            },
        }
        url = (
            f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/"
            f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
        )
        outbound = Request(
            url,
            data=json.dumps(message).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(outbound, timeout=8) as response:
                response.read()
        except (HTTPError, URLError, TimeoutError) as error:
            logger.warning("No se pudo responder al mensaje de WhatsApp: %s", error)
            return HttpResponse(status=502)
    return HttpResponse(status=200)
