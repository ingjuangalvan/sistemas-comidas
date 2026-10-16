from django.urls import path

from . import views

urlpatterns = [
    path("", views.menu, name="menu"),
    path("panel/", views.panel, name="panel"),
    path("api/menu/", views.menu_api, name="menu-api"),
    path("api/products/", views.products_api, name="products-api"),
    path("api/products/<int:product_id>/", views.product_detail_api, name="product-detail-api"),
    path("api/orders/", views.orders_api, name="orders-api"),
    path("api/orders/<int:order_id>/status/", views.order_status_api, name="order-status-api"),
    path("api/orders/<int:order_id>/payment/", views.order_payment_api, name="order-payment-api"),
    path("api/cash/", views.cash_api, name="cash-api"),
    path("api/cash/<int:session_id>/reconcile/", views.cash_reconciliation_api, name="cash-reconciliation-api"),
    path("api/reports/", views.reports_api, name="reports-api"),
    path("reports/export.csv", views.reports_csv, name="reports-csv"),
]