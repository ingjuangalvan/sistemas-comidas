import csv
import hashlib
import hmac
import io
import json
import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce, TruncDate, TruncMonth
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .models import (
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
    invoice = getattr(order, "invoice", None)
    status_history = list(order.status_history.all())
    cancellation_log = next(
        (
            entry
            for entry in reversed(status_history)
            if entry.new_status == Order.Status.CANCELLED
        ),
        None,
    )
    current_status_log = next(
        (
            entry
            for entry in reversed(status_history)
            if entry.new_status == order.status
        ),
        None,
    )
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
        "status_since": timezone.localtime(
            current_status_log.changed_at if current_status_log else order.created_at
        ).isoformat(),
        "cancellation_reason": (
            cancellation_log.reason if cancellation_log else ""
        ),
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
        "invoice": (
            {
                "number": invoice.number,
                "status": invoice.status,
                "created_at": timezone.localtime(invoice.created_at).isoformat(),
                "cash_received": (
                    str(invoice.cash_received) if invoice.cash_received is not None else None
                ),
                "change_given": str(invoice.change_given),
                "not_refunded": invoice.status == OrderInvoice.Status.VOIDED,
                "voided_at": (
                    timezone.localtime(invoice.voided_at).isoformat()
                    if invoice.voided_at
                    else None
                ),
                "void_reason": next(
                    (
                        item.reason
                        for item in invoice.cancellation_requests.all()
                        if item.status == InvoiceCancellationRequest.Status.APPROVED
                    ),
                    None,
                ),
            }
            if invoice
            else None
        ),
        "items": [
            {
                "id": item.id,
                "product_id": item.product_id,
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
    return render(
        request,
        "orders/menu.html",
        {**_business_context(), "table_numbers": range(1, 11)},
    )


def public_menu(request):
    return render(request, "orders/public_menu.html", _business_context())


@require_GET
def public_menu_qr(request):
    try:
        import qrcode
        from qrcode.image.svg import SvgPathImage
    except ImportError:
        return JsonResponse(
            {
                "error": (
                    "No está instalada la dependencia para generar el QR. "
                    "Ejecuta python -m pip install -r requirements.txt."
                )
            },
            status=503,
        )

    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(request.build_absolute_uri(reverse("public-menu")))
    qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    output = io.BytesIO()
    image.save(output)
    response = HttpResponse(output.getvalue(), content_type="image/svg+xml")
    response["Content-Disposition"] = 'attachment; filename="carta-qr.svg"'
    response["Cache-Control"] = "no-store"
    return response


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
                            "stock_tracked": product.stock_tracked,
                            "stock_quantity": product.stock_quantity,
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
        "stock_tracked": product.stock_tracked,
        "stock_quantity": product.stock_quantity,
        "sold_count": product.sold_count,
    }


def _change_stock_reservations(reservation_deltas):
    """Apply reservation increases as deductions and decreases as returns."""
    product_ids = [product_id for product_id, delta in reservation_deltas.items() if delta]
    products = {
        product.id: product
        for product in Product.objects.select_for_update()
        .filter(id__in=product_ids)
        .order_by("id")
    }
    if len(products) != len(product_ids):
        return "No se encontró un producto para actualizar sus existencias."

    for product_id, delta in reservation_deltas.items():
        if not delta:
            continue
        product = products[product_id]
        if product.stock_quantity is None:
            return f"Configura las existencias de {product.name} antes de tomar pedidos."
        if delta > 0 and product.stock_quantity < delta:
            return f"Existencias insuficientes de {product.name}: quedan {product.stock_quantity}."

    for product_id, delta in reservation_deltas.items():
        if not delta:
            continue
        product = products[product_id]
        previous_quantity = product.stock_quantity
        product.stock_quantity -= delta
        update_fields = ["stock_quantity"]
        if product.stock_quantity == 0:
            product.available = False
            update_fields.append("available")
        elif previous_quantity == 0 and product.stock_quantity > 0:
            product.available = True
            update_fields.append("available")
        product.save(update_fields=update_fields)
    return None


def _update_product(product, data, creating=False):
    if not isinstance(data, dict):
        return "Los datos del producto no son válidos."
    previous_stock_quantity = product.stock_quantity

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
    if creating or "stock_tracked" in data:
        stock_tracked = data.get(
            "stock_tracked",
            "bebida" in product.category.name.casefold() if creating else False,
        )
        if not isinstance(stock_tracked, bool):
            return "El control de existencias debe ser sí o no."
        product.stock_tracked = (
            stock_tracked or "bebida" in product.category.name.casefold()
        )
    if creating or "stock_quantity" in data:
        raw_quantity = data.get("stock_quantity")
        if raw_quantity in (None, ""):
            if product.stock_tracked:
                return "Indica las existencias iniciales del producto."
            product.stock_quantity = None
        else:
            try:
                quantity_text = str(raw_quantity).strip()
                if isinstance(raw_quantity, bool) or not quantity_text.isdecimal():
                    return "Las existencias deben ser un número entero no negativo."
                stock_quantity = int(quantity_text)
                if stock_quantity > 2147483647:
                    return "Las existencias superan el límite permitido."
                product.stock_quantity = stock_quantity
            except (TypeError, ValueError):
                return "Las existencias deben ser un número entero no negativo."
    elif (
        "stock_tracked" in data
        and product.stock_tracked
        and product.stock_quantity is None
    ):
        return "Indica las existencias actuales del producto."
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
    if (
        not creating
        and data.get("available") is True
        and product.stock_tracked
        and (product.stock_quantity is None or product.stock_quantity == 0)
    ):
        return "Registra existencias antes de volver a ofrecer este producto."
    if (
        product.stock_tracked
        and previous_stock_quantity == 0
        and product.stock_quantity is not None
        and product.stock_quantity > 0
        and "available" not in data
    ):
        product.available = True
    if product.stock_tracked and product.stock_quantity == 0:
        product.available = False
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
        queryset = Order.objects.prefetch_related(
            "items", "invoice__cancellation_requests", "status_history"
        )
        scope = request.GET.get("scope", "history").strip()
        if scope == "active":
            active_orders = queryset.filter(
                status__in=[
                    Order.Status.RECEIVED,
                    Order.Status.PREPARING,
                    Order.Status.READY,
                ]
            )
            return JsonResponse(
                {"orders": [_order_dict(order) for order in active_orders]}
            )
        if scope != "history":
            return JsonResponse(
                {"error": "La vista solicitada no es válida."}, status=400
            )

        number = request.GET.get("number", "").strip()[:16]
        status = request.GET.get("status", "").strip()
        invoice_status = request.GET.get("invoice_status", "").strip()
        date_from_value = request.GET.get("date_from", "").strip()
        date_to_value = request.GET.get("date_to", "").strip()
        if status and status not in Order.Status.values:
            return JsonResponse(
                {"error": "El estado del pedido no es válido."}, status=400
            )
        if invoice_status not in ("", OrderInvoice.Status.VOIDED):
            return JsonResponse(
                {"error": "El estado del comprobante no es válido."}, status=400
            )
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
        if status:
            queryset = queryset.filter(status=status)
        if invoice_status:
            queryset = queryset.filter(invoice__status=invoice_status)
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)
        try:
            page_number = int(request.GET.get("page", "1"))
            if page_number < 1:
                raise ValueError
        except ValueError:
            return JsonResponse(
                {"error": "El número de página no es válido."}, status=400
            )

        paginator = Paginator(queryset, 10)
        page = paginator.get_page(page_number)

        today = timezone.localdate()
        today_orders = Order.objects.filter(created_at__date=today)
        today_paid = today_orders.filter(payment_status=Order.PaymentStatus.PAID)
        month_start = today.replace(day=1)
        month_paid = Order.objects.filter(
            payment_status=Order.PaymentStatus.PAID
        ).filter(
            Q(paid_at__date__gte=month_start, paid_at__date__lte=today)
            | Q(
                paid_at__isnull=True,
                created_at__date__gte=month_start,
                created_at__date__lte=today,
            )
        )
        recent_orders = today_orders.order_by("-created_at")[:6]
        summary = {
            "order_count": today_orders.count(),
            "sales_total": str(today_paid.aggregate(total=Sum("total"))["total"] or 0),
            "month_sales_total": str(
                month_paid.aggregate(total=Sum("total"))["total"] or 0
            ),
            "month_paid_order_count": month_paid.count(),
            "month_start": str(month_start),
            "pending_count": today_orders.filter(
                payment_status=Order.PaymentStatus.PENDING
            ).exclude(status=Order.Status.CANCELLED).count(),
            "active_count": Order.objects.filter(
                status__in=[
                    Order.Status.RECEIVED,
                    Order.Status.PREPARING,
                    Order.Status.READY,
                ]
            ).count(),
            "voided_invoice_count": today_paid.filter(
                invoice__status=OrderInvoice.Status.VOIDED
            ).count(),
            "voided_invoice_total": str(
                today_paid.filter(
                    invoice__status=OrderInvoice.Status.VOIDED
                ).aggregate(total=Sum("total"))["total"]
                or 0
            ),
            "recent_orders": [
                {
                    "id": order.id,
                    "number": order.number,
                    "customer_name": order.customer_name,
                    "kind_label": order.get_kind_display(),
                    "status": order.status,
                    "status_label": order.get_status_display(),
                    "total": str(order.total),
                    "created_at": timezone.localtime(order.created_at).isoformat(),
                }
                for order in recent_orders
            ],
        }
        return JsonResponse(
            {
                "orders": [_order_dict(order) for order in page.object_list],
                "pagination": {
                    "page": page.number,
                    "pages": paginator.num_pages,
                    "total": paginator.count,
                },
                "summary": summary,
            }
        )

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
    table_number = ""
    if kind == Order.Kind.TABLE:
        raw_table_number = str(data.get("table_number", "")).strip()
        if not raw_table_number:
            return JsonResponse({"error": "Selecciona el número de mesa."}, status=400)
        if not raw_table_number.isdecimal() or not 1 <= int(raw_table_number) <= 10:
            return JsonResponse(
                {"error": "El número de mesa debe estar entre 1 y 10."},
                status=400,
            )
        table_number = str(int(raw_table_number))
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
        locked_products = {
            product.id: product
            for product in Product.objects.select_for_update()
            .filter(id__in=product_ids)
            .order_by("id")
        }
        if len(locked_products) != len(product_ids) or any(
            not product.available for product in locked_products.values()
        ):
            return JsonResponse(
                {"error": "Uno de los productos ya no está disponible. Actualiza la carta."},
                status=409,
            )
        stock_deltas = {}
        for product, quantity, _, _, _ in parsed_items:
            locked_product = locked_products[product.id]
            if locked_product.stock_tracked:
                stock_deltas[product.id] = (
                    stock_deltas.get(product.id, 0) + quantity
                )
        stock_error = _change_stock_reservations(stock_deltas)
        if stock_error:
            return JsonResponse({"error": stock_error}, status=409)

        order = Order.objects.create(
            customer_name=name,
            phone=phone[:32],
            kind=kind,
            table_number=table_number,
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
                    product=locked_products[product.id],
                    product_name=locked_products[product.id].name,
                    unit_price=locked_products[product.id].price,
                    extra_total=extra_total,
                    extras_snapshot=[
                        {"name": extra.name, "price": str(extra.price)}
                        for extra in extras
                    ],
                    quantity=quantity,
                    stock_reserved=locked_products[product.id].stock_tracked,
                    instructions=instructions,
                )
                for product, quantity, instructions, extras, extra_total in parsed_items
            ]
        )
    return JsonResponse({"order": _order_dict(order)}, status=201)


