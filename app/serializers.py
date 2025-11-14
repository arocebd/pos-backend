from rest_framework import serializers
from .models import Category, Customer, Product, Sale, SaleItem, Expense, Supplier, SupplierPayment, PurchaseItem, Purchase
from django.db.models import Sum
from decimal import Decimal

# -------------------------
# Category Serializer
# -------------------------
class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name"]


# -------------------------
# Product Serializer
# -------------------------
class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    image_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Product
        fields = [
            "id", "title", "product_code", "sku", "barcode",
            "category", "category_name",
             "purchased_price", "regular_price", "selling_price", "discount",
            "image", "image_url", "stock",
            "created_at", "updated_at",
        ]
        read_only_fields = ("created_at", "updated_at")

    def get_image_url(self, obj):
        request = self.context.get("request")
        if obj.image and hasattr(obj.image, "url"):
            url = obj.image.url
            return request.build_absolute_uri(url) if request else url
        return None


# -------------------------
# Sale Item Serializer
# -------------------------
# app/serializers.py - Update CustomerSerializer
class CustomerSerializer(serializers.ModelSerializer):
    sales_count = serializers.IntegerField(read_only=True)  # Add this field
    
    class Meta:
        model = Customer
        fields = ['id', 'name', 'phone', 'points', 'created_at', 'updated_at', 'sales_count']
        read_only_fields = ['created_at', 'updated_at', 'sales_count']



class SaleItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = SaleItem
        fields = ['id', 'product', 'quantity', 'price', 'total']


# -------------------------
#  ✨ COMPLETE AND CORRECTED SALE SERIALIZERS
# -------------------------

# ✨ THIS HELPER CLASS WAS MISSING.
# It's needed to accept customer data without causing a unique phone number error.
class SaleCustomerWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ['name', 'phone']
        # This removes the uniqueness validator that was causing the original error
        extra_kwargs = {
            'phone': {'validators': []},
        }

# ✨ THIS IS THE FULLY CORRECTED SaleSerializer
class SaleSerializer(serializers.ModelSerializer):
    # ✨ THESE FIELD DEFINITIONS WERE MISSING.
    # They tell the serializer HOW to handle the nested data.
    customer = CustomerSerializer(read_only=True)
    customer_data = SaleCustomerWriteSerializer(write_only=True, required=False, allow_null=True)
    items = SaleItemSerializer(many=True)
    earned_points = serializers.ReadOnlyField()

    class Meta:
        model = Sale
        fields = [
            'id',
            'customer',        # For reading existing sales
            'customer_data',   # For creating a new sale
            'date',
            'subtotal',
            'discount',
            'total',
            'redeemed_points',
            'earned_points',
            'items'
        ]

    def create(self, validated_data):
        # Your create logic from before is correct and remains here.
        customer_payload = validated_data.pop('customer_data', {})
        items_data = validated_data.pop('items', [])

        phone = customer_payload.get('phone', '').strip() if customer_payload else None
        name = customer_payload.get('name', '').strip() if customer_payload else None

        customer = None
        if phone:
            customer, created = Customer.objects.get_or_create(
                phone=phone,
                defaults={'name': name}
            )
            if not created and name and customer.name != name:
                customer.name = name
                customer.save()
        
        # This line is important: it links the found/created customer to the sale.
        sale = Sale.objects.create(customer=customer, **validated_data)

        for item_data in items_data:
            SaleItem.objects.create(sale=sale, **item_data)
            # You could add stock deduction logic here if needed
            # product = item_data['product']
            # product.stock -= item_data['quantity']
            # product.save()

        return sale


class ExpenseSerializer(serializers.ModelSerializer):
    added_by_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Expense
        fields = ["id", "date", "category", "description", "amount", "payment_method", "added_by", "added_by_name"]
        read_only_fields = ["id", "date", "added_by", "added_by_name"]

    def get_added_by_name(self, obj):
        return getattr(obj.added_by, "username", None)

    def create(self, validated_data):
        request = self.context.get("request")
        if request and request.user and request.user.is_authenticated:
            validated_data["added_by"] = request.user
        return super().create(validated_data)

# =========================================================
# SUPPLIER / PURCHASE / PAYMENT SERIALIZERS
# =========================================================
class PurchaseItemSerializer(serializers.ModelSerializer):
    product_title = serializers.CharField(source="product.title", read_only=True)

    class Meta:
        model = PurchaseItem
        fields = ["id", "product", "product_title", "quantity", "purchase_price", "total"]


class PurchaseSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    items = PurchaseItemSerializer(many=True)

    class Meta:
        model = Purchase
        fields = [
            "id", "invoice_no", "supplier", "supplier_name", "date",
            "subtotal", "discount", "total",
            "paid_amount", "due_amount", "payment_method", "remarks",
            "items", "created_at",
        ]

    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
        purchase = Purchase.objects.create(**validated_data)
        subtotal = 0
        for item_data in items_data:
            line = PurchaseItem.objects.create(purchase=purchase, **item_data)
            subtotal += line.total
        purchase.subtotal = subtotal
        purchase.total = subtotal - validated_data.get("discount", 0)
        purchase.save()
        return purchase


class SupplierSerializer(serializers.ModelSerializer):
    total_purchases = serializers.SerializerMethodField()
    total_paid = serializers.SerializerMethodField()
    total_due = serializers.SerializerMethodField()

    class Meta:
        model = Supplier
        fields = [
            "id", "name", "phone", "address", "opening_balance", "created_at",
            "total_purchases", "total_paid", "total_due",
        ]

    # ---- no Coalesce(), compute in Python ----
    def get_total_purchases(self, obj):
        total = Purchase.objects.filter(supplier=obj).aggregate(sum_val=Sum("total"))["sum_val"]
        return total if total is not None else Decimal("0.00")

    def get_total_paid(self, obj):
        total = SupplierPayment.objects.filter(supplier=obj).aggregate(sum_val=Sum("amount"))["sum_val"]
        return total if total is not None else Decimal("0.00")

    def get_total_due(self, obj):
        return self.get_total_purchases(obj) - self.get_total_paid(obj)

class SupplierPaymentSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)

    class Meta:
        model = SupplierPayment
        fields = ["id", "supplier", "supplier_name", "date", "memo_no", "amount", "payment_method", "remarks"]


# =========================================================
# SUPPLIER DETAIL SERIALIZER (keep this LAST)
# =========================================================
class SupplierDetailSerializer(serializers.ModelSerializer):
    purchases = PurchaseSerializer(many=True, read_only=True)
    payments = SupplierPaymentSerializer(many=True, read_only=True)

    class Meta:
        model = Supplier
        fields = [
            "id", "name", "phone", "address", "opening_balance", "created_at",
            "purchases", "payments",
        ]