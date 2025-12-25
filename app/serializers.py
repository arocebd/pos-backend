# app/serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import (
    Category, Customer, Product, Sale, SaleItem, Expense,
    Supplier, SupplierPayment, PurchaseItem, Purchase,
    Shop, UserProfile, PaymentRequest, CustomerPayment
)
from django.db.models import Sum
from decimal import Decimal

User = get_user_model()


# ------------------------------------------------------------
# HELPER FUNCTION
# ------------------------------------------------------------
def get_current_shop(context):
    """Get the shop from the request user's profile"""
    request = context.get('request')
    if request and request.user.is_authenticated:
        profile = getattr(request.user, 'profile', None)
        if profile:
            return profile.shop
    return None


# ------------------------------------------------------------
# CATEGORY SERIALIZER
# ------------------------------------------------------------
class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name"]
        read_only_fields = ['shop']

    def create(self, validated_data):
        shop = get_current_shop(self.context)
        if shop:
            validated_data['shop'] = shop
        return super().create(validated_data)


# ------------------------------------------------------------
# PRODUCT SERIALIZER
# ------------------------------------------------------------
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
        read_only_fields = ("created_at", "updated_at", "shop")

    def get_image_url(self, obj):
        request = self.context.get("request")
        if obj.image and hasattr(obj.image, "url"):
            url = obj.image.url
            return request.build_absolute_uri(url) if request else url
        return None

    def create(self, validated_data):
        shop = get_current_shop(self.context)
        if shop:
            validated_data['shop'] = shop
        return super().create(validated_data)


# ------------------------------------------------------------
# CUSTOMER SERIALIZER
# ------------------------------------------------------------
class CustomerSerializer(serializers.ModelSerializer):
    sales_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Customer
        fields = [
            "id", "name", "phone", "points",
            "created_at", "updated_at", "sales_count"
        ]
        read_only_fields = ["created_at", "updated_at", "sales_count", "shop"]

    def create(self, validated_data):
        shop = get_current_shop(self.context)
        if shop:
            validated_data['shop'] = shop
        return super().create(validated_data)


# ------------------------------------------------------------
# SALE ITEM SERIALIZER
# ------------------------------------------------------------
class SaleItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = SaleItem
        fields = ["id", "product", "quantity", "price", "total"]


# ------------------------------------------------------------
# CUSTOMER WRITE SERIALIZER FOR SALE CREATION
# ------------------------------------------------------------
class SaleCustomerWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ["name", "phone"]
        extra_kwargs = {
            "phone": {"validators": []},
        }


# ------------------------------------------------------------
# SALE SERIALIZER
# ------------------------------------------------------------
class SaleSerializer(serializers.ModelSerializer):
    customer = CustomerSerializer(read_only=True)
    customer_data = SaleCustomerWriteSerializer(write_only=True, required=False, allow_null=True)
    items = SaleItemSerializer(many=True)
    earned_points = serializers.ReadOnlyField()
    payment = serializers.JSONField(write_only=True, required=False)

    class Meta:
        model = Sale
        fields = [
            "id",
            "customer",
            "customer_data",
            "date",
            "subtotal",
            "discount",
            "total",
            "redeemed_points",
            "earned_points",
            "items",
            "payment_method",
            "paid_amount",
            "due_amount",
            "trx_id",
            "payment",
        ]
        read_only_fields = ["shop", "due_amount", "earned_points", "date"]

    def create(self, validated_data):
        shop = get_current_shop(self.context)
        if shop:
            validated_data["shop"] = shop

        payment_data = validated_data.pop("payment", {}) or {}
        customer_payload = validated_data.pop("customer_data", {}) or {}
        items_data = validated_data.pop("items", [])

        # ---- customer create/get ----
        phone = customer_payload.get("phone")
        name = customer_payload.get("name")

        customer = None
        if phone:
            customer, created = Customer.objects.get_or_create(
                shop=shop,
                phone=phone,
                defaults={"name": name or phone},
            )
            if not created and name and customer.name != name:
                customer.name = name
                customer.save()

        # ---- payment parse ----
        method = (payment_data.get("method") or validated_data.get("payment_method") or "cash").strip()
        paid_amount = Decimal(str(payment_data.get("paid_amount") or validated_data.get("paid_amount") or 0))
        trx_id = payment_data.get("trx_id") or validated_data.get("trx_id")
        
        total = Decimal(str(validated_data.get("total") or 0))
        
        # Validate payment
        if paid_amount > total:
            raise serializers.ValidationError({"paid_amount": "Paid amount cannot be greater than total."})

        # IMPORTANT: if due exists, customer must be selected
        # due_amount = total - paid_amount
        # if due_amount > 0 and not customer:
            raise serializers.ValidationError({"customer_data": "Customer is required when due amount > 0."})

        # Create the sale with all payment fields
        sale = Sale.objects.create(
            customer=customer,
            payment_method=method,
            paid_amount=paid_amount,
            trx_id=trx_id,
            **validated_data,
        )
        
        # The save() method in the model will calculate due_amount and earned_points

        # Create sale items
        for item in items_data:
            SaleItem.objects.create(sale=sale, **item)

        return sale