def _order_editability_error(order):
    """Keep edits limited to unpaid orders that have not entered preparation."""
    if order.status != Order.Status.RECEIVED:
        return "Solo se puede editar o eliminar un pedido que aún no empezó a prepararse."
    if order.payment_status != Order.PaymentStatus.PENDING:
        return "No se puede editar ni eliminar un pedido que ya tiene el pago registrado."
    return None


@staff_member_required
@require_http_methods(["PATCH", "DELETE"])
def order_detail_api(request, order_id):
    data = _json_body(request) if request.method == "PATCH" else {}
    if request.method == "PATCH" and not isinstance(data, dict):
        return JsonResponse({"error": "Solicitud no válida."}, status=400)

    with transaction.atomic():
        order = get_object_or_404(
            Order.objects.select_for_update().prefetch_related("items"),
            pk=order_id,
        )
        error = _order_editability_error(order)
        if error:
            return JsonResponse({"error": error}, status=409)

        if request.method == "DELETE":
            reserved = {}
            for item in order.items.all():
                if item.stock_reserved:
                    reserved[item.product_id] = (
                        reserved.get(item.product_id, 0) - item.quantity
                    )
            stock_error = _change_stock_reservations(reserved)
            if stock_error:
                return JsonResponse({"error": stock_error}, status=409)
            order.delete()
            return JsonResponse({"deleted": True})

        rows = data.get("items")
        if not isinstance(rows, list) or not rows or len(rows) > 50:
            return JsonResponse(
                {"error": "El pedido debe conservar entre 1 y 50 productos."},
                status=400,
            )

        existing_items = {item.id: item for item in order.items.all()}
        used_item_ids = set()
        parsed_rows = []
        try:
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError
                quantity = int(row.get("quantity", 0))
                if quantity < 1 or quantity > 30:
                    raise ValueError
                instructions = str(row.get("instructions", "")).strip()[:180]
                item_id = row.get("item_id")
                if item_id is not None:
                    item_id = int(item_id)
                    item = existing_items.get(item_id)
                    if item is None or item_id in used_item_ids:
                        raise ValueError
                    if int(row.get("product_id", item.product_id)) != item.product_id:
                        raise ValueError
                    used_item_ids.add(item_id)
                    parsed_rows.append(("existing", item, quantity, instructions))
                else:
                    product_id = int(row.get("product_id"))
                    parsed_rows.append(("new", product_id, quantity, instructions))
        except (TypeError, ValueError):
            return JsonResponse(
                {"error": "Revisa los productos y cantidades del pedido."},
                status=400,
            )

        new_product_ids = {
            value for kind, value, _, _ in parsed_rows if kind == "new"
        }
        product_ids = new_product_ids | {
            item.product_id for item in existing_items.values()
        }
        products = {
            product.id: product
            for product in Product.objects.select_for_update()
            .filter(id__in=product_ids)
            .order_by("id")
        }
        if len(products) != len(product_ids) or any(
            not products[product_id].available for product_id in new_product_ids
        ):
            return JsonResponse(
                {"error": "Uno de los productos nuevos ya no está disponible."},
                status=400,
            )

        previous_reservations = {}
        for item in existing_items.values():
            if item.stock_reserved:
                previous_reservations[item.product_id] = (
                    previous_reservations.get(item.product_id, 0) + item.quantity
                )
        desired_reservations = {}
        for kind, value, quantity, _ in parsed_rows:
            product_id = value.product_id if kind == "existing" else value
            if products[product_id].stock_tracked:
                desired_reservations[product_id] = (
                    desired_reservations.get(product_id, 0) + quantity
                )
        reservation_deltas = {
            product_id: desired_reservations.get(product_id, 0)
            - previous_reservations.get(product_id, 0)
            for product_id in product_ids
        }
        stock_error = _change_stock_reservations(reservation_deltas)
        if stock_error:
            return JsonResponse({"error": stock_error}, status=409)

        subtotal = Decimal("0")
        retained_items = []
        for kind, value, quantity, instructions in parsed_rows:
            if kind == "existing":
                item = value
                item.quantity = quantity
                item.instructions = instructions
                item.stock_reserved = products[item.product_id].stock_tracked
                item.save(
                    update_fields=["quantity", "instructions", "stock_reserved"]
                )
            else:
                product = products[value]
                item = OrderItem.objects.create(
                    order=order,
                    product=product,
                    product_name=product.name,
                    unit_price=product.price,
                    quantity=quantity,
                    stock_reserved=product.stock_tracked,
                    instructions=instructions,
                )
            subtotal += item.line_total
            retained_items.append(item.id)

        order.items.exclude(id__in=retained_items).delete()
        order.subtotal = _money(subtotal)
        order.tax = _money(
            order.subtotal * Decimal(settings.BUSINESS_TAX_RATE) / Decimal("100")
        )
        order.total = order.subtotal + order.delivery_fee + order.tax
        order.save(
            update_fields=["subtotal", "tax", "total", "updated_at"]
        )

    order.refresh_from_db()
    order = Order.objects.prefetch_related(
        "items", "invoice__cancellation_requests"
    ).get(pk=order.pk)
    return JsonResponse({"order": _order_dict(order)})


