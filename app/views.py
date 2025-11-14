# app/views.py
from decimal import Decimal
import io
from datetime import date, timedelta
from datetime import datetime, date as _date, datetime as _datetime
from openpyxl import Workbook


from django.db import transaction
from django.db.models import Q, Sum, Count, F, DecimalField, ExpressionWrapper, Value as V
from django.db.models.functions import TruncDate, Coalesce
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import viewsets, filters, permissions, status
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

from .models import (
    Product, Category, Sale, Customer, SaleItem, Expense, Supplier,
    Purchase, PurchaseItem, SupplierPayment
)
from .serializers import (
    ProductSerializer, CategorySerializer, SaleSerializer,
    CustomerSerializer, ExpenseSerializer, SupplierSerializer,
    PurchaseSerializer, PurchaseItemSerializer, SupplierPaymentSerializer
)


# -----------------------------
# Category & Product
# -----------------------------
class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all().order_by("name")
    serializer_class = CategorySerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.select_related("category").order_by("-id")
    serializer_class = ProductSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [filters.SearchFilter]
    search_fields = ["title", "product_code", "sku", "barcode"]


# -----------------------------
# Sales
# -----------------------------
class SaleViewSet(viewsets.ModelViewSet):
    queryset = Sale.objects.all().order_by("-id")
    serializer_class = SaleSerializer
    permission_classes = [permissions.AllowAny]

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=False)
        if not serializer.is_valid():
            return Response(
                {"success": False, "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        items = request.data.get("items", [])
        product_ids = [i.get("product") for i in items if i.get("product")]
        products = {
            p.id: p
            for p in Product.objects.select_for_update().filter(id__in=product_ids)
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
    code = request.query_params.get("code", "").strip()
    if not code:
        return Response({"error": "No code provided"}, status=400)

    try:
        product = Product.objects.get(
            Q(product_code__iexact=code) | Q(barcode__iexact=code)
        )
        serializer = ProductSerializer(product, context={"request": request})
        return Response(serializer.data, status=200)
    except Product.DoesNotExist:
        return Response({"error": f"Product '{code}' not found"}, status=404)


def invoice_view(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    serializer = SaleSerializer(sale, context={"request": request})
    return JsonResponse(serializer.data)


# -----------------------------
# Customers
# -----------------------------
class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all().order_by("-id")
    serializer_class = CustomerSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "phone"]
    ordering_fields = ["name", "points", "id"]

    def get_queryset(self):
        return Customer.objects.all().annotate(sales_count=Count("sales"))


@api_view(["GET"])
def customer_lookup(request):
    phone = request.query_params.get("phone", "").strip()
    if not phone:
        return Response({"error": "No phone provided"}, status=400)

    try:
        customer = Customer.objects.get(phone=phone)
        serializer = CustomerSerializer(customer)
        return Response(serializer.data, status=200)
    except Customer.DoesNotExist:
        return Response({"message": "New customer"}, status=404)


# -----------------------------
# KPI / Analytics
# -----------------------------
class SalesMetricsView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        today = date.today()
        start_of_month = today.replace(day=1)

        today_total = (
            Sale.objects.filter(date__date=today).aggregate(total=Sum("total"))["total"]
            or 0
        )
        month_total = (
            Sale.objects.filter(date__date__gte=start_of_month).aggregate(
                total=Sum("total")
            )["total"]
            or 0
        )
        products_in_stock = (
            Product.objects.aggregate(total=Sum("stock"))["total"] or 0
        )

        top_product = (
            SaleItem.objects.filter(sale__date__date__gte=start_of_month)
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


class DailySalesView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        start = request.GET.get("from")
        end = request.GET.get("to")

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
            Sale.objects.filter(date__date__range=[start_d, end_d])
            .annotate(day=TruncDate("date"))
            .values("day")
            .annotate(total=Sum("total"))
            .order_by("day")
        )
        data = [{"date": str(x["day"]), "total": x["total"] or 0} for x in qs]
        return Response(data)


class CategorySummaryView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        start = request.GET.get("from")
        end = request.GET.get("to")

        qs = (
            SaleItem.objects.filter(sale__date__date__range=[start, end])
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
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        start = request.GET.get("from")
        end = request.GET.get("to")
        limit = int(request.GET.get("limit", 5))

        qs = (
            SaleItem.objects.filter(sale__date__date__range=[start, end])
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
class ExpenseViewSet(viewsets.ModelViewSet):
    queryset = Expense.objects.all().order_by("-date", "-id")
    serializer_class = ExpenseSerializer
    permission_classes = [permissions.AllowAny]
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


class ExpenseSummaryView(APIView):
    """
    GET /api/expenses/summary/?from=YYYY-MM-DD&to=YYYY-MM-DD
    Returns category-wise totals + grand total + daily totals.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        f = request.GET.get("from")
        t = request.GET.get("to")

        qs = Expense.objects.all()
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
class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all().order_by("name")
    serializer_class = SupplierSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "phone"]

    @action(detail=True, methods=["get"])
    def ledger(self, request, pk=None):
        """
        GET /api/suppliers/<pk>/ledger/
        """
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


class PurchaseViewSet(viewsets.ModelViewSet):
    queryset = Purchase.objects.all().order_by("-date", "-id")
    serializer_class = PurchaseSerializer
    permission_classes = [permissions.AllowAny]
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


class PurchaseItemViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PurchaseItem.objects.all().select_related("purchase", "product")
    serializer_class = PurchaseItemSerializer
    permission_classes = [permissions.AllowAny]


class SupplierPaymentViewSet(viewsets.ModelViewSet):
    queryset = SupplierPayment.objects.all().order_by("-date", "-id")
    serializer_class = SupplierPaymentSerializer
    permission_classes = [permissions.AllowAny]

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


class SupplierLedgerView(APIView):
    """
    Optional standalone endpoint: GET /api/suppliers/<supplier_id>/ledger/
    (Kept for backward compatibility if your URLs reference it.)
    """
    permission_classes = [permissions.AllowAny]

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
# Sales Report (Summary/Detail) + PDF/Excel
# -----------------------------
@api_view(["GET"])
def sales_report(request):
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

    sales_qs = Sale.objects.filter(date__date__range=[start_d, end_d])

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
        
class BusinessOverviewAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")

        sales_filter = {}
        expenses_filter = {}
        purchases_filter = {}

        if start_date and end_date:
            # dates come from frontend as YYYY-MM-DD
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

        # Inventory value = stock * purchased_price  (must declare output_field!)
        stock_value_expr = ExpressionWrapper(
            F("stock") * F("purchased_price"),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
        total_stock_value = (
            Product.objects.aggregate(
                total=Coalesce(Sum(stock_value_expr), Decimal("0.00"))
            )["total"]
            or Decimal("0.00")
        )

        # Fixed costs (simple keyword filter; adjust to your categories)
        fixed_cost = (
            Expense.objects.filter(**expenses_filter)
            .filter(
                category__icontains="rent"
            )
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

        # Capital investment (extend with opening capital logic if you have it)
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


class BusinessOverviewTimeseriesAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")

        sales_filter = {}
        expenses_filter = {}
        purchases_filter = {}

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


class BusinessOverviewExportPDF(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")

        summary = BusinessOverviewAPIView().get(request).data

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []

        story.append(Paragraph("Al Zabeer — Business Overview", styles["Title"]))
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


class BusinessOverviewExportExcel(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")
        summary = BusinessOverviewAPIView().get(request).data

        wb = Workbook()
        ws = wb.active
        ws.title = "Business Overview"
        ws.append(["Al Zabeer — Business Overview"])
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

# JWT Authentication Views
class LoginView(TokenObtainPairView):
    permission_classes = [permissions.AllowAny]