# ------------------------------------------------------------
# Customer Payment Serializer
# ------------------------------------------------------------
class CustomerPaymentSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)

    class Meta:
        model = CustomerPayment
        fields = ["id", "customer", "customer_name", "date", "memo_no", "amount", "payment_method", "remarks"]
        read_only_fields = ["shop", "date"]

    def create(self, validated_data):
        shop = get_current_shop(self.context)
        if shop:
            validated_data["shop"] = shop
        return super().create(validated_data)


# ------------------------------------------------------------
# EXPENSE SERIALIZER
# ------------------------------------------------------------
class ExpenseSerializer(serializers.ModelSerializer):
    added_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Expense
        fields = [
            "id", "date", "category", "description",
            "amount", "payment_method", "added_by", "added_by_name"
        ]
        read_only_fields = ["id", "date", "added_by", "added_by_name", "shop"]

    def get_added_by_name(self, obj):
        return getattr(obj.added_by, "username", None)

    def create(self, validated_data):
        request = self.context.get("request")
        shop = get_current_shop(self.context)
        
        if shop:
            validated_data['shop'] = shop
        if request.user.is_authenticated:
            validated_data["added_by"] = request.user
        return super().create(validated_data)


# ------------------------------------------------------------
# PURCHASE / SUPPLIER SERIALIZERS
# ------------------------------------------------------------
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
        read_only_fields = ['shop']

    def create(self, validated_data):
        shop = get_current_shop(self.context)
        if shop:
            validated_data['shop'] = shop
            
        items_data = validated_data.pop("items", [])
        purchase = Purchase.objects.create(**validated_data)

        subtotal = 0
        for item in items_data:
            line = PurchaseItem.objects.create(purchase=purchase, **item)
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
        read_only_fields = ['shop']

    def get_total_purchases(self, obj):
        total = Purchase.objects.filter(supplier=obj).aggregate(sum_val=Sum("total"))["sum_val"]
        return total or Decimal("0.00")

    def get_total_paid(self, obj):
        total = SupplierPayment.objects.filter(supplier=obj).aggregate(sum_val=Sum("amount"))["sum_val"]
        return total or Decimal("0.00")

    def get_total_due(self, obj):
        return self.get_total_purchases(obj) - self.get_total_paid(obj)

    def create(self, validated_data):
        shop = get_current_shop(self.context)
        if shop:
            validated_data['shop'] = shop
        return super().create(validated_data)


class SupplierPaymentSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)

    class Meta:
        model = SupplierPayment
        fields = ["id", "supplier", "supplier_name", "date", "memo_no", "amount", "payment_method", "remarks"]
        read_only_fields = ['shop']

    def create(self, validated_data):
        shop = get_current_shop(self.context)
        if shop:
            validated_data['shop'] = shop
        return super().create(validated_data)


# ------------------------------------------------------------
# SUBSCRIPTION SYSTEM SERIALIZERS
# ------------------------------------------------------------
class ShopRegistrationSerializer(serializers.Serializer):
    shop_name = serializers.CharField(max_length=120)
    location = serializers.CharField(max_length=255, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=20)
    email_or_link = serializers.CharField(max_length=200, required=False, allow_blank=True)
    owner_name = serializers.CharField(max_length=100)

    # Shop Logo (optional)
    logo = serializers.ImageField(required=False, allow_null=True)

    # User credentials
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True)

    # Subscription plan
    subscription_plan = serializers.ChoiceField(choices=["trial", "monthly", "yearly"])

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value


class PaymentRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentRequest
        fields = ["method", "sender_last4", "amount", "transaction_id", "screenshot"]


class SubscriptionStatusSerializer(serializers.Serializer):
    shop_id = serializers.CharField()
    shop_name = serializers.CharField()
    logo = serializers.CharField(allow_null=True)
    plan = serializers.CharField()
    is_active = serializers.BooleanField()
    expire_date = serializers.DateField(allow_null=True)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email"]


class UserProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer()

    class Meta:
        model = UserProfile
        fields = ["id", "user", "role", "profile_picture"]

    def create(self, validated_data):
        user_data = validated_data.pop("user")
        password = user_data.pop("password", None)  # Optional support
        user = User.objects.create_user(**user_data, password=password or "defaultpass123")
        profile = UserProfile.objects.create(user=user, **validated_data)
        return profile

    def update(self, instance, validated_data):
        user_data = validated_data.pop("user", None)
        if user_data:
            user = instance.user
            user.username = user_data.get("username", user.username)
            user.email = user_data.get("email", user.email)
            user.save()

        return super().update(instance, validated_data)
    
class ShopSerializer(serializers.ModelSerializer):
    logo_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Shop
        fields = ["shop_id", "shop_name", "location", "phone", "email_or_link", "logo", "logo_url", "plan", "is_active", "expire_date", "created_at"]
        read_only_fields = ["shop_id", "plan", "is_active", "created_at"]
    
    def get_logo_url(self, obj):
        request = self.context.get('request')
        if obj.logo and hasattr(obj.logo, 'url'):
            url = obj.logo.url
            return request.build_absolute_uri(url) if request else url
        return None