@staff_member_required
@require_POST
def order_status_api(request, order_id):
    """Apply an allowed order transition and record cancellation reasons."""
    data = _json_body(request)
    if not isinstance(data, dict) or data.get("status") not in Order.Status.values:
        return JsonResponse({"error": "Estado no válido."}, status=400)
    reason = str(data.get("reason", "")).strip()[:500]
    if data["status"] == Order.Status.CANCELLED and not reason:
        return JsonResponse(
            {"error": "Escribe el motivo de cancelación del pedido."}, status=400
        )
    with transaction.atomic():
        order = get_object_or_404(Order.objects.select_for_update(), pk=order_id)
        old_status = order.status
        allowed_transitions = {
            Order.Status.RECEIVED: {
                Order.Status.PREPARING,
                Order.Status.CANCELLED,
            },
            Order.Status.PREPARING: {
                Order.Status.READY,
                Order.Status.CANCELLED,
            },
            Order.Status.READY: {
                Order.Status.DELIVERED,
                Order.Status.CANCELLED,
            },
            Order.Status.DELIVERED: set(),
            Order.Status.CANCELLED: set(),
        }
        if data["status"] not in allowed_transitions[old_status]:
            return JsonResponse(
                {"error": "No se puede cambiar el pedido a ese estado."}, status=409
            )
        if (
            data["status"] == Order.Status.CANCELLED
            and old_status == Order.Status.RECEIVED
        ):
            reserved_items = list(
                order.items.filter(stock_reserved=True).only(
                    "id", "product_id", "quantity"
                )
            )
            reservation_returns = {}
            for item in reserved_items:
                reservation_returns[item.product_id] = (
                    reservation_returns.get(item.product_id, 0) - item.quantity
                )
            stock_error = _change_stock_reservations(reservation_returns)
            if stock_error:
                return JsonResponse({"error": stock_error}, status=409)
            OrderItem.objects.filter(
                id__in=[item.id for item in reserved_items]
            ).update(stock_reserved=False)
        order.status = data["status"]
        order.save(update_fields=["status", "updated_at"])
        OrderStatusLog.objects.create(
            order=order,
            previous_status=old_status,
            new_status=order.status,
            reason=reason if order.status == Order.Status.CANCELLED else "",
            changed_by=request.user,
        )
    return JsonResponse({"order": _order_dict(order)})


