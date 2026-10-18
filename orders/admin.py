from django.contrib import admin
from django.db.models import Q

from .models import (
    CashSession,
    Category,
    InvoiceCancellationRequest,
    Order,
    OrderInvoice,
    OrderItem,
    OrderStatusLog,
    Product,
    ProductExtra,
)

admin.site.site_header = "Administración del restaurante"
admin.site.site_title = "Administración del restaurante"
admin.site.index_title = "Carta, pedidos y caja"


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "sort_order", "active")
    list_editable = ("sort_order", "active")
    search_fields = ("name",)
    ordering = ("sort_order", "name")


class ProductExtraInline(admin.TabularInline):
    model = ProductExtra
    extra = 0
    fields = ("name", "price", "active")
    verbose_name = "Adicional"
    verbose_name_plural = "Adicionales para este producto"


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "price",
        "available",
        "featured",
        "stock_tracked",
        "stock_quantity",
    )
    list_filter = ("category", "available", "featured", "stock_tracked")
    list_editable = ("price", "available", "featured", "stock_tracked", "stock_quantity")
    search_fields = ("name", "description")
    ordering = ("category__sort_order", "name")
    list_per_page = 25
    date_hierarchy = "created_at"
    readonly_fields = ("created_at",)
    fieldsets = (
        ("Información del producto", {"fields": ("name", "category", "description")}),
        (
            "Precio, disponibilidad e inventario",
            {
                "fields": (
                    "price",
                    "available",
                    "featured",
                    "stock_tracked",
                    "stock_quantity",
                )
            },
        ),
        ("Registro", {"fields": ("created_at",)}),
    )
    inlines = (ProductExtraInline,)
    actions = ("mark_sold_out", "mark_available")

    @admin.action(description="Marcar como agotados y quitar de la carta pública")
    def mark_sold_out(self, request, queryset):
        updated = queryset.update(available=False)
        self.message_user(request, f"{updated} producto(s) marcado(s) como agotado(s).")

    @admin.action(description="Volver a ofrecer los productos seleccionados")
    def mark_available(self, request, queryset):
        eligible = queryset.filter(
            Q(stock_tracked=False) | Q(stock_quantity__gt=0)
        )
        updated = eligible.update(available=True)
        blocked = queryset.count() - updated
        message = f"{updated} producto(s) disponible(s) en la carta."
        if blocked:
            message += f" {blocked} producto(s) necesitan existencias antes de ofrecerse."
        self.message_user(request, message)


@admin.register(ProductExtra)
class ProductExtraAdmin(admin.ModelAdmin):
    list_display = ("name", "product", "price", "active")
    list_filter = ("active", "product__category")
    list_editable = ("price", "active")
    search_fields = ("name", "product__name")


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = (
        "product",
        "product_name",
        "unit_price",
        "extra_total",
        "extras_snapshot",
        "quantity",
        "instructions",
    )
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class OrderStatusLogInline(admin.TabularInline):
    model = OrderStatusLog
    extra = 0
    can_delete = False
    readonly_fields = (
        "previous_status",
        "new_status",
        "reason",
        "changed_by",
        "changed_at",
    )

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("number", "customer_name", "kind", "status", "payment_status", "total", "created_at")
    list_filter = ("status", "kind", "payment_method", "payment_status", "created_at")
    search_fields = ("number", "customer_name", "phone")
    readonly_fields = (
        "number",
        "customer_name",
        "phone",
        "kind",
        "table_number",
        "address",
        "note",
        "status",
        "payment_method",
        "payment_status",
        "paid_at",
        "subtotal",
        "delivery_fee",
        "tax",
        "total",
        "created_at",
        "updated_at",
    )
    inlines = (OrderItemInline, OrderStatusLogInline)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OrderInvoice)
class OrderInvoiceAdmin(admin.ModelAdmin):
    list_display = ("number", "order", "status", "created_at", "voided_at")
    list_filter = ("status", "created_at")
    search_fields = ("number", "order__number")
    readonly_fields = (
        "order",
        "number",
        "status",
        "created_at",
        "voided_at",
        "cash_received",
        "change_given",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(InvoiceCancellationRequest)
class InvoiceCancellationRequestAdmin(admin.ModelAdmin):
    list_display = (
        "invoice",
        "status",
        "requested_by",
        "requested_at",
        "decided_at",
    )
    list_filter = ("status", "requested_at")
    search_fields = ("invoice__number", "requested_by__username", "reason")
    readonly_fields = (
        "invoice",
        "requested_by",
        "reason",
        "status",
        "requested_at",
        "decided_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CashSession)
class CashSessionAdmin(admin.ModelAdmin):
    list_display = ("opened_at", "opened_by", "opening_amount", "closed_at", "counted_amount")
    readonly_fields = ("opened_at", "opened_by", "opening_amount", "closed_at", "counted_amount", "closed_by")