import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class Category(models.Model):
    name = models.CharField("Nombre de categoría", max_length=80, unique=True)
    sort_order = models.PositiveSmallIntegerField("Orden en la carta", default=0)
    active = models.BooleanField("Categoría activa", default=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Categoría"
        verbose_name_plural = "Categorías"

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(Category, verbose_name="Categoría", on_delete=models.PROTECT, related_name="products")
    name = models.CharField("Nombre del producto", max_length=120)
    description = models.CharField("Descripción para la carta", max_length=240, blank=True)
    price = models.DecimalField("Precio en COP", max_digits=10, decimal_places=2)
    available = models.BooleanField(
        "Disponible para pedir",
        default=True,
        help_text="Desmarca para agotarlo o retirarlo de la carta. Si tiene ventas, no se puede borrar porque forma parte del historial.",
    )
    featured = models.BooleanField("Producto destacado", default=False)
    created_at = models.DateTimeField("Fecha de creación", auto_now_add=True)

    class Meta:
        ordering = ["category__sort_order", "name"]
        verbose_name = "Producto de la carta"
        verbose_name_plural = "Productos de la carta"

    def __str__(self):
        return self.name


class ProductExtra(models.Model):
    product = models.ForeignKey(Product, verbose_name="Producto", on_delete=models.CASCADE, related_name="extras")
    name = models.CharField("Nombre del adicional", max_length=80)
    price = models.DecimalField("Precio adicional en COP", max_digits=10, decimal_places=2, default=Decimal("0"))
    active = models.BooleanField("Adicional activo", default=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["product", "name"], name="unique_product_extra_name")]
        verbose_name = "Adicional de producto"
        verbose_name_plural = "Adicionales de producto"

    def __str__(self):
        return f"{self.product.name}: {self.name}"


class Order(models.Model):
    class Kind(models.TextChoices):
        TABLE = "table", "Mesa"
        TAKEAWAY = "takeaway", "Para llevar"
        DELIVERY = "delivery", "Domicilio"

    class Status(models.TextChoices):
        RECEIVED = "received", "Recibido"
        PREPARING = "preparing", "En preparación"
        READY = "ready", "Preparado"
        DELIVERED = "delivered", "Entregado"
        CANCELLED = "cancelled", "Cancelado"

    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Efectivo"
        CARD = "card", "Tarjeta"
        BANCOLOMBIA = "bancolombia", "Bancolombia"
        NEQUI = "nequi", "Nequi"

    class PaymentStatus(models.TextChoices):
        PENDING = "pending", "Pendiente"
        PAID = "paid", "Pagado"

    number = models.CharField(max_length=16, unique=True, editable=False)
    customer_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=32, blank=True)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    table_number = models.CharField(max_length=12, blank=True)
    address = models.CharField(max_length=240, blank=True)
    note = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RECEIVED)
    payment_method = models.CharField(max_length=12, choices=PaymentMethod.choices, default=PaymentMethod.CASH)
    payment_status = models.CharField(max_length=8, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    paid_at = models.DateTimeField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Pedido"
        verbose_name_plural = "Pedidos"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = f"{timezone.localdate():%y%m%d}-{uuid.uuid4().hex[:6].upper()}"
        if self.payment_status == self.PaymentStatus.PAID and self.paid_at is None:
            self.paid_at = timezone.now()
        elif self.payment_status != self.PaymentStatus.PAID:
            self.paid_at = None
        super().save(*args, **kwargs)

    def __str__(self):
        return self.number


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="sold_items")
    product_name = models.CharField(max_length=120)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    extra_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    extras_snapshot = models.JSONField(default=list, blank=True)
    quantity = models.PositiveSmallIntegerField()
    instructions = models.CharField(max_length=180, blank=True)

    @property
    def line_total(self):
        return (self.unit_price + self.extra_total) * self.quantity


class OrderStatusLog(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="status_history")
    previous_status = models.CharField(max_length=12, choices=Order.Status.choices, blank=True)
    new_status = models.CharField(max_length=12, choices=Order.Status.choices)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["changed_at"]


class CashSession(models.Model):
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cash_sessions")
    opened_at = models.DateTimeField(default=timezone.now)
    opening_amount = models.DecimalField(max_digits=12, decimal_places=2)
    closed_at = models.DateTimeField(null=True, blank=True)
    counted_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    counted_denominations = models.JSONField(default=dict, blank=True)
    payment_totals_snapshot = models.JSONField(default=dict, blank=True)
    verified_payment_totals = models.JSONField(default=dict, blank=True)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    reconciled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="cash_reconciliations")
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="closed_cash_sessions")

    class Meta:
        ordering = ["-opened_at"]
        verbose_name = "Turno de caja"
        verbose_name_plural = "Turnos de caja"

    @property
    def is_open(self):
        return self.closed_at is None

    def payment_totals(self):
        from django.db.models import Sum

        if not self.is_open:
            return {key: Decimal(value) for key, value in self.payment_totals_snapshot.items()}
        rows = Order.objects.filter(
            paid_at__gte=self.opened_at,
            payment_status=Order.PaymentStatus.PAID,
        ).exclude(status=Order.Status.CANCELLED).values("payment_method").annotate(total=Sum("total"))
        labels = dict(Order.PaymentMethod.choices)
        labels.update({"transfer": "Transferencia (anterior)", "other": "Otro (anterior)"})
        return {labels[row["payment_method"]]: row["total"] or Decimal("0") for row in rows}

    @property
    def expected_cash(self):
        return self.opening_amount + self.payment_totals().get("Efectivo", Decimal("0"))

    @property
    def difference(self):
        if self.counted_amount is None:
            return None
        return self.counted_amount - self.expected_cash