@staff_member_required
@require_POST
def order_payment_api(request, order_id):
    """Record payment once and create its invoice within the same transaction."""
    data = _json_body(request)
    if not isinstance(data, dict):
        return JsonResponse({"error": "Solicitud no válida."}, status=400)
    method = data.get("payment_method")
    if method not in Order.PaymentMethod.values:
        return JsonResponse({"error": "Método de pago no válido."}, status=400)
    if data.get("paid") is not True:
        return JsonResponse(
            {"error": "El pago debe confirmarse explícitamente."}, status=400
        )
    cash_received = None
    change_given = Decimal("0")
    if method == Order.PaymentMethod.CASH:
        try:
            cash_received = _money(data.get("cash_received"))
            if (
                not cash_received.is_finite()
                or cash_received < 0
                or cash_received > Decimal("9999999999.99")
            ):
                raise InvalidOperation
        except (InvalidOperation, TypeError, ValueError):
            return JsonResponse(
                {"error": "Indica un importe válido recibido en efectivo."}, status=400
            )
    with transaction.atomic():
        order = get_object_or_404(
            Order.objects.select_for_update(), pk=order_id
        )
        if order.payment_status == Order.PaymentStatus.PAID:
            return JsonResponse({"error": "Este pedido ya tiene el pago registrado."}, status=409)
        if order.status == Order.Status.CANCELLED:
            return JsonResponse(
                {"error": "No se puede registrar el pago de un pedido cancelado."},
                status=409,
            )
        if method == Order.PaymentMethod.CASH:
            if cash_received < order.total:
                return JsonResponse(
                    {"error": "El efectivo recibido no puede ser menor que el total del pedido."},
                    status=400,
                )
            change_given = cash_received - order.total
        existing_invoice = OrderInvoice.objects.filter(order=order).first()
        if existing_invoice and existing_invoice.status == OrderInvoice.Status.VOIDED:
            return JsonResponse(
                {"error": "El comprobante de este pedido está anulado; no se puede registrar otro cobro."},
                status=409,
            )
        order.payment_method = method
        order.payment_status = Order.PaymentStatus.PAID
        order.paid_at = timezone.now()
        order.save(
            update_fields=["payment_method", "payment_status", "paid_at", "updated_at"]
        )
        invoice, created = OrderInvoice.objects.get_or_create(
            order=order,
            defaults={
                "number": f"F-{order.number}",
                "cash_received": cash_received,
                "change_given": change_given,
            },
        )
        if not created:
            invoice.cash_received = cash_received
            invoice.change_given = change_given
            invoice.save(update_fields=["cash_received", "change_given"])
    order = Order.objects.prefetch_related(
        "items", "invoice__cancellation_requests"
    ).get(pk=order.pk)
    return JsonResponse({"order": _order_dict(order)})


