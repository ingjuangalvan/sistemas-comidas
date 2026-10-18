from django.urls import path

from . import views

urlpatterns = [
    path("", views.menu, name="menu"),
    path("carta/", views.public_menu, name="public-menu"),
    path("carta/qr.svg", views.public_menu_qr, name="public-menu-qr"),
    path("panel/", views.panel, name="panel"),
    path("api/menu/", views.menu_api, name="menu-api"),
    path("api/products/", views.products_api, name="products-api"),
    path("api/products/<int:product_id>/", views.product_detail_api, name="product-detail-api"),
    path("api/orders/", views.orders_api, name="orders-api"),
    path("api/orders/<int:order_id>/", views.order_detail_api, name="order-detail-api"),
    path("api/orders/<int:order_id>/status/", views.order_status_api, name="order-status-api"),
    path("api/orders/<int:order_id>/payment/", views.order_payment_api, name="order-payment-api"),
    path(
        "api/orders/<int:order_id>/invoice-cancellation/",
        views.invoice_cancellation_request_api,
        name="invoice-cancellation-request-api",
    ),
    path("api/cash/", views.cash_api, name="cash-api"),
    path("api/cash/<int:session_id>/reconcile/", views.cash_reconciliation_api, name="cash-reconciliation-api"),
    path("api/expenses/", views.expenses_api, name="expenses-api"),
    path("api/expenses/<int:expense_id>/", views.expense_detail_api, name="expense-detail-api"),
    path("api/profits/", views.profits_api, name="profits-api"),
    path("api/reports/", views.reports_api, name="reports-api"),
    path("reports/export.csv", views.reports_csv, name="reports-csv"),
]