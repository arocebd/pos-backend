# app/views.py
from decimal import Decimal
import io
from datetime import date, timedelta, timezone
from datetime import datetime, date as _date, datetime as _datetime
from django.core.exceptions import FieldError
from openpyxl import Workbook


from django.db import transaction
from django.db.models import Q, Sum, Count, F, DecimalField, ExpressionWrapper, Value as V
from django.db.models.functions import TruncDate, Coalesce
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from django.contrib.auth import get_user_model

from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework import serializers, viewsets, filters, permissions, status
from rest_framework.decorators import api_view, action, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework.generics import CreateAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework_simplejwt.authentication import JWTAuthentication

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from rest_framework import status
from django.contrib.auth.hashers import make_password

from .models import (
    Product, Category, Sale, Customer, SaleItem, Expense, Supplier, CustomerPayment,
    Purchase, PurchaseItem, SupplierPayment, Shop, UserProfile, PaymentRequest
)
from .serializers import (
    ProductSerializer, CategorySerializer, SaleSerializer,
    CustomerSerializer, ExpenseSerializer, SupplierSerializer,
    PurchaseSerializer, PurchaseItemSerializer, SupplierPaymentSerializer, CustomerPaymentSerializer,
    ShopRegistrationSerializer, PaymentRequestSerializer, SubscriptionStatusSerializer, UserProfileSerializer,
    ShopSerializer
)

User = get_user_model()


# ------------------------------------------------------------
# SHOP FILTER MIXIN FOR MULTI-TENANCY
# ------------------------------------------------------------
class ShopFilterMixin:
    """Mixin to filter queryset by current user's shop"""
    
    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.is_authenticated:
            profile = getattr(self.request.user, 'profile', None)
            if profile and profile.shop:
                return qs.filter(shop=profile.shop)
        return qs.none()  # Return empty if no shop


# -----------------------------
# Category & Product
# -----------------------------
class CategoryViewSet(ShopFilterMixin, viewsets.ModelViewSet):
    queryset = Category.objects.all().order_by("name")
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]


class ProductViewSet(ShopFilterMixin, viewsets.ModelViewSet):
    queryset = Product.objects.select_related("category").order_by("-id")
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ["title", "product_code", "sku", "barcode"]