@staff_member_required
@require_POST
def invoice_cancellation_request_api(request, order_id):
    """Void the receipt without changing payment or recording a refund."""
    data = _json_body(request)
    reason = str(data.get("reason", "")).strip()[:500] if isinstance(data, dict) else ""
    if not reason:
        return JsonResponse({"error": "Escribe el motivo de la anulación."}, status=400)

    with transaction.atomic():
        order = get_object_or_404(
            Order.objects.select_for_update().select_related("invoice"),
            pk=order_id,
        )
        try:
            invoice = order.invoice
        except OrderInvoice.DoesNotExist:
            return JsonResponse(
                {"error": "Este pedido todavía no tiene un comprobante registrado."},
                status=409,
            )
        if invoice.status != OrderInvoice.Status.ACTIVE:
            return JsonResponse(
                {"error": "El comprobante ya está anulado."}, status=409
            )
        now = timezone.now()
        actor_email = request.user.email or ""
        cancellation = InvoiceCancellationRequest.objects.create(
            invoice=invoice,
            requested_by=request.user,
            reason=reason,
            status=InvoiceCancellationRequest.Status.APPROVED,
            decided_at=now,
            decided_by_email=actor_email,
        )
        invoice.status = OrderInvoice.Status.VOIDED
        invoice.voided_at = now
        invoice.voided_by_email = actor_email
        invoice.save(update_fields=["status", "voided_at", "voided_by_email"])
    return JsonResponse(
        {
            "cancelled": True,
            "invoice_number": invoice.number,
            "status": invoice.status,
            "reason": cancellation.reason,
            "cancelled_at": timezone.localtime(invoice.voided_at).isoformat(),
            "refunded": False,
        }
    )


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


def _expense_dict(expense):
    return {
        "id": expense.id,
        "expense_date": expense.expense_date.isoformat(),
        "category": expense.category,
        "category_label": expense.get_category_display(),
        "description": expense.description,
        "amount": str(expense.amount),
        "created_by": expense.created_by.username,
    }


