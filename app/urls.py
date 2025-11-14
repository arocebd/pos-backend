#app/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ProductViewSet, CategoryViewSet, SaleViewSet, product_lookup, customer_lookup, CustomerViewSet, invoice_view
from .views import SalesMetricsView, DailySalesView, CategorySummaryView, TopProductsView, ExpenseViewSet, ExpenseSummaryView
from .views import SupplierViewSet, PurchaseViewSet, PurchaseItemViewSet, SupplierPaymentViewSet, SupplierLedgerView, sales_report
from .views import BusinessOverviewAPIView, BusinessOverviewTimeseriesAPIView, BusinessOverviewExportPDF, BusinessOverviewExportExcel
from .views import LoginView
from rest_framework_simplejwt.views import TokenRefreshView

router = DefaultRouter()
router.register(r"categories", CategoryViewSet, basename="category")
router.register(r"products", ProductViewSet, basename="product")
router.register(r"sales", SaleViewSet, basename="sale")
router.register(r"customers", CustomerViewSet, basename="customer")
router.register(r"expenses", ExpenseViewSet, basename="expense")
router.register(r"suppliers", SupplierViewSet, basename="supplier")
router.register(r"purchases", PurchaseViewSet, basename="purchase")
router.register(r"purchase-items", PurchaseItemViewSet, basename="purchase-item")
router.register(r"supplier-payments", SupplierPaymentViewSet, basename="supplier-payment")

urlpatterns = [
    path('', include(router.urls)),
    path("product-lookup/", product_lookup, name="product_lookup"),
    path("customer-lookup/", customer_lookup, name="customer_lookup"),
    path("invoice/<int:pk>/", invoice_view, name="invoice_view"),
    path("dashboard/metrics/", SalesMetricsView.as_view(), name="dashboard-metrics"),
    path("dashboard/daily/", DailySalesView.as_view(), name="dashboard-daily"),
    path("dashboard/category-summary/", CategorySummaryView.as_view(), name="dashboard-category-summary"),
    path("dashboard/top-products/", TopProductsView.as_view(), name="dashboard-top-products"),
    path("expenses/summary/", ExpenseSummaryView.as_view(), name="expenses-summary"),
    path("suppliers/<int:supplier_id>/ledger/", SupplierLedgerView.as_view(), name="supplier-ledger"),
    path('sales-report/', sales_report, name='sales-report'),
    path('business-overview/', BusinessOverviewAPIView.as_view()),
    path('business-overview/timeseries/', BusinessOverviewTimeseriesAPIView.as_view()),
    path('business-overview/export/pdf/', BusinessOverviewExportPDF.as_view()),
    path('business-overview/export/excel/', BusinessOverviewExportExcel.as_view()),
    path('auth/login/', LoginView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]