# -----------------------------
# Sales
# -----------------------------
class SaleViewSet(ShopFilterMixin, viewsets.ModelViewSet):
    queryset = Sale.objects.all().order_by("-id")
    serializer_class = SaleSerializer
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=False)
        if not serializer.is_valid():
            return Response(
                {"success": False, "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get current shop
        profile = request.user.profile
        shop = profile.shop if profile else None
        
        items = request.data.get("items", [])
        product_ids = [i.get("product") for i in items if i.get("product")]
        products = {
            p.id: p
            for p in Product.objects.select_for_update().filter(id__in=product_ids, shop=shop)
        }

        # Stock check
        for item in items:
            pid = item.get("product")
            qty = int(item.get("quantity", 0))
            p = products.get(pid)
            if not p:
                return Response(
                    {"success": False, "error": f"Product ID {pid} not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )
            if p.stock < qty:
                return Response(
                    {
                        "success": False,
                        "error": f"Insufficient stock for {p.title}. Available: {p.stock}",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Save sale and deduct stock
        sale = serializer.save()
        for item in items:
            p = products[item["product"]]
            p.stock -= int(item["quantity"])
            p.save(update_fields=["stock"])

        return Response(
            {
                "success": True,
                "message": "Sale completed successfully, stock updated.",
                "data": self.get_serializer(sale).data,
            },
            status=status.HTTP_201_CREATED,
        )


@api_view(["GET"])
def product_lookup(request):
    """Lookup product by code or barcode (shop-scoped)"""
    code = request.query_params.get("code", "").strip()
    if not code:
        return Response({"error": "No code provided"}, status=400)

    # Get current shop
    profile = request.user.profile
    shop = profile.shop if profile else None
    
    try:
        product = Product.objects.get(
            Q(product_code__iexact=code) | Q(barcode__iexact=code),
            shop=shop
        )
        serializer = ProductSerializer(product, context={"request": request})
        return Response(serializer.data, status=200)
    except Product.DoesNotExist:
        return Response({"error": f"Product '{code}' not found"}, status=404)


# In invoice_view function:
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def invoice_view(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    serializer = SaleSerializer(sale, context={"request": request})
    return Response(serializer.data)


# -----------------------------
# Customers
# -----------------------------
class StandardPagination(PageNumberPagination):
    page_size = 12
    page_size_query_param = 'page_size'
    max_page_size = 100

class CustomerViewSet(ShopFilterMixin, viewsets.ModelViewSet):
    queryset = Customer.objects.all().order_by("-id")
    serializer_class = CustomerSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "phone"]
    ordering_fields = ["name", "points", "id"]
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = super().get_queryset()
    
        # Try different possible relationship names
        try:
        # First try 'sales' (most common custom name)
            qs = qs.annotate(sales_count=Count("sales"))
        except FieldError:
            try:
            # Then try 'sale_set' (Django default)
                qs = qs.annotate(sales_count=Count("sale_set"))
            except FieldError:
                try:
                # Try 'sale' (singular)
                    qs = qs.annotate(sales_count=Count("sale"))
                except FieldError:
                # If all fail, just return queryset without annotation
                    return qs
    
        return qs

    @action(detail=True, methods=["get"])
    def ledger(self, request, pk=None):
        customer = self.get_object()

        total_sales = Sale.objects.filter(customer=customer).aggregate(s=Sum("total"))["s"] or Decimal("0.00")
        total_paid_in_sale = Sale.objects.filter(customer=customer).aggregate(s=Sum("paid_amount"))["s"] or Decimal("0.00")
        total_repaid = CustomerPayment.objects.filter(customer=customer).aggregate(s=Sum("amount"))["s"] or Decimal("0.00")

        total_paid = total_paid_in_sale + total_repaid
        total_due = total_sales - total_paid

        entries = []

        sales = Sale.objects.filter(customer=customer).order_by("date", "id").prefetch_related("items__product")
        for s in sales:
            entries.append({
                "id": s.id,
                "model": "sale",
                "date": s.date.strftime("%Y-%m-%d"),
                "type": "Sale",
                "memo": f"INV-{s.id}",
                "total": float(s.total or 0),
                "paid_amount": float(s.paid_amount or 0),
                "due_amount": float(s.due_amount or 0),
                "payment_method": s.payment_method,
                "trx_id": s.trx_id,
                "items": [
                    {
                        "product": it.product.title,
                        "quantity": it.quantity,
                        "unit_price": float(it.price),
                        "total": float(it.total),
                    } for it in s.items.all()
                ],
                "debit": float(s.total or 0),
                "credit": 0.0,
                "balance": None,
            })

        payments = CustomerPayment.objects.filter(customer=customer).order_by("date", "id")
        for pay in payments:
            entries.append({
                "id": pay.id,
                "model": "payment",
                "date": pay.date.strftime("%Y-%m-%d"),
                "type": "Payment",
                "memo": pay.memo_no or "-",
                "remarks": pay.remarks or "",
                "amount": float(pay.amount or 0),
                "payment_method": pay.payment_method,
                "debit": 0.0,
                "credit": float(pay.amount or 0),
                "balance": None,
            })

        entries.sort(key=lambda r: (r["date"], r["type"] != "Sale"))

        running = 0.0
        for r in entries:
            running += (r.get("debit", 0.0) or 0.0) - (r.get("credit", 0.0) or 0.0)
            r["balance"] = float(running)

        return Response({
            "customer": {"id": customer.id, "name": customer.name, "phone": customer.phone},
            "summary": {
                "total_sales": float(total_sales),
                "total_paid": float(total_paid),
                "total_due": float(total_due),
            },
            "entries": entries,
        })

    @action(detail=True, methods=["post"])
    def repay(self, request, pk=None):
        customer = self.get_object()
        shop = request.user.profile.shop

        amount = Decimal(str(request.data.get("amount") or "0"))
        if amount <= 0:
            return Response({"detail": "Amount must be > 0"}, status=400)

        # Optional: block overpay
        total_sales = Sale.objects.filter(customer=customer).aggregate(s=Sum("total"))["s"] or Decimal("0.00")
        total_paid_in_sale = Sale.objects.filter(customer=customer).aggregate(s=Sum("paid_amount"))["s"] or Decimal("0.00")
        total_repaid = CustomerPayment.objects.filter(customer=customer).aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
        current_due = total_sales - (total_paid_in_sale + total_repaid)

        if amount > current_due:
            return Response({"detail": f"Overpay not allowed. Current due is {current_due}"}, status=400)

        pay = CustomerPayment.objects.create(
            shop=shop,
            customer=customer,
            amount=amount,
            payment_method=request.data.get("payment_method") or "cash",
            memo_no=request.data.get("memo_no"),
            remarks=request.data.get("remarks"),
        )

        return Response({"success": True, "payment": CustomerPaymentSerializer(pay).data})

# customer lookup by phone
@api_view(["GET"])
def customer_lookup(request):
    phone = request.query_params.get("phone", "").strip()
    if not phone:
        return Response({"error": "No phone provided"}, status=400)
    # Get current shop
    profile = request.user.profile
    shop = profile.shop if profile else None
    
    try:
        customer = Customer.objects.get(phone=phone, shop=shop)
        serializer = CustomerSerializer(customer)
        return Response(serializer.data, status=200)
    except Customer.DoesNotExist:
        return Response({"message": "New customer"}, status=404)

# In views.py, add these imports at the top
from .models import CustomerPayment
from .serializers import CustomerPaymentSerializer

# Add CustomerPaymentViewSet
class CustomerPaymentViewSet(ShopFilterMixin, viewsets.ModelViewSet):
    queryset = CustomerPayment.objects.all().order_by("-date", "-id")
    serializer_class = CustomerPaymentSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["customer__name", "customer__phone", "memo_no"]
    filterset_fields = ["customer", "payment_method"]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = serializer.save()
        
        return Response({
            "success": True,
            "message": "Customer payment recorded successfully.",
            "data": self.get_serializer(payment).data,
        }, status=status.HTTP_201_CREATED)


# Add CustomerLedgerView
class CustomerLedgerView(ShopFilterMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, customer_id):
        try:
            customer = Customer.objects.get(id=customer_id)
        except Customer.DoesNotExist:
            return Response({"error": "Customer not found"}, status=404)

        # Get all sales for this customer
        sales = Sale.objects.filter(customer=customer).order_by("date")
        
        # Get all payments for this customer
        payments = CustomerPayment.objects.filter(customer=customer).order_by("date")
        
        # Calculate totals
        total_sales = sales.aggregate(total=Coalesce(Sum("total"), V(0)))["total"]
        total_paid_from_sales = sales.aggregate(total=Coalesce(Sum("paid_amount"), V(0)))["total"]
        total_paid_from_payments = payments.aggregate(total=Coalesce(Sum("amount"), V(0)))["total"]
        total_paid = total_paid_from_sales + total_paid_from_payments
        total_due = total_sales - total_paid
        
        ledger = []
        
        # Add sales to ledger
        for sale in sales:
            ledger.append({
                "id": sale.id,
                "model": "sale",
                "date": str(sale.date),
                "type": "Sale",
                "invoice_no": f"INV-{sale.id}",
                "description": f"Sale #{sale.id}",
                "total": float(sale.total),
                "paid_amount": float(sale.paid_amount),
                "due_amount": float(sale.due_amount),
                "payment_method": sale.payment_method,
                "trx_id": sale.trx_id,
                "debit": float(sale.total),
                "credit": 0,
                "balance": None,
            })
        
        # Add payments to ledger
        for payment in payments:
            ledger.append({
                "id": payment.id,
                "model": "payment",
                "date": str(payment.date),
                "type": "Payment",
                "description": payment.remarks or "Payment Received",
                "memo_no": payment.memo_no or "-",
                "payment_method": payment.payment_method,
                "debit": 0,
                "credit": float(payment.amount),
                "balance": None,
            })
        
        # Sort by date and calculate running balance
        ledger = sorted(ledger, key=lambda x: x["date"])
        running = 0
        for row in ledger:
            running += row["debit"] - row["credit"]
            row["balance"] = running
        
        return Response({
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "phone": customer.phone,
                "points": customer.points,
            },
            "totals": {
                "total_sales": float(total_sales),
                "total_paid": float(total_paid),
                "total_due": float(total_due),
            },
            "ledger": ledger,
        })

class CustomerLedgerDetailView(ShopFilterMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, customer_id):
        try:
            customer = Customer.objects.get(id=customer_id, shop=request.user.profile.shop)
        except Customer.DoesNotExist:
            return Response({"error": "Customer not found"}, status=404)

        sales = Sale.objects.filter(customer=customer).order_by("date")
        
        payments = CustomerPayment.objects.filter(customer=customer).order_by("date")
        
        total_sales = sales.aggregate(total=Sum("total"))["total"] or Decimal("0.00")
        total_paid_from_sales = sales.aggregate(total=Sum("paid_amount"))["total"] or Decimal("0.00")
        total_paid_from_payments = payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        total_paid = total_paid_from_sales + total_paid_from_payments
        total_due = total_sales - total_paid
        
        ledger = []
        
 
        for sale in sales:
            ledger.append({
                "id": sale.id,
                "type": "বিক্রয়",
                "date": sale.date.strftime("%Y-%m-%d"),
                "invoice_no": f"INV-{sale.id}",
                "description": f"Sale #{sale.id}",
                "total": float(sale.total),
                "paid_amount": float(sale.paid_amount),
                "due_amount": float(sale.due_amount),
                "payment_method": sale.payment_method,
                "trx_id": sale.trx_id,
                "debit": float(sale.total),
                "credit": 0.0,
                "balance": None,
            })
        
        for payment in payments:
            ledger.append({
                "id": payment.id,
                "type": "Payment",
                "date": payment.date.strftime("%Y-%m-%d"),
                "description": payment.remarks or "Payment Received",
                "memo_no": payment.memo_no or "-",
                "payment_method": payment.payment_method,
                "debit": 0.0,
                "credit": float(payment.amount),
                "balance": None,
            })
        
        ledger = sorted(ledger, key=lambda x: x["date"])
        running = Decimal("0.00")
        for row in ledger:
            running += Decimal(str(row["debit"])) - Decimal(str(row["credit"]))
            row["balance"] = float(running)
        
        return Response({
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "phone": customer.phone,
                "points": customer.points,
            },
            "totals": {
                "total_sales": float(total_sales),
                "total_paid": float(total_paid),
                "total_due": float(total_due),
            },
            "ledger": ledger,
        })


# Add CustomerDueSummaryView
class CustomerDueSummaryView(ShopFilterMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        # Get all customers with their due amounts
        customers_with_due = []
        
        # Get current shop
        profile = request.user.profile
        shop = profile.shop if profile else None
        
        customers = Customer.objects.filter(shop=shop).order_by("name")
        
        for customer in customers:
            # Calculate customer's total due
            sales = Sale.objects.filter(customer=customer)
            payments = CustomerPayment.objects.filter(customer=customer)
            
            total_sales = sales.aggregate(total=Coalesce(Sum("total"), V(0)))["total"]
            total_paid_from_sales = sales.aggregate(total=Coalesce(Sum("paid_amount"), V(0)))["total"]
            total_paid_from_payments = payments.aggregate(total=Coalesce(Sum("amount"), V(0)))["total"]
            total_paid = total_paid_from_sales + total_paid_from_payments
            total_due = total_sales - total_paid
            
            if total_due > 0:
                customers_with_due.append({
                    "id": customer.id,
                    "name": customer.name,
                    "phone": customer.phone,
                    "total_due": float(total_due),
                    "last_sale_date": sales.last().date if sales.exists() else None,
                    "points": customer.points,
                })
        
        # Sort by highest due
        customers_with_due.sort(key=lambda x: x["total_due"], reverse=True)
        
        # Calculate grand total
        grand_total_due = sum(c["total_due"] for c in customers_with_due)
        
        return Response({
            "total_customers_with_due": len(customers_with_due),
            "grand_total_due": grand_total_due,
            "customers": customers_with_due,
        })


# -----------------------------
# KPI / Analytics
# -----------------------------
class SalesMetricsView(ShopFilterMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        today = date.today()
        start_of_month = today.replace(day=1)

        # Get current shop
        profile = request.user.profile
        shop = profile.shop if profile else None
        
        today_total = (
            Sale.objects.filter(shop=shop, date__date=today).aggregate(total=Sum("total"))["total"]
            or 0
        )
        month_total = (
            Sale.objects.filter(shop=shop, date__date__gte=start_of_month).aggregate(
                total=Sum("total")
            )["total"]
            or 0
        )
        products_in_stock = (
            Product.objects.filter(shop=shop).aggregate(total=Sum("stock"))["total"] or 0
        )

        top_product = (
            SaleItem.objects.filter(sale__shop=shop, sale__date__date__gte=start_of_month)
            .values("product__id", "product__title")
            .annotate(
                qty=Sum("quantity"),
                total=Sum(
                    F("price") * F("quantity"),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                ),
            )
            .order_by("-qty")
            .first()
        )

        return Response(
            {
                "today_total": today_total,
                "month_total": month_total,
                "products_in_stock": products_in_stock,
                "top_product": {
                    "id": top_product["product__id"] if top_product else None,
                    "title": top_product["product__title"] if top_product else "",
                    "qty": top_product["qty"] if top_product else 0,
                    "total": top_product["total"] if top_product else 0,
                },
            }
        )


class DailySalesView(ShopFilterMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        start = request.GET.get("from")
        end = request.GET.get("to")

        # Get current shop
        profile = request.user.profile
        shop = profile.shop if profile else None

        try:
            if not (start and end):
                today = date.today()
                start_d = today - timedelta(days=6)
                end_d = today
            else:
                start_d = datetime.strptime(start, "%Y-%m-%d").date()
                end_d = datetime.strptime(end, "%Y-%m-%d").date()
        except ValueError:
            return Response({"error": "from/to must be YYYY-MM-DD"}, status=400)

        qs = (
            Sale.objects.filter(shop=shop, date__date__range=[start_d, end_d])
            .annotate(day=TruncDate("date"))
            .values("day")
            .annotate(total=Sum("total"))
            .order_by("day")
        )
        data = [{"date": str(x["day"]), "total": x["total"] or 0} for x in qs]
        return Response(data)

class CategorySummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        start = request.GET.get("from")
        end = request.GET.get("to")

        shop = request.user.profile.shop

        if not (start and end):
            return Response({"detail": "from and to are required (YYYY-MM-DD)."}, status=400)

        qs = (
            SaleItem.objects.filter(sale__shop=shop, sale__date__date__range=[start, end])
            .values("product__category__name")
            .annotate(
                qty=Sum("quantity"),
                total=Sum(
                    F("price") * F("quantity"),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                ),
            )
            .order_by("-total")
        )

        data = [
            {
                "category": x["product__category__name"] or "Uncategorized",
                "qty": x["qty"] or 0,
                "total": x["total"] or 0,
            }
            for x in qs
        ]
        return Response(data)


class TopProductsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        start = request.GET.get("from")
        end = request.GET.get("to")
        limit = int(request.GET.get("limit", 5))

        shop = request.user.profile.shop

        if not (start and end):
            return Response({"detail": "from and to are required (YYYY-MM-DD)."}, status=400)

        qs = (
            SaleItem.objects.filter(sale__shop=shop, sale__date__date__range=[start, end])
            .values("product__id", "product__title")
            .annotate(
                qty=Sum("quantity"),
                total=Sum(
                    F("price") * F("quantity"),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                ),
            )
            .order_by("-qty")[:limit]
        )

        data = [
            {
                "id": x["product__id"],
                "title": x["product__title"],
                "qty": x["qty"] or 0,
                "total": x["total"] or 0,
            }
            for x in qs
        ]
        return Response(data)

class CategorySummaryView(ShopFilterMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        start = request.GET.get("from")
        end = request.GET.get("to")

        # Get current shop
        profile = request.user.profile
        shop = profile.shop if profile else None

        qs = (
            SaleItem.objects.filter(sale__shop=shop, sale__date__date__range=[start, end])
            .values("product__category__name")
            .annotate(
                qty=Sum("quantity"),
                total=Sum(
                    F("price") * F("quantity"),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                ),
            )
            .order_by("-total")
        )

        data = [
            {
                "category": x["product__category__name"] or "Uncategorized",
                "qty": x["qty"] or 0,
                "total": x["total"] or 0,
            }
            for x in qs
        ]
        return Response(data)


class TopProductsView(ShopFilterMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        start = request.GET.get("from")
        end = request.GET.get("to")
        limit = int(request.GET.get("limit", 5))

        # Get current shop
        profile = request.user.profile
        shop = profile.shop if profile else None

        qs = (
            SaleItem.objects.filter(sale__shop=shop, sale__date__date__range=[start, end])
            .values("product__id", "product__title")
            .annotate(
                qty=Sum("quantity"),
                total=Sum(
                    F("price") * F("quantity"),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                ),
            )
            .order_by("-qty")[:limit]
        )

        data = [
            {
                "id": x["product__id"],
                "title": x["product__title"],
                "qty": x["qty"] or 0,
                "total": x["total"] or 0,
            }
            for x in qs
        ]
        return Response(data)


# -----------------------------
# Expenses
# -----------------------------
class ExpenseViewSet(ShopFilterMixin, viewsets.ModelViewSet):
    queryset = Expense.objects.all().order_by("-date", "-id")
    serializer_class = ExpenseSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["category", "payment_method"]
    search_fields = ["category", "description"]

    def get_queryset(self):
        qs = super().get_queryset()
        f = self.request.query_params.get("from")
        t = self.request.query_params.get("to")
        if f and t:
            qs = qs.filter(date__range=[f, t])
        return qs


# In views.py, replace the ExpenseSummaryView class:

class ExpenseSummaryView(ShopFilterMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        f = request.GET.get("from")
        t = request.GET.get("to")

        # Get current shop
        profile = request.user.profile
        shop = profile.shop if profile else None
        
        # Get filtered queryset
        qs = Expense.objects.filter(shop=shop)
        
        if f and t:
            qs = qs.filter(date__range=[f, t])

        category_rows = qs.values("category").annotate(total=Sum("amount")).order_by("-total")
        grand_total = qs.aggregate(total=Sum("amount"))["total"] or 0

        daily_rows = (
            qs.annotate(day=TruncDate("date"))
            .values("day")
            .annotate(total=Sum("amount"))
            .order_by("day")
        )

        return Response(
            {
                "grand_total": grand_total,
                "by_category": [
                    {"category": r["category"], "total": r["total"] or 0}
                    for r in category_rows
                ],
                "by_day": [{"date": str(r["day"]), "total": r["total"] or 0} for r in daily_rows],
            }
        )


# -----------------------------
# Supplier + Purchases
# -----------------------------
class SupplierViewSet(ShopFilterMixin, viewsets.ModelViewSet):
    queryset = Supplier.objects.all().order_by("name")
    serializer_class = SupplierSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "phone"]

    @action(detail=True, methods=["get"])
    def ledger(self, request, pk=None):
        """GET /api/suppliers/<pk>/ledger/"""
        supplier = self.get_object()

        total_purchase = (
            Purchase.objects.filter(supplier=supplier).aggregate(s=Sum("total"))["s"] or 0
        )
        total_paid = (
            SupplierPayment.objects.filter(supplier=supplier).aggregate(s=Sum("amount"))["s"]
            or 0
        )
        total_due = total_purchase - total_paid

        entries = []

        purchases = Purchase.objects.filter(supplier=supplier).order_by("date", "id")
        for p in purchases:
            items = PurchaseItem.objects.filter(purchase=p).select_related("product")
            entries.append(
                {
                    "id": p.id,
                    "model": "purchase",
                    "date": p.date.strftime("%Y-%m-%d"),
                    "type": "Purchase",
                    "memo": p.invoice_no,
                    "remarks": p.remarks or "",
                    "subtotal": float(p.subtotal or 0),
                    "discount": float(p.discount or 0),
                    "total": float(p.total or 0),
                    "paid_amount": float(p.paid_amount or 0),
                    "due_amount": float(p.due_amount or 0),
                    "items": [
                        {
                            "product": it.product.title,
                            "quantity": it.quantity,
                            "unit_price": float(it.purchase_price),
                            "total": float(it.total),
                        }
                        for it in items
                    ],
                    "debit": float(p.total or 0),
                    "credit": 0.0,
                    "balance": None,
                }
            )

        payments = SupplierPayment.objects.filter(supplier=supplier).order_by("date", "id")
        for pay in payments:
            entries.append(
                {
                    "id": pay.id,
                    "model": "payment",
                    "date": pay.date.strftime("%Y-%m-%d"),
                    "type": "Payment",
                    "memo": pay.memo_no or "-",
                    "remarks": pay.remarks or "",
                    "amount": float(pay.amount or 0),
                    "payment_method": pay.payment_method,
                    "debit": 0.0,
                    "credit": float(pay.amount or 0),
                    "balance": None,
                }
            )

        entries.sort(key=lambda r: (r["date"], r["type"] != "Purchase"))
        running = 0.0
        for r in entries:
            running += (r.get("debit", 0.0) or 0.0) - (r.get("credit", 0.0) or 0.0)
            r["balance"] = float(running)

        return Response(
            {
                "supplier": supplier.name,
                "phone": supplier.phone,
                "address": supplier.address,
                "total_purchase": float(total_purchase),
                "total_paid": float(total_paid),
                "total_due": float(total_due),
                "ledger": entries,
            },
            status=status.HTTP_200_OK,
        )


class PurchaseViewSet(ShopFilterMixin, viewsets.ModelViewSet):
    queryset = Purchase.objects.all().order_by("-date", "-id")
    serializer_class = PurchaseSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ["invoice_no", "supplier__name"]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        purchase = serializer.save()
        return Response(
            {
                "success": True,
                "message": "Purchase recorded successfully.",
                "data": self.get_serializer(purchase).data,
            },
            status=status.HTTP_201_CREATED,
        )
    
    def update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return super().update(request, *args, **kwargs)


class PurchaseItemViewSet(ShopFilterMixin, viewsets.ReadOnlyModelViewSet):
    queryset = PurchaseItem.objects.all().select_related("purchase", "product")
    serializer_class = PurchaseItemSerializer
    permission_classes = [permissions.IsAuthenticated]


class SupplierPaymentViewSet(ShopFilterMixin, viewsets.ModelViewSet):
    queryset = SupplierPayment.objects.all().order_by("-date", "-id")
    serializer_class = SupplierPaymentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = serializer.save()
        return Response(
            {
                "success": True,
                "message": "Supplier payment added successfully.",
                "data": self.get_serializer(payment).data,
            },
            status=status.HTTP_201_CREATED,
        )


class SupplierLedgerView(ShopFilterMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, supplier_id):
        try:
            supplier = Supplier.objects.get(id=supplier_id)
        except Supplier.DoesNotExist:
            return Response({"error": "Supplier not found"}, status=404)

        purchases = Purchase.objects.filter(supplier=supplier).order_by("date")
        payments = SupplierPayment.objects.filter(supplier=supplier).order_by("date")

        total_purchase = purchases.aggregate(total=Coalesce(Sum("total"), V(0)))["total"]
        total_paid = payments.aggregate(total=Coalesce(Sum("amount"), V(0)))["total"]
        total_due = total_purchase - total_paid

        ledger = []

        for p in purchases:
            items = PurchaseItem.objects.filter(purchase=p).select_related("product")
            item_list = [
                {
                    "product": it.product.title,
                    "quantity": it.quantity,
                    "unit_price": float(it.purchase_price),
                    "total": float(it.total),
                }
                for it in items
            ]
            ledger.append(
                {
                    "date": str(p.date),
                    "type": "Purchase",
                    "memo": p.invoice_no,
                    "remarks": p.remarks or "",
                    "subtotal": float(p.subtotal),
                    "discount": float(p.discount),
                    "total": float(p.total),
                    "paid_amount": float(p.paid_amount),
                    "due_amount": float(p.due_amount),
                    "items": item_list,
                    "debit": float(p.total),
                    "credit": 0,
                    "balance": None,
                }
            )

        for pay in payments:
            ledger.append(
                {
                    "date": str(pay.date),
                    "type": "Payment",
                    "memo": pay.memo_no or "-",
                    "remarks": pay.remarks or "",
                    "amount": float(pay.amount),
                    "method": pay.payment_method,
                    "debit": 0,
                    "credit": float(pay.amount),
                    "balance": None,
                }
            )

        ledger = sorted(ledger, key=lambda x: x["date"])
        running = 0
        for row in ledger:
            running += row["debit"] - row["credit"]
            row["balance"] = running

        return Response(
            {
                "supplier": supplier.name,
                "phone": supplier.phone,
                "address": supplier.address,
                "total_purchase": total_purchase,
                "total_paid": total_paid,
                "total_due": total_due,
                "ledger": ledger,
            }
        )


# -----------------------------
# Sales Report
# -----------------------------
@api_view(["GET"])
def sales_report(request):
    """Sales report with shop filtering"""
    # Get current shop
    profile = request.user.profile
    shop = profile.shop if profile else None
    
    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")
    report_type = request.GET.get("type", "summary").lower()
    export = request.GET.get("export")  # 'pdf' or 'excel'

    if not (start_date and end_date):
        return Response({"error": "Please provide start_date and end_date."}, status=400)

    try:
        start_d = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_d = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        return Response({"error": "Dates must be in YYYY-MM-DD format"}, status=400)

    sales_qs = Sale.objects.filter(shop=shop, date__date__range=[start_d, end_d])

    # --------------- SUMMARY REPORT ------------------
    if report_type == "summary":
        sums = sales_qs.aggregate(
            total_sales=Coalesce(Sum("total"), Decimal("0.00")),
            total_discount=Coalesce(Sum("discount"), Decimal("0.00")),
        )

        # Optional Profit Calculation
        profit_value = None
        try:
            # Calculate profit for summary: total sales - total discount - redeemed points - purchase costs
            total_redeemed_points = sales_qs.aggregate(
                total_points=Coalesce(Sum("redeemed_points"), 0)
            )["total_points"]
            
            # Get total purchase cost from sale items
            total_purchase_cost = SaleItem.objects.filter(
                sale__in=sales_qs
            ).aggregate(
                total_cost=Coalesce(
                    Sum(F('quantity') * F('product__purchased_price')),
                    Decimal('0.00')
                )
            )["total_cost"] or Decimal('0.00')
            
            profit_value = (
                (sums["total_sales"] or Decimal('0.00')) - 
                (sums["total_discount"] or Decimal('0.00')) - 
                Decimal(total_redeemed_points) - 
                total_purchase_cost
            )
        except Exception as e:
            print(f"Profit calculation error: {e}")
            profit_value = None

        payload = {
            "report_type": "summary",
            "start_date": start_date,
            "end_date": end_date,
            "summary": {
                "total_sales": float(sums["total_sales"]),
                "total_discount": float(sums["total_discount"]),
                "total_profit": float(profit_value) if profit_value is not None else None,
            },
            "total_invoices": sales_qs.count(),
        }

        if export == "excel":
            import pandas as pd
            from io import BytesIO

            df = pd.DataFrame([{
                "Start Date": start_date,
                "End Date": end_date,
                "Total Sales": payload["summary"]["total_sales"],
                "Total Discount": payload["summary"]["total_discount"],
                "Total Profit": payload["summary"]["total_profit"],
                "Invoices Count": payload["total_invoices"],
            }])

            buffer = BytesIO()
            df.to_excel(buffer, index=False)
            buffer.seek(0)

            resp = HttpResponse(
                buffer,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            resp["Content-Disposition"] = f'attachment; filename="sales_summary_{start_date}_to_{end_date}.xlsx"'
            return resp

        if export == "pdf":
            from io import BytesIO
            buffer = BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4)
            elements = []
            styles = getSampleStyleSheet()

            elements.append(Paragraph(f"Sales Summary Report ({start_date} - {end_date})", styles["Heading2"]))
            elements.append(Spacer(1, 12))

            table_data = [[
                "Total Sales", "Total Discount", "Total Profit", "Invoices Count"
            ], [
                f'{payload["summary"]["total_sales"]:.2f}',
                f'{payload["summary"]["total_discount"]:.2f}',
                "-" if payload["summary"]["total_profit"] is None else f'{payload["summary"]["total_profit"]:.2f}',
                str(payload["total_invoices"]),
            ]]

            table = Table(table_data)
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.beige]),
            ]))

            elements.append(table)
            doc.build(elements)
            buffer.seek(0)
            resp = HttpResponse(buffer, content_type="application/pdf")
            resp["Content-Disposition"] = f'attachment; filename="sales_summary_{start_date}_to_{end_date}.pdf"'
            return resp

        return Response(payload)

    # --------------- DETAIL REPORT ------------------
    else:
        try:
            # Fetch sales with related data for profit calculation
            sales_with_items = sales_qs.select_related("customer").prefetch_related(
                "items", "items__product"
            ).order_by("date", "id")

            def fmt_date(d):
                if d is None:
                    return ""
                if isinstance(d, _datetime):
                    return d.strftime("%Y-%m-%d %H:%M")
                if isinstance(d, _date):
                    return d.strftime("%Y-%m-%d")
                return str(d)

            # Process records with profit calculation
            records = []
            total_sales = Decimal('0.00')
            total_discount = Decimal('0.00')
            total_redeemed_points = 0
            total_profit = Decimal('0.00')

            for sale in sales_with_items:
                # Calculate profit for this sale
                sale_profit = Decimal('0.00')
                total_purchase_cost = Decimal('0.00')
                
                # Calculate total purchase cost for all items in this sale
                for item in sale.items.all():
                    purchase_price = item.product.purchased_price if item.product.purchased_price else Decimal('0.00')
                    item_purchase_cost = purchase_price * item.quantity
                    total_purchase_cost += item_purchase_cost

                # Calculate profit: total - discount - redeemed points - purchase cost
                sale_profit = (
                    sale.total - 
                    sale.discount - 
                    Decimal(sale.redeemed_points) - 
                    total_purchase_cost
                )

                rec = {
                    "invoice_no": f"INV-{sale.id}",
                    "customer": sale.customer.name if sale.customer else "",
                    "date": fmt_date(sale.date),
                    "total": float(sale.total),
                    "discount": float(sale.discount),
                    "redeemed_points": sale.redeemed_points,
                    "profit": float(sale_profit),
                }
                
                records.append(rec)
                
                # Update totals
                total_sales += sale.total
                total_discount += sale.discount
                total_redeemed_points += sale.redeemed_points
                total_profit += sale_profit

            # Prepare payload
            payload = {
                "report_type": "detail",
                "start_date": start_date,
                "end_date": end_date,
                "records": records,
                "count": len(records),
                "totals": {
                    "total_sales": float(total_sales),
                    "total_discount": float(total_discount),
                    "total_redeemed_points": total_redeemed_points,
                    "total_profit": float(total_profit),
                },
            }

            # ----- Excel export -----
            if export == "excel":
                import pandas as pd
                from io import BytesIO

                # Create DataFrame from records
                df = pd.DataFrame(records)
                
                # Add totals row
                totals_row = {
                    "invoice_no": "TOTAL",
                    "customer": "",
                    "date": "",
                    "total": float(total_sales),
                    "discount": float(total_discount),
                    "redeemed_points": total_redeemed_points,
                    "profit": float(total_profit),
                }
                
                df = pd.concat([df, pd.DataFrame([totals_row])], ignore_index=True)
                
                buffer = BytesIO()
                df.to_excel(buffer, index=False)
                buffer.seek(0)

                resp = HttpResponse(
                    buffer,
                    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                resp["Content-Disposition"] = f'attachment; filename="sales_detail_{start_date}_to_{end_date}.xlsx"'
                return resp

            # ----- PDF export -----
            if export == "pdf":
                from io import BytesIO

                buffer = BytesIO()
                doc = SimpleDocTemplate(buffer, pagesize=A4)
                elements = []
                styles = getSampleStyleSheet()

                elements.append(
                    Paragraph(
                        f"Sales Detail Report ({start_date} - {end_date})",
                        styles["Heading2"],
                    )
                )
                elements.append(Spacer(1, 12))

                # Prepare table headers
                headers = ["Invoice No", "Customer", "Date", "Total", "Discount", "Redeemed Points", "Profit"]

                table_data = [headers]
                
                # Add data rows
                for r in records:
                    row = [
                        r["invoice_no"],
                        r["customer"],
                        r["date"],
                        f'{r["total"]:.2f}',
                        f'{r["discount"]:.2f}',
                        str(r["redeemed_points"]),
                        f'{r["profit"]:.2f}',
                    ]
                    table_data.append(row)
                
                # Add totals row
                totals_row = [
                    "TOTAL",
                    "",
                    "",
                    f'{float(total_sales):.2f}',
                    f'{float(total_discount):.2f}',
                    str(total_redeemed_points),
                    f'{float(total_profit):.2f}',
                ]
                table_data.append(totals_row)

                # Create and style table
                table = Table(table_data, repeatRows=1)
                table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                            ("GRID", (0, 0), (-1, -1), 1, colors.black),
                            ("BACKGROUND", (0, -1), (-1, -1), colors.lightgrey),
                            ("FONTWEIGHT", (0, -1), (-1, -1), "BOLD"),
                        ]
                    )
                )
                elements.append(table)
                doc.build(elements)
                buffer.seek(0)

                resp = HttpResponse(buffer, content_type="application/pdf")
                resp["Content-Disposition"] = f'attachment; filename="sales_detail_{start_date}_to_{end_date}.pdf"'
                return resp

            return Response(payload)

        except Exception as e:
            return Response({"error": f"detail report failed: {type(e).__name__}: {e}"}, status=400)


# -----------------------------
# Business Overview Views
# -----------------------------
class BusinessOverviewAPIView(ShopFilterMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")

        # Get current shop
        profile = request.user.profile
        shop = profile.shop if profile else None

        sales_filter = {"shop": shop}
        expenses_filter = {"shop": shop}
        purchases_filter = {"shop": shop}

        if start_date and end_date:
            sales_filter["date__date__range"] = [start_date, end_date]
            expenses_filter["date__range"] = [start_date, end_date]
            purchases_filter["date__range"] = [start_date, end_date]

        # Totals
        total_income = (
            Sale.objects.filter(**sales_filter)
            .aggregate(total=Coalesce(Sum("total"), Decimal("0.00")))
            ["total"]
        )
        total_expense = (
            Expense.objects.filter(**expenses_filter)
            .aggregate(total=Coalesce(Sum("amount"), Decimal("0.00")))
            ["total"]
        )
        total_purchase = (
            Purchase.objects.filter(**purchases_filter)
            .aggregate(total=Coalesce(Sum("total"), Decimal("0.00")))
            ["total"]
        )

        # Profits
        gross_profit = total_income - total_purchase
        net_profit = gross_profit - total_expense

        # Inventory value
        stock_value_expr = ExpressionWrapper(
            F("stock") * F("purchased_price"),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
        total_stock_value = (
            Product.objects.filter(shop=shop).aggregate(
                total=Coalesce(Sum(stock_value_expr), Decimal("0.00"))
            )["total"]
            or Decimal("0.00")
        )

        # Fixed costs
        fixed_cost = (
            Expense.objects.filter(**expenses_filter)
            .filter(category__icontains="rent")
            .aggregate(total=Coalesce(Sum("amount"), Decimal("0.00")))["total"]
        ) + (
            Expense.objects.filter(**expenses_filter)
            .filter(category__icontains="salary")
            .aggregate(total=Coalesce(Sum("amount"), Decimal("0.00")))["total"]
        )

        # Cash flow & growth
        cash_flow = total_income - total_expense
        business_growth = (
            (gross_profit / total_purchase * 100)
            if total_purchase and total_purchase > 0
            else Decimal("0.00")
        )

        # Capital investment
        capital_investment = total_purchase

        return Response(
            {
                "total_income": float(total_income),
                "total_expense": float(total_expense),
                "total_purchase": float(total_purchase),
                "gross_profit": float(gross_profit),
                "net_profit": float(net_profit),
                "fixed_cost": float(fixed_cost),
                "cash_flow": float(cash_flow),
                "business_growth": float(business_growth),
                "total_stock_value": float(total_stock_value),
                "capital_investment": float(capital_investment),
            }
        )


class BusinessOverviewTimeseriesAPIView(ShopFilterMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")

        # Get current shop
        profile = request.user.profile
        shop = profile.shop if profile else None

        sales_filter = {"shop": shop}
        expenses_filter = {"shop": shop}
        purchases_filter = {"shop": shop}

        if start_date and end_date:
            sales_filter["date__date__range"] = [start_date, end_date]
            expenses_filter["date__range"] = [start_date, end_date]
            purchases_filter["date__range"] = [start_date, end_date]

        sales = (
            Sale.objects.filter(**sales_filter)
            .annotate(d=TruncDate("date"))
            .values("d")
            .annotate(total=Sum("total"))
            .order_by("d")
        )
        expenses = (
            Expense.objects.filter(**expenses_filter)
            .annotate(d=TruncDate("date"))
            .values("d")
            .annotate(total=Sum("amount"))
            .order_by("d")
        )
        purchases = (
            Purchase.objects.filter(**purchases_filter)
            .annotate(d=TruncDate("date"))
            .values("d")
            .annotate(total=Sum("total"))
            .order_by("d")
        )

        all_dates = sorted(
            {*[s["d"] for s in sales], *[e["d"] for e in expenses], *[p["d"] for p in purchases]}
        )
        sales_map = {x["d"]: x["total"] or 0 for x in sales}
        exp_map = {x["d"]: x["total"] or 0 for x in expenses}
        pur_map = {x["d"]: x["total"] or 0 for x in purchases}

        labels = [d.isoformat() for d in all_dates]
        income = [float(sales_map.get(d, 0)) for d in all_dates]
        expense = [float(exp_map.get(d, 0)) for d in all_dates]
        purchase = [float(pur_map.get(d, 0)) for d in all_dates]
        cash_flow = [i - e for i, e in zip(income, expense)]
        net_profit = [i - e - p for i, e, p in zip(income, expense, purchase)]

        return Response(
            {
                "labels": labels,
                "income": income,
                "expense": expense,
                "purchase": purchase,
                "cash_flow": cash_flow,
                "net_profit": net_profit,
            }
        )


class BusinessOverviewExportPDF(ShopFilterMixin, APIView):
    authentication_classes = [JWTAuthentication] 
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")

        # Get current shop
        profile = request.user.profile
        shop = profile.shop if profile else None
        
        # Get summary data
        sales_filter = {"shop": shop}
        expenses_filter = {"shop": shop}
        purchases_filter = {"shop": shop}

        if start_date and end_date:
            sales_filter["date__date__range"] = [start_date, end_date]
            expenses_filter["date__range"] = [start_date, end_date]
            purchases_filter["date__range"] = [start_date, end_date]

        total_income = (
            Sale.objects.filter(**sales_filter)
            .aggregate(total=Coalesce(Sum("total"), Decimal("0.00")))
            ["total"]
        )
        total_expense = (
            Expense.objects.filter(**expenses_filter)
            .aggregate(total=Coalesce(Sum("amount"), Decimal("0.00")))
            ["total"]
        )
        total_purchase = (
            Purchase.objects.filter(**purchases_filter)
            .aggregate(total=Coalesce(Sum("total"), Decimal("0.00")))
            ["total"]
        )

        # Profits
        gross_profit = total_income - total_purchase
        net_profit = gross_profit - total_expense

        # Inventory value
        stock_value_expr = ExpressionWrapper(
            F("stock") * F("purchased_price"),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
        total_stock_value = (
            Product.objects.filter(shop=shop).aggregate(
                total=Coalesce(Sum(stock_value_expr), Decimal("0.00"))
            )["total"]
            or Decimal("0.00")
        )

        # Fixed costs
        fixed_cost = (
            Expense.objects.filter(**expenses_filter)
            .filter(category__icontains="rent")
            .aggregate(total=Coalesce(Sum("amount"), Decimal("0.00")))["total"]
        ) + (
            Expense.objects.filter(**expenses_filter)
            .filter(category__icontains="salary")
            .aggregate(total=Coalesce(Sum("amount"), Decimal("0.00")))["total"]
        )

        # Cash flow & growth
        cash_flow = total_income - total_expense
        business_growth = (
            (gross_profit / total_purchase * 100)
            if total_purchase and total_purchase > 0
            else Decimal("0.00")
        )

        # Capital investment
        capital_investment = total_purchase

        summary = {
            "total_income": float(total_income),
            "total_expense": float(total_expense),
            "total_purchase": float(total_purchase),
            "gross_profit": float(gross_profit),
            "net_profit": float(net_profit),
            "fixed_cost": float(fixed_cost),
            "cash_flow": float(cash_flow),
            "total_stock_value": float(total_stock_value),
            "capital_investment": float(capital_investment),
            "business_growth": float(business_growth),
        }

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []

        story.append(Paragraph("Business Overview Report", styles["Title"]))
        story.append(Paragraph(f"Shop: {shop.shop_name if shop else 'Unknown'}", styles["Normal"]))
        if start_date and end_date:
            story.append(Paragraph(f"Period: {start_date} to {end_date}", styles["Normal"]))
        story.append(Spacer(1, 12))

        table_data = [
            ["Metric", "Amount"],
            ["Total Income", f'{summary["total_income"]:.2f}'],
            ["Total Expense", f'{summary["total_expense"]:.2f}'],
            ["Total Purchase", f'{summary["total_purchase"]:.2f}'],
            ["Gross Profit", f'{summary["gross_profit"]:.2f}'],
            ["Net Profit", f'{summary["net_profit"]:.2f}'],
            ["Fixed Cost", f'{summary["fixed_cost"]:.2f}'],
            ["Cash Flow", f'{summary["cash_flow"]:.2f}'],
            ["Inventory Value", f'{summary["total_stock_value"]:.2f}'],
            ["Capital Investment", f'{summary["capital_investment"]:.2f}'],
            ["Business Growth %", f'{summary["business_growth"]:.2f}%'],
        ]

        t = Table(table_data, colWidths=[220, 220])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ]
            )
        )
        story.append(t)
        doc.build(story)

        buffer.seek(0)
        response = HttpResponse(buffer, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="business_overview_{start_date}_{end_date}.pdf"'
        )
        return response


class BusinessOverviewExportExcel(ShopFilterMixin, APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")

        # Get current shop
        profile = request.user.profile
        shop = profile.shop if profile else None
        
        # Get summary data
        sales_filter = {"shop": shop}
        expenses_filter = {"shop": shop}
        purchases_filter = {"shop": shop}

        if start_date and end_date:
            sales_filter["date__date__range"] = [start_date, end_date]
            expenses_filter["date__range"] = [start_date, end_date]
            purchases_filter["date__range"] = [start_date, end_date]

        total_income = (
            Sale.objects.filter(**sales_filter)
            .aggregate(total=Coalesce(Sum("total"), Decimal("0.00")))
            ["total"]
        )
        total_expense = (
            Expense.objects.filter(**expenses_filter)
            .aggregate(total=Coalesce(Sum("amount"), Decimal("0.00")))
            ["total"]
        )
        total_purchase = (
            Purchase.objects.filter(**purchases_filter)
            .aggregate(total=Coalesce(Sum("total"), Decimal("0.00")))
            ["total"]
        )

        # Profits
        gross_profit = total_income - total_purchase
        net_profit = gross_profit - total_expense

        # Inventory value
        stock_value_expr = ExpressionWrapper(
            F("stock") * F("purchased_price"),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
        total_stock_value = (
            Product.objects.filter(shop=shop).aggregate(
                total=Coalesce(Sum(stock_value_expr), Decimal("0.00"))
            )["total"]
            or Decimal("0.00")
        )

        # Fixed costs
        fixed_cost = (
            Expense.objects.filter(**expenses_filter)
            .filter(category__icontains="rent")
            .aggregate(total=Coalesce(Sum("amount"), Decimal("0.00")))["total"]
        ) + (
            Expense.objects.filter(**expenses_filter)
            .filter(category__icontains="salary")
            .aggregate(total=Coalesce(Sum("amount"), Decimal("0.00")))["total"]
        )

        # Cash flow & growth
        cash_flow = total_income - total_expense
        business_growth = (
            (gross_profit / total_purchase * 100)
            if total_purchase and total_purchase > 0
            else Decimal("0.00")
        )

        # Capital investment
        capital_investment = total_purchase

        summary = {
            "total_income": float(total_income),
            "total_expense": float(total_expense),
            "total_purchase": float(total_purchase),
            "gross_profit": float(gross_profit),
            "net_profit": float(net_profit),
            "fixed_cost": float(fixed_cost),
            "cash_flow": float(cash_flow),
            "total_stock_value": float(total_stock_value),
            "capital_investment": float(capital_investment),
            "business_growth": float(business_growth),
        }

        wb = Workbook()
        ws = wb.active
        ws.title = "Business Overview"
        ws.append(["Business Overview Report"])
        ws.append([f"Shop: {shop.shop_name if shop else 'Unknown'}"])
        if start_date and end_date:
            ws.append([f"Period: {start_date} to {end_date}"])
        ws.append([])
        ws.append(["Metric", "Amount"])

        for k, v in [
            ("Total Income", summary["total_income"]),
            ("Total Expense", summary["total_expense"]),
            ("Total Purchase", summary["total_purchase"]),
            ("Gross Profit", summary["gross_profit"]),
            ("Net Profit", summary["net_profit"]),
            ("Fixed Cost", summary["fixed_cost"]),
            ("Cash Flow", summary["cash_flow"]),
            ("Inventory Value", summary["total_stock_value"]),
            ("Capital Investment", summary["capital_investment"]),
            ("Business Growth %", summary["business_growth"]),
        ]:
            ws.append([k, v])

        stream = io.BytesIO()
        wb.save(stream)
        stream.seek(0)
        response = HttpResponse(
            stream.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="business_overview_{start_date}_{end_date}.xlsx"'
        )
        return response


# -----------------------------
# JWT Authentication Views
# -----------------------------
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

class LoginView(APIView):
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        print("=== LOGIN ATTEMPT ===")
        print("Username:", request.data.get('username'))
        
        username = request.data.get('username')
        password = request.data.get('password')
        
        if not username or not password:
            return Response({
                "detail": "Username and password are required."
            }, status=400)
        
        # First, try to authenticate the user
        from django.contrib.auth import authenticate
        user = authenticate(username=username, password=password)
        
        if user is None:
            print("Authentication failed - invalid credentials")
            return Response({
                "detail": "Invalid username or password."
            }, status=400)
        
        print(f"✓ User authenticated: {user.username}")
        
        # Check if user has profile and shop
        if not hasattr(user, 'profile'):
            print("✗ User has no profile")
            return Response({
                "detail": "User profile not found. Please contact support."
            }, status=400)
        
        if not hasattr(user.profile, 'shop'):
            print("✗ User profile has no shop")
            return Response({
                "detail": "Shop not found for user."
            }, status=400)
        
        shop = user.profile.shop
        print(f"✓ User's shop: {shop.shop_name} (ID: {shop.shop_id})")
        
        # IMPORTANT: Check if payment was verified but shop not activated
        if hasattr(shop, 'payment_request'):
            pr = shop.payment_request
            print(f"Payment request found: Verified={pr.is_verified}")
            
            if pr.is_verified and not shop.is_active:
                print(f"⚠️ Payment verified but shop not active. Activating now...")
                if shop.plan == "monthly":
                    shop.activate_monthly()
                elif shop.plan == "yearly":
                    shop.activate_yearly()
                else:
                    shop.is_active = True
                    shop.save()
                print(f"✓ Shop activated after payment verification: {shop.is_active}")
        
        # Check if trial expired
        if shop.plan == "trial" and shop.expire_date and shop.expire_date < date.today():
            print("✗ Trial expired")
            shop.is_active = False
            shop.save()
        
        # Check if shop is active
        if not shop.is_active:
            print("✗ Shop is not active")
            
            # Check if there's a pending payment request
            if hasattr(shop, 'payment_request'):
                pr = shop.payment_request
                if pr.is_verified:
                    response_data = {
                        "detail": "Payment verified but activation pending. Please try logging in again.",
                        "shop_id": shop.shop_id,
                        "plan": shop.plan,
                        "payment_verified": True,
                        "is_active": False,
                        "error_code": "ACTIVATION_PENDING"
                    }
                else:
                    response_data = {
                        "detail": "Payment pending verification. Please wait for admin approval.",
                        "shop_id": shop.shop_id,
                        "plan": shop.plan,
                        "is_active": False,
                        "payment_submitted": True,
                        "error_code": "PAYMENT_PENDING"
                    }
            else:
                response_data = {
                    "detail": "Your subscription is inactive. Please make payment to activate.",
                    "shop_id": shop.shop_id,
                    "plan": shop.plan,
                    "is_active": False,
                    "expire_date": str(shop.expire_date) if shop.expire_date else None,
                    "requires_payment": shop.plan in ["monthly", "yearly"],
                    "error_code": "SUBSCRIPTION_INACTIVE"
                }
                
                if shop.plan == "trial":
                    response_data["detail"] = "Your trial has expired. Please upgrade to continue."
                    response_data["error_code"] = "TRIAL_EXPIRED"
            
            return Response(response_data, status=402)
        
        print("✓ Shop is active, generating tokens")
        
        # Generate JWT tokens manually
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(user)
        
        response_data = {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email if user.email else ""
            },
            "shop": {
                "shop_id": shop.shop_id,
                "shop_name": shop.shop_name,
                "plan": shop.plan,
                "is_active": shop.is_active,
                "expire_date": str(shop.expire_date) if shop.expire_date else None,
                "logo_url": shop.logo.url if shop.logo else None
            }
        }
        
        print("✓ Login successful")
        return Response(response_data, status=200)
    
# Shop Registration & Subscription
# -----------------------------
class ShopRegistrationView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = ShopRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Create Shop
        shop = Shop.objects.create(
            shop_name=data["shop_name"],
            location=data.get("location", ""),
            phone=data["phone"],
            email_or_link=data.get("email_or_link", ""),
            owner_name=data["owner_name"],
            logo=request.FILES.get("logo"),
            plan=data["subscription_plan"],
            is_active=False
        )

        # Activate trial instantly
        if data["subscription_plan"] == "trial":
            shop.activate_trial()
            message = "🎉 Trial activated! You can login now."
        else:
            message = "✅ Registration successful! Please complete payment verification."

        # Create User
        User = get_user_model()
        user = User.objects.create_user(
            username=data["username"],
            password=data["password"]
        )

        UserProfile.objects.create(
            user=user,
            shop=shop,
            role="admin",  # Shop creator is admin
            is_owner=True,  # Shop creator is the owner
            profile_picture=None
        )

        response = {
            "success": True,
            "message": message,
            "shop_id": shop.shop_id,
            "logo": shop.logo.url if shop.logo else None,
            "plan": shop.plan,
            "is_active": shop.is_active,
            "expire_date": shop.expire_date,
            "requires_payment": shop.plan in ["monthly", "yearly"],
            "phone": shop.phone
        }

        # If paid plan, show payment instructions
        if shop.plan in ["monthly", "yearly"]:
            response["payment_instructions"] = {
                "message": "Please send payment and submit verification",
                "bkash": "01791927084",
                "nagad": "01791927084",
                "amount": 750 if shop.plan == "monthly" else 7990,
                "note": "After payment, submit the last 4 digits of sender number."
            }

        return Response(response, status=201)

# Update the CreatePaymentRequestView in views.py:
class CreatePaymentRequestView(CreateAPIView):
    serializer_class = PaymentRequestSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        print("=== PAYMENT REQUEST RECEIVED ===")
        print("Request data:", request.data)
        print("Files:", request.FILES)
        
        shop_id = request.data.get("shop_id")
        print(f"Shop ID: {shop_id}")
        
        try:
            shop = Shop.objects.get(shop_id=shop_id)
            print(f"Shop found: {shop.shop_name}, Plan: {shop.plan}")
        except Shop.DoesNotExist:
            print(f"Shop not found: {shop_id}")
            return Response({"detail": "Shop not found."}, status=404)

        # Prevent duplicate verified requests
        existing = getattr(shop, "payment_request", None)
        if existing:
            print(f"Existing payment request found: {existing.id}, Verified: {existing.is_verified}")
            if existing.is_verified:
                return Response({"detail": "Payment already verified."}, status=400)
            existing.delete()  # remove old unverified request
            print("Old unverified request deleted")
        
        # Get amount from request (it comes as string from FormData)
        submitted_amount_str = request.data.get("amount", "0")
        try:
            submitted_amount = int(submitted_amount_str)
        except ValueError:
            submitted_amount = 0
            
        print(f"Submitted amount: {submitted_amount} (as string: '{submitted_amount_str}')")
        
        # Calculate expected amount based on plan
        if shop.plan == "monthly":
            expected_amount = 750
        elif shop.plan == "yearly":
            expected_amount = 7990
        else:
            expected_amount = 0
            
        print(f"Expected amount for {shop.plan} plan: {expected_amount}")
        
        if submitted_amount != expected_amount:
            return Response({
                "detail": f"Invalid amount. Expected {expected_amount} tk for {shop.plan} plan, got {submitted_amount} tk."
            }, status=400)

        # Prepare data for serializer
        payment_data = {
            "method": request.data.get("method"),
            "sender_last4": request.data.get("sender_last4"),
            "amount": submitted_amount,
            "transaction_id": request.data.get("transaction_id", ""),
        }
        
        print("Payment data for serializer:", payment_data)
        
        # Handle file if present
        if request.FILES.get("screenshot"):
            payment_data["screenshot"] = request.FILES["screenshot"]
            print("Screenshot file received")
        
        serializer = self.get_serializer(data=payment_data)
        
        if serializer.is_valid():
            print("Serializer is valid")
            payment_request = serializer.save(shop=shop)
            print(f"Payment request created: {payment_request.id}")
            
            return Response({
                "detail": "Payment request submitted successfully.",
                "shop_id": shop.shop_id,
                "payment_id": payment_request.id,
                "status": "pending",
                "message": "Your payment details have been received. Admin will verify and activate your shop shortly."
            }, status=201)
        else:
            print("Serializer errors:", serializer.errors)
            return Response({
                "detail": "Invalid payment data.",
                "errors": serializer.errors
            }, status=400)


class AdminVerifyPaymentView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, shop_id):
        try:
            shop = Shop.objects.get(shop_id=shop_id)
        except Shop.DoesNotExist:
            return Response({"detail": "Shop not found."}, status=404)

        # Check if payment request exists
        if not hasattr(shop, "payment_request"):
            return Response({"detail": "No payment request found for this shop."}, status=404)

        pr = shop.payment_request

        if pr.is_verified:
            return Response({"detail": "Payment already verified."}, status=400)

        # Mark as verified
        pr.is_verified = True
        pr.verified_at = timezone.now()
        pr.verified_by = request.user
        pr.save()

        # Activate subscription based on plan
        if shop.plan == "monthly":
            shop.activate_monthly()
        elif shop.plan == "yearly":
            shop.activate_yearly()
        else:
            shop.is_active = True
            shop.save()

        # Send SMS notification (implement your SMS service)
        self.send_activation_notification(shop)

        return Response({
            "detail": "Payment verified and subscription activated successfully.",
            "shop": {
                "shop_id": shop.shop_id,
                "shop_name": shop.shop_name,
                "plan": shop.plan,
                "is_active": shop.is_active,
                "expire_date": shop.expire_date,
                "activated_at": timezone.now().isoformat()
            }
        })
    
class PaymentVerificationStatusView(APIView):
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        shop_id = request.query_params.get('shop_id')
        if not shop_id:
            return Response({"detail": "Shop ID is required"}, status=400)
        
        try:
            shop = Shop.objects.get(shop_id=shop_id)
            
            response_data = {
                "shop_id": shop.shop_id,
                "shop_name": shop.shop_name,
                "plan": shop.plan,
                "is_active": shop.is_active,
                "expire_date": shop.expire_date,
                "status": "active" if shop.is_active else "inactive"
            }
            
            # Add payment request info if exists
            if hasattr(shop, "payment_request"):
                pr = shop.payment_request
                response_data["payment_request"] = {
                    "method": pr.method,
                    "amount": pr.amount,
                    "is_verified": pr.is_verified,
                    "created_at": pr.created_at,
                    "verified_at": pr.verified_at if pr.is_verified else None
                }
                response_data["status"] = "verified" if pr.is_verified else "pending_verification"
            
            return Response(response_data)
            
        except Shop.DoesNotExist:
            return Response({"detail": "Shop not found"}, status=404)
    
    def send_activation_notification(self, shop):
        """Send activation notification to shop owner"""
        # Implement SMS/email notification here
        print(f"Shop {shop.shop_name} ({shop.shop_id}) activated!")
        print(f"Phone: {shop.phone}")
        print(f"Plan: {shop.plan}, Expires: {shop.expire_date}")
    
    def send_activation_sms(self, shop):
        """Send activation SMS to shop owner"""
        # Implement SMS sending here (Twilio, SMS API, etc.)
        message = f"Your shop {shop.shop_name} has been activated! Login at https://yourdomain.com"
        print(f"SMS to {shop.phone}: {message}")
        # Actual SMS sending code would go here

class SubscriptionRequiredView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        profile = getattr(request.user, 'profile', None)
        if not profile:
            return Response({"detail": "User profile not found"}, status=400)
        
        shop = profile.shop
        return Response({
            "detail": "Subscription required to access this feature.",
            "shop_id": shop.shop_id,
            "shop_name": shop.shop_name,
            "plan": shop.plan,
            "is_active": shop.is_active,
            "expire_date": str(shop.expire_date) if shop.expire_date else None,
            "requires_payment": shop.plan in ["monthly", "yearly"] and not shop.is_active,
            "error_code": "SUBSCRIPTION_REQUIRED"
        }, status=402)


class SubscriptionStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        shop = request.user.profile.shop

        data = {
            "shop_id": shop.shop_id,
            "shop_name": shop.shop_name,
            "logo": shop.logo.url if shop.logo else None,
            "plan": shop.plan,
            "is_active": shop.is_active,
            "expire_date": shop.expire_date
        }

        return Response(data)


class UpdateShopLogoView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        shop = request.user.profile.shop

        new_logo = request.FILES.get("logo")
        if not new_logo:
            return Response({"detail": "Logo file required."}, status=400)

        shop.logo = new_logo
        shop.save()

        return Response({
            "detail": "Shop logo updated successfully.",
            "logo_url": shop.logo.url
        })


class UpdateProfilePictureView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        profile = request.user.profile
        pp = request.FILES.get("profile_picture")

        if not pp:
            return Response({"detail": "Profile picture required."}, status=400)

        profile.profile_picture = pp
        profile.save()

        return Response({
            "detail": "Profile picture updated.",
            "profile_picture_url": profile.profile_picture.url
        })

class ShopUserViewSet(viewsets.ModelViewSet):
    """
    Full CRUD for shop users (create cashiers/managers)
    Only shop admin can manage users
    """
    queryset = UserProfile.objects.select_related('user', 'shop')
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_permissions(self):
        """
        Only allow admin users to manage shop users
        """
        # Check if user is admin for write operations
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            profile = self.request.user.profile
            if profile.role != 'admin':
                raise PermissionDenied("Only shop admins can manage users")
        return super().get_permissions()
    
    def get_queryset(self):
        """Return only users from current user's shop"""
        shop = self.request.user.profile.shop
        return UserProfile.objects.filter(shop=shop).order_by('-id')
    
    def list(self, request, *args, **kwargs):
        """List users with current user marked"""
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        
        # Add current user info to response
        current_user_data = {
            'id': request.user.profile.id,
            'username': request.user.username,
            'email': request.user.email,
            'role': request.user.profile.role,
            'is_owner': request.user.profile.is_owner,
            'is_current_user': True
        }
        
        response_data = {
            'users': serializer.data,
            'current_user': current_user_data
        }
        
        return Response(response_data)
    
    def create(self, request, *args, **kwargs):
        """Create new shop user"""
        username = request.data.get('username')
        email = request.data.get('email', '')
        password = request.data.get('password')
        role = request.data.get('role', 'cashier')
        
        # Validate required fields
        if not all([username, password]):
            return Response({
                "detail": "Username and password are required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate role
        valid_roles = ['admin', 'manager', 'cashier']
        if role not in valid_roles:
            return Response({
                "detail": f"Invalid role. Choose from: {', '.join(valid_roles)}"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if username already exists
        if User.objects.filter(username=username).exists():
            return Response({
                "detail": "Username already exists"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if email already exists
        if email and User.objects.filter(email=email).exists():
            return Response({
                "detail": "Email already exists"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Create user
        user = User.objects.create_user(
            username=username,
            email=email if email else '',
            password=password
        )
        
        # Create profile
        shop = request.user.profile.shop
        profile = UserProfile.objects.create(
            user=user,
            shop=shop,
            role=role,
            is_owner=False  # Never set new users as owner
        )
        
        serializer = self.get_serializer(profile)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    def update(self, request, *args, **kwargs):
        """Update user (role changes, etc.)"""
        instance = self.get_object()
        
        # Prevent updating owner status
        if 'is_owner' in request.data:
            return Response({
                "detail": "Cannot change owner status"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Update user fields if provided
        if 'email' in request.data:
            instance.user.email = request.data['email']
            instance.user.save()
        
        # Update profile
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        
        return Response(serializer.data)
    
    def destroy(self, request, *args, **kwargs):
        """Delete user (can't delete shop owner)"""
        instance = self.get_object()
        
        # Check if trying to delete current user
        if instance.user == request.user:
            return Response({
                "detail": "Cannot delete your own account"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if trying to delete shop owner
        if instance.is_owner:
            return Response({
                "detail": "Cannot delete shop owner"
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Delete the user
        username = instance.user.username
        instance.user.delete()  # This will cascade delete the profile
        
        return Response({
            "success": True,
            "message": f"User {username} deleted successfully"
        }, status=status.HTTP_200_OK)


# REMOVE or COMMENT OUT the duplicate function
# @api_view(["POST"])
# @permission_classes([permissions.IsAuthenticated])
# def create_shop_user(request):
#     # This is now handled by ShopUserViewSet.create()
#     pass


@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated])
def shop_settings(request):
    profile = request.user.profile
    shop = profile.shop

    if request.method == "GET":
        # ✅ Return the structure Vue component expects
        return Response({
            "shop": ShopSerializer(shop, context={'request': request}).data,
            "user": {
                "role": profile.role,
                "is_owner": profile.is_owner
            }
        })

    # PUT (Update shop) - Only owner can update
    if not profile.is_owner:
        return Response({
            "detail": "Only the shop owner can update settings."
        }, status=status.HTTP_403_FORBIDDEN)

    # Handle logo upload separately
    logo_file = request.FILES.get('logo')
    if logo_file:
        shop.logo = logo_file
    
    # Update other fields
    serializer = ShopSerializer(shop, data=request.data, partial=True, context={'request': request})
    if serializer.is_valid():
        serializer.save()
        return Response({
            "success": True,
            "shop": serializer.data,
            "user": {
                "role": profile.role,
                "is_owner": profile.is_owner
            }
        })
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_user_password(request, user_id):
    """
    Update password for a user (admin can update any user's password)
    OR user can update their own password
    """
    try:
        # Get target user profile
        if user_id == request.user.profile.id:
            # User updating their own password
            target_profile = request.user.profile
        else:
            # Admin updating another user's password
            admin_profile = request.user.profile
            if admin_profile.role != 'admin':
                return Response({
                    "detail": "Only admin can update other users' passwords"
                }, status=status.HTTP_403_FORBIDDEN)
            
            target_profile = UserProfile.objects.get(
                id=user_id,
                shop=admin_profile.shop
            )
    except UserProfile.DoesNotExist:
        return Response({
            "detail": "User not found"
        }, status=status.HTTP_404_NOT_FOUND)
    
    new_password = request.data.get('password')
    if not new_password or len(new_password) < 6:
        return Response({
            "detail": "Password is required and must be at least 6 characters"
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Update password
    target_profile.user.set_password(new_password)
    target_profile.user.save()
    
    return Response({
        "success": True,
        "message": f"Password updated for {target_profile.user.username}"
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_current_user_profile(request):
    profile = request.user.profile
    shop = profile.shop

    logo_url = None
    if shop.logo:
        logo_url = request.build_absolute_uri(shop.logo.url)

    return Response({
        "id": profile.id,
        "user_id": request.user.id,
        "username": request.user.username,
        "email": request.user.email or "",
        "role": profile.role,
        "is_owner": profile.is_owner,
        "shop": {
            "shop_id": shop.shop_id,
            "shop_name": shop.shop_name,
            "phone": shop.phone,  # ✅ added
            "expire_date": str(shop.expire_date) if shop.expire_date else None,  # ✅ added
            "logo": logo_url,
            "plan": shop.plan,
            "is_active": shop.is_active,

            # (optional but useful)
            "location": getattr(shop, "location", ""),
            "email_or_link": getattr(shop, "email_or_link", ""),
        }
    })