def _expense_values(data):
    if not isinstance(data, dict):
        return None, "Los datos del gasto no tienen un formato válido."

    expense_date_value = str(data.get("expense_date", "")).strip()
    try:
        expense_date = parse_date(expense_date_value) if expense_date_value else None
    except ValueError:
        expense_date = None
    if expense_date is None:
        return None, "Indica una fecha válida para el gasto."

    category = str(data.get("category", "")).strip()
    if category not in Expense.Category.values:
        return None, "Selecciona una categoría de gasto válida."

    description = str(data.get("description", "")).strip()[:240]
    if category == Expense.Category.REMODELING and not description:
        return None, "Escribe una descripción para el gasto de remodelación."

    try:
        amount = _money(data.get("amount"))
        if not amount.is_finite() or amount <= 0 or amount > Decimal("9999999999.99"):
            raise InvalidOperation
    except (InvalidOperation, TypeError, ValueError):
        return None, "El valor del gasto debe ser mayor que cero."

    return {
        "expense_date": expense_date,
        "category": category,
        "description": description,
        "amount": amount,
    }, None


@staff_member_required
@require_http_methods(["GET", "POST"])
def expenses_api(request):
    if request.method == "POST":
        values, error = _expense_values(_json_body(request))
        if error:
            return JsonResponse({"error": error}, status=400)
        expense = Expense.objects.create(**values, created_by=request.user)
        return JsonResponse({"expense": _expense_dict(expense)}, status=201)

    queryset = Expense.objects.select_related("created_by")
    start_value = request.GET.get("start", "").strip()
    end_value = request.GET.get("end", "").strip()
    category = request.GET.get("category", "").strip()
    try:
        start = parse_date(start_value) if start_value else None
        end = parse_date(end_value) if end_value else None
    except ValueError:
        return JsonResponse({"error": "El rango de fechas del gasto no es válido."}, status=400)
    if (start_value and start is None) or (end_value and end is None):
        return JsonResponse({"error": "El rango de fechas del gasto no es válido."}, status=400)
    if start and end and start > end:
        return JsonResponse(
            {"error": "La fecha inicial no puede ser posterior a la fecha final."},
            status=400,
        )
    if category and category not in Expense.Category.values:
        return JsonResponse({"error": "La categoría de gasto no es válida."}, status=400)
    if start:
        queryset = queryset.filter(expense_date__gte=start)
    if end:
        queryset = queryset.filter(expense_date__lte=end)
    if category:
        queryset = queryset.filter(category=category)
    return JsonResponse(
        {
            "expenses": [_expense_dict(expense) for expense in queryset],
            "total": str(queryset.aggregate(total=Sum("amount"))["total"] or 0),
            "count": queryset.count(),
            "categories": [
                {"value": value, "label": label}
                for value, label in Expense.Category.choices
            ],
        }
    )


@staff_member_required
@require_http_methods(["PATCH", "DELETE"])
def expense_detail_api(request, expense_id):
    expense = get_object_or_404(Expense, pk=expense_id)
    if request.method == "DELETE":
        expense.delete()
        return JsonResponse({"deleted": True})

    values, error = _expense_values(_json_body(request))
    if error:
        return JsonResponse({"error": error}, status=400)
    for field, value in values.items():
        setattr(expense, field, value)
    expense.save(update_fields=[*values.keys()])
    return JsonResponse({"expense": _expense_dict(expense)})


def _next_month(month):
    return date(month.year + (month.month == 12), month.month % 12 + 1, 1)


def _parse_month(value):
    if not value or len(value) != 7:
        raise ValueError
    month = date.fromisoformat(f"{value}-01")
    if month.strftime("%Y-%m") != value:
        raise ValueError
    return month


@staff_member_required
@require_GET
def profits_api(request):
    today = timezone.localdate()
    default_end_month = today.replace(day=1)
    default_start_month = (default_end_month - timedelta(days=1)).replace(day=1)
    default_start_month = (default_start_month - timedelta(days=1)).replace(day=1)
    try:
        start_month = _parse_month(
            request.GET.get("start_month", default_start_month.strftime("%Y-%m"))
        )
        end_month = _parse_month(
            request.GET.get("end_month", default_end_month.strftime("%Y-%m"))
        )
        if end_month < start_month:
            raise ValueError
        month_count = (
            (end_month.year - start_month.year) * 12
            + end_month.month
            - start_month.month
            + 1
        )
        if month_count > 120:
            raise ValueError
    except ValueError:
        return JsonResponse(
            {"error": "Selecciona un rango de meses válido de hasta 10 años."},
            status=400,
        )

    end_date = _next_month(end_month) - timedelta(days=1)
    paid_orders = Order.objects.filter(payment_status=Order.PaymentStatus.PAID).filter(
        Q(paid_at__date__gte=start_month, paid_at__date__lte=end_date)
        | Q(
            paid_at__isnull=True,
            created_at__date__gte=start_month,
            created_at__date__lte=end_date,
        )
    )
    sales_by_month = {
        row["month"].strftime("%Y-%m"): row["total"] or Decimal("0")
        for row in paid_orders.annotate(
            month=TruncMonth(Coalesce("paid_at", "created_at"))
        )
        .values("month")
        .annotate(total=Sum("total"))
    }
    expense_queryset = Expense.objects.filter(
        expense_date__gte=start_month,
        expense_date__lte=end_date,
    )
    expenses_by_month = {
        row["month"].strftime("%Y-%m"): row["total"] or Decimal("0")
        for row in expense_queryset.annotate(month=TruncMonth("expense_date"))
        .values("month")
        .annotate(total=Sum("amount"))
    }
    expenses_by_category = {
        row["category"]: row["total"] or Decimal("0")
        for row in expense_queryset.values("category").annotate(total=Sum("amount"))
    }
    category_labels = dict(Expense.Category.choices)
    months = []
    month = start_month
    while month <= end_month:
        key = month.strftime("%Y-%m")
        sales_total = sales_by_month.get(key, Decimal("0"))
        expense_total = expenses_by_month.get(key, Decimal("0"))
        months.append(
            {
                "month": key,
                "sales_total": str(sales_total),
                "expense_total": str(expense_total),
                "profit": str(sales_total - expense_total),
            }
        )
        month = _next_month(month)

    total_sales = sum(
        (Decimal(row["sales_total"]) for row in months), Decimal("0")
    )
    total_expenses = sum(
        (Decimal(row["expense_total"]) for row in months), Decimal("0")
    )
    return JsonResponse(
        {
            "start_month": start_month.strftime("%Y-%m"),
            "end_month": end_month.strftime("%Y-%m"),
            "sales_total": str(total_sales),
            "expense_total": str(total_expenses),
            "profit": str(total_sales - total_expenses),
            "expense_by_category": [
                {
                    "category": category_labels[category],
                    "total": str(total),
                }
                for category, total in expenses_by_category.items()
            ],
            "months": months,
        }
    )


