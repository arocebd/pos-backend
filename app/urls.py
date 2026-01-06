# app/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework.schemas import views
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    ProductViewSet, ProductVariantViewSet, CategoryViewSet, SaleViewSet,
    product_lookup, customer_lookup, CustomerViewSet, invoice_view,
    SalesMetricsView, DailySalesView, CategorySummaryView, TopProductsView,
    ExpenseViewSet, ExpenseSummaryView,
    SupplierViewSet, PurchaseViewSet, PurchaseItemViewSet, SupplierPaymentViewSet,
    SupplierLedgerView, sales_report,
    BusinessOverviewAPIView, BusinessOverviewTimeseriesAPIView,
    BusinessOverviewExportPDF, BusinessOverviewExportExcel,
    LoginView, ShopRegistrationView, SubscriptionStatusView,
    CreatePaymentRequestView, AdminVerifyPaymentView,
    UpdateShopLogoView, UpdateProfilePictureView, CustomerPaymentViewSet,
    CustomerDueSummaryView, CustomerLedgerDetailView,
    ShopUserViewSet, shop_settings, get_current_user_profile, update_user_password,
    ComprehensiveDashboardMetricsView, StockAlertDashboardView, DueAmountDashboardView,
    QuickRestockView, RenewSubscriptionView,
    CashTransactionListAPIView, CashTransactionCreateAPIView, CashTransactionSyncAPIView,
    CashTransactionSummaryAPIView, CashTransactionDeleteAPIView, OpeningBalanceAPIView,
    CashTransactionExportPDF, CashTransactionExportExcel
)

router = DefaultRouter()
router.register(r"categories", CategoryViewSet, basename="category")
router.register(r"products", ProductViewSet, basename="product")
router.register(r"product-variants", ProductVariantViewSet, basename="product-variant")
router.register(r"sales", SaleViewSet, basename="sale")
router.register(r"customers", CustomerViewSet, basename="customer")
router.register(r"expenses", ExpenseViewSet, basename="expense")
router.register(r"suppliers", SupplierViewSet, basename="supplier")
router.register(r"purchases", PurchaseViewSet, basename="purchase")
router.register(r"purchase-items", PurchaseItemViewSet, basename="purchase-item")
router.register(r"supplier-payments", SupplierPaymentViewSet, basename="supplier-payment")
router.register(r"customer-payments", CustomerPaymentViewSet, basename="customer-payment")
router.register(r"shop-users", ShopUserViewSet, basename="shop-user")  # ADDED

urlpatterns = [
    path("", include(router.urls)),
    
    # User & Shop Management
    path("user/profile/", get_current_user_profile, name="current-user-profile"),
    path("shop-users/<int:user_id>/update-password/", update_user_password, name="update-user-password"),
    
    # Business Operations
    path("product-lookup/", product_lookup, name="product_lookup"),
    path("customer-lookup/", customer_lookup, name="customer_lookup"),
    path("invoice/<int:pk>/", invoice_view, name="invoice_view"),
    
    # Dashboard Analytics
    path("dashboard/metrics/", SalesMetricsView.as_view(), name="dashboard-metrics"),
    path("dashboard/daily/", DailySalesView.as_view(), name="dashboard-daily"),
    path("dashboard/category-summary/", CategorySummaryView.as_view(), name="dashboard-category-summary"),
    path("dashboard/top-products/", TopProductsView.as_view(), name="dashboard-top-products"),
    path('dashboard/comprehensive-metrics/', ComprehensiveDashboardMetricsView.as_view(), name='dashboard-comprehensive-metrics'),
    path('dashboard/stock-alerts/', StockAlertDashboardView.as_view(), name='dashboard-stock-alerts'),
    path('dashboard/due-summary/', DueAmountDashboardView.as_view(), name='dashboard-due-summary'),
    
    # Customer Management
    path("customers/<int:customer_id>/ledger/", CustomerLedgerDetailView.as_view(), name="customer-ledger"),
    path("customer-due-summary/", CustomerDueSummaryView.as_view(), name="customer-due-summary"),
    
    # Expenses & Suppliers
    path('purchases/quick-restock/', QuickRestockView.as_view(), name='quick-restock'),
    path("expenses/summary/", ExpenseSummaryView.as_view(), name="expenses-summary"),
    path("suppliers/<int:supplier_id>/ledger/", SupplierLedgerView.as_view(), name="supplier-ledger"),
    
    # Reports
    path("sales-report/", sales_report, name="sales-report"),
    
    # Business Overview
    path("business-overview/", BusinessOverviewAPIView.as_view(), name="business-overview"),
    path("business-overview/timeseries/", BusinessOverviewTimeseriesAPIView.as_view(), name="business-overview-timeseries"),
    path("business-overview/export/pdf/", BusinessOverviewExportPDF.as_view(), name="business-overview-export-pdf"),
    path("business-overview/export/excel/", BusinessOverviewExportExcel.as_view(), name="business-overview-export-excel"),
    
    # Auth + Subscription
    path("auth/login/", LoginView.as_view(), name="token_obtain_pair"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("auth/register-shop/", ShopRegistrationView.as_view(), name="shop-register"),
    path("subscription-status/", SubscriptionStatusView.as_view(), name="subscription-status"),
    path("renew-subscription/", RenewSubscriptionView.as_view(), name="renew-subscription"),
    path("payment-request/", CreatePaymentRequestView.as_view(), name="payment-request"),
    
    # Admin verifies payment
    path("admin/verify-payment/<str:shop_id>/", AdminVerifyPaymentView.as_view(), name="verify-payment"),
    
    # Logo/Profile updates
    path("shop/update-logo/", UpdateShopLogoView.as_view(), name="update-shop-logo"),
    path("user/update-profile-picture/", UpdateProfilePictureView.as_view(), name="update-profile-picture"),
    
    # Shop Settings (GET/PUT for updating shop info)
    path("shop/settings/", shop_settings, name="shop-settings"),

    # Cash Transaction / Ledger
    path("cash-transactions/", CashTransactionListAPIView.as_view(), name="cash-transaction-list"),
    path("cash-transactions/create/", CashTransactionCreateAPIView.as_view(), name="cash-transaction-create"),
    path("cash-transactions/sync/", CashTransactionSyncAPIView.as_view(), name="cash-transaction-sync"),
    path("cash-transactions/summary/", CashTransactionSummaryAPIView.as_view(), name="cash-transaction-summary"),
    path("cash-transactions/<int:pk>/delete/", CashTransactionDeleteAPIView.as_view(), name="cash-transaction-delete"),
    path("cash-transactions/opening-balance/", OpeningBalanceAPIView.as_view(), name="cash-transaction-opening-balance"),    path("cash-transactions/export/pdf/", CashTransactionExportPDF.as_view(), name="cash-transaction-export-pdf"),
    path("cash-transactions/export/excel/", CashTransactionExportExcel.as_view(), name="cash-transaction-export-excel"),]