def _report_data(start, end):
    created_orders = Order.objects.filter(
        created_at__date__gte=start, created_at__date__lte=end
    )
    orders = created_orders.exclude(status=Order.Status.CANCELLED)
    # Sales follow the payment date; legacy paid orders without paid_at use creation date.
    paid = Order.objects.filter(payment_status=Order.PaymentStatus.PAID).filter(
        Q(paid_at__date__gte=start, paid_at__date__lte=end)
        | Q(
            paid_at__isnull=True,
            created_at__date__gte=start,
            created_at__date__lte=end,
        )
    )
    voided_paid = paid.filter(invoice__status=OrderInvoice.Status.VOIDED)
    by_method = paid.values("payment_method").annotate(
        total=Sum("total"), count=Count("id")
    )
    by_order_type = paid.values("kind").annotate(
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
    monthly_trend = (end - start).days > 62
    if monthly_trend:
        trend_rows = (
            paid.annotate(period=TruncMonth(Coalesce("paid_at", "created_at")))
            .values("period")
            .annotate(total=Sum("total"))
        )
        trend_totals = {
            row["period"].strftime("%Y-%m"): row["total"] or Decimal("0")
            for row in trend_rows
        }
        periods = []
        month = start.replace(day=1)
        last_month = end.replace(day=1)
        while month <= last_month:
            periods.append(month)
            month = _next_month(month)
        daily_sales = [
            {
                "date": month.isoformat(),
                "total": str(trend_totals.get(month.strftime("%Y-%m"), Decimal("0"))),
            }
            for month in periods
        ]
    else:
        daily_rows = (
            paid.filter(paid_at__isnull=False)
            .annotate(day=TruncDate("paid_at"))
            .values("day")
            .annotate(total=Sum("total"))
        )
        daily_totals = {
            str(row["day"]): row["total"] or Decimal("0") for row in daily_rows
        }
        legacy_daily_rows = (
            paid.filter(paid_at__isnull=True)
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(total=Sum("total"))
        )
        daily_totals.update(
            {
                str(row["day"]): row["total"] or Decimal("0")
                for row in legacy_daily_rows
            }
        )
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
    sales_totals = paid.aggregate(
        total=Sum("total"),
        subtotal=Sum("subtotal"),
        delivery_fee=Sum("delivery_fee"),
        tax=Sum("tax"),
    )
    sales_total = sales_totals["total"] or Decimal("0")
    paid_order_count = paid.count()
    inventory = list(
        Product.objects.filter(stock_tracked=True)
        .select_related("category")
        .order_by("category__sort_order", "category__name", "name")
    )
    sold_units_by_product = dict(
        OrderItem.objects.filter(order__in=paid)
        .values("product_id")
        .annotate(units=Sum("quantity"))
        .values_list("product_id", "units")
    )
    return {
        "start": str(start),
        "end": str(end),
        "trend_interval": "month" if monthly_trend else "day",
        "order_count": orders.count(),
        "created_order_count": created_orders.count(),
        "cancelled_order_count": created_orders.filter(
            status=Order.Status.CANCELLED
        ).count(),
        "paid_order_count": paid_order_count,
        "sales_total": str(sales_total),
        "average_ticket": str(
            (sales_total / paid_order_count).quantize(Decimal("0.01"))
            if paid_order_count
            else Decimal("0")
        ),
        "subtotal_total": str(sales_totals["subtotal"] or Decimal("0")),
        "delivery_fee_total": str(sales_totals["delivery_fee"] or Decimal("0")),
        "tax_total": str(sales_totals["tax"] or Decimal("0")),
        "voided_invoice_count": voided_paid.count(),
        "voided_invoice_total": str(
            voided_paid.aggregate(total=Sum("total"))["total"] or Decimal("0")
        ),
        "pending_total": str(
            orders.filter(payment_status=Order.PaymentStatus.PENDING).aggregate(
                total=Sum("total")
            )["total"]
            or Decimal("0")
        ),
        "pending_order_count": orders.filter(
            payment_status=Order.PaymentStatus.PENDING
        ).count(),
        "by_method": [
            {
                "method": labels[row["payment_method"]],
                "total": str(row["total"] or 0),
                "count": row["count"],
            }
            for row in by_method
        ],
        "by_order_type": [
            {
                "kind": dict(Order.Kind.choices).get(row["kind"], row["kind"]),
                "total": str(row["total"] or 0),
                "count": row["count"],
            }
            for row in by_order_type
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
        "inventory": [
            {
                "name": product.name,
                "category": product.category.name,
                "stock_quantity": product.stock_quantity,
                "available": product.available,
                "units_sold": sold_units_by_product.get(product.id, 0),
            }
            for product in inventory
        ],
        "out_of_stock_count": sum(
            product.stock_quantity == 0 for product in inventory
        ),
        "unconfigured_stock_count": sum(
            product.stock_quantity is None for product in inventory
        ),
    }


@staff_member_required
@require_GET
def reports_api(request):
    today = timezone.localdate()
    try:
        all_sales = request.GET.get("all") == "1"
        if all_sales:
            first_paid_date = (
                Order.objects.filter(payment_status=Order.PaymentStatus.PAID)
                .annotate(sales_date=Coalesce("paid_at", "created_at"))
                .order_by("sales_date")
                .values_list("sales_date", flat=True)
                .first()
            )
            start = (
                timezone.localtime(first_paid_date).date()
                if first_paid_date
                else today
            )
            end = today
        else:
            start = date.fromisoformat(
                request.GET.get("start", str(today.replace(day=1)))
            )
            end = date.fromisoformat(request.GET.get("end", str(today)))
        if end < start or (not all_sales and (end - start).days > 366):
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
        all_sales = request.GET.get("all") == "1"
        if all_sales:
            first_paid_date = (
                Order.objects.filter(payment_status=Order.PaymentStatus.PAID)
                .annotate(sales_date=Coalesce("paid_at", "created_at"))
                .order_by("sales_date")
                .values_list("sales_date", flat=True)
                .first()
            )
            start = (
                timezone.localtime(first_paid_date).date()
                if first_paid_date
                else today
            )
            end = today
        else:
            start = date.fromisoformat(
                request.GET.get("start", str(today.replace(day=1)))
            )
            end = date.fromisoformat(request.GET.get("end", str(today)))
        if end < start or (not all_sales and (end - start).days > 366):
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
            "Fecha del pedido",
            "Fecha del pago",
            "Cliente",
            "Tipo",
            "Estado",
            "Método de pago",
            "Pago",
            "Total",
            "Comprobante",
            "Estado del comprobante",
            "Efectivo recibido",
            "Cambio entregado",
            "Motivo de cancelación",
            "Motivo de anulación",
        ]
    )
    for order in Order.objects.filter(
        Q(created_at__date__gte=start, created_at__date__lte=end)
        | Q(paid_at__date__gte=start, paid_at__date__lte=end)
    ).select_related("invoice").prefetch_related(
        "status_history", "invoice__cancellation_requests"
    ).order_by("created_at"):
        invoice = getattr(order, "invoice", None)
        cancellation_reason = next(
            (
                entry.reason
                for entry in order.status_history.all()
                if entry.new_status == Order.Status.CANCELLED
            ),
            "",
        )
        invoice_void_reason = next(
            (
                request.reason
                for request in invoice.cancellation_requests.all()
                if request.status == InvoiceCancellationRequest.Status.APPROVED
            ),
            "",
        ) if invoice else ""
        writer.writerow(
            [
                order.number,
                timezone.localtime(order.created_at).strftime("%Y-%m-%d %H:%M"),
                (
                    timezone.localtime(order.paid_at).strftime("%Y-%m-%d %H:%M")
                    if order.paid_at
                    else ""
                ),
                order.customer_name,
                order.get_kind_display(),
                order.get_status_display(),
                order.get_payment_method_display(),
                order.get_payment_status_display(),
                order.total,
                invoice.number if invoice else "",
                invoice.get_status_display() if invoice else "",
                (
                    invoice.cash_received
                    if invoice and invoice.cash_received is not None
                    else ""
                ),
                invoice.change_given if invoice else "",
                cancellation_reason,
                invoice_void_reason,
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
