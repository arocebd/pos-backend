# app/serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import (
    Category, Customer, Product, ProductVariant, Sale, SaleItem, Expense,
    Supplier, SupplierPayment, PurchaseItem, Purchase, StockLedger,
    Shop, UserProfile, PaymentRequest, CustomerPayment, CashTransaction
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
            "base_unit", "has_variants",
            "purchased_price", "regular_price", "selling_price", "discount",
            "image", "image_url", "stock",
            "vat_applicable", "vat_percent",
            "created_at", "updated_at",
        ]
        read_only_fields = ("created_at", "updated_at", "shop")

    def get_image_url(self, obj):
        request = self.context.get("request")
        if obj.image and hasattr(obj.image, "url"):
            url = obj.image.url
            if request:
                return request.build_absolute_uri(url)
            return url
        return None


# ------------------------------------------------------------
# CASH TRANSACTION / LEDGER SERIALIZER
# ------------------------------------------------------------
class CashTransactionSerializer(serializers.ModelSerializer):
    source_display = serializers.CharField(source='get_source_display', read_only=True)
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    created_by_name = serializers.SerializerMethodField()
    reference_details = serializers.SerializerMethodField()
    
    class Meta:
        model = CashTransaction
        fields = [
            'id', 'date', 'transaction_type', 'transaction_type_display',
            'source', 'source_display', 'amount', 'running_balance',
            'payment_method', 'payment_method_display',
            'description', 'reference_no', 'bank_name',
            'is_manual', 'created_by', 'created_by_name',
            'sale', 'expense', 'purchase', 'supplier_payment', 'customer_payment',
            'reference_details', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'running_balance', 'created_by', 'created_at', 'updated_at']
    
    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.username
        return None
    
    def get_reference_details(self, obj):
        """Get details from the referenced object (sale, expense, purchase, etc.)"""
        if obj.sale:
            return {
                'type': 'sale',
                'id': obj.sale.id,
                'customer': obj.sale.customer.name if obj.sale.customer else 'Walk-in',
                'total': float(obj.sale.total)
            }
        elif obj.expense:
            return {
                'type': 'expense',
                'id': obj.expense.id,
                'category': obj.expense.category,
                'description': obj.expense.description
            }
        elif obj.purchase:
            return {
                'type': 'purchase',
                'id': obj.purchase.id,
                'supplier': obj.purchase.supplier.name,
                'invoice_no': obj.purchase.invoice_no
            }
        elif obj.supplier_payment:
            return {
                'type': 'supplier_payment',
                'id': obj.supplier_payment.id,
                'supplier': obj.supplier_payment.supplier.name
            }
        elif obj.customer_payment:
            return {
                'type': 'customer_payment',
                'id': obj.customer_payment.id,
                'customer': obj.customer_payment.customer.name
            }
        return None
    
    def create(self, validated_data):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['created_by'] = request.user
            profile = getattr(request.user, 'profile', None)
            if profile:
                validated_data['shop'] = profile.shop
        validated_data['is_manual'] = True
        return super().create(validated_data)


class CashTransactionCreateSerializer(serializers.ModelSerializer):
    """Simplified serializer for creating manual transactions"""
    
    class Meta:
        model = CashTransaction
        fields = [
            'date', 'transaction_type', 'source', 'amount',
            'payment_method', 'description', 'reference_no', 'bank_name'
        ]
    
    def create(self, validated_data):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['created_by'] = request.user
            profile = getattr(request.user, 'profile', None)
            if profile:
                validated_data['shop'] = profile.shop
        validated_data['is_manual'] = True
        return super().create(validated_data)


    def create(self, validated_data):
        shop = get_current_shop(self.context)
        if shop:
            validated_data['shop'] = shop
        return super().create(validated_data)


# ------------------------------------------------------------
# PRODUCT VARIANT SERIALIZER
# ------------------------------------------------------------
class ProductVariantSerializer(serializers.ModelSerializer):
    product_title = serializers.CharField(source="product.title", read_only=True)
    product_base_unit = serializers.CharField(source="product.base_unit", read_only=True)

    class Meta:
        model = ProductVariant
        fields = [
            "id", "product", "product_title", "product_base_unit",
            "variant_name", "sku", "barcode",
            "purchase_price", "selling_price", "stock",
            "created_at", "updated_at",
        ]
        read_only_fields = ("created_at", "updated_at")


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
        fields = ["id", "product", "product_variant", "quantity", "unit", "price", "total", 
                  "vat_applicable", "vat_percent", "vat_amount"]


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
    redeemed_points = serializers.IntegerField(min_value=0, default=0, write_only=True)

    class Meta:
        model = Sale
        fields = [
            "id",
            "customer",
            "customer_data",
            "date",
            "subtotal",
            "discount",
            "vat_applicable",
            "vat_amount",
            "total",
            "redeemed_points",
            "earned_points",
            "items",
            "payment_method",
            "paid_amount",
            "due_amount",
            "trx_id",
            "payment",
            # Don't include shop in fields since it's handled automatically
        ]
        read_only_fields = ["shop", "due_amount", "earned_points", "date"]

    def create(self, validated_data):
        request = self.context.get('request')
        shop = None
        if request and hasattr(request.user, 'profile'):
            profile = request.user.profile
            if hasattr(profile, 'shop'):
                shop = profile.shop
        
        if not shop:
            raise serializers.ValidationError({"shop": "Shop not found."})

        # Remove all data that will be handled separately
        payment_data = validated_data.pop("payment", {}) or {}
        customer_payload = validated_data.pop("customer_data", {}) or {}
        items_data = validated_data.pop("items", [])
        redeemed_points = validated_data.pop("redeemed_points", 0)
        
        # Remove fields that will be set explicitly
        validated_data.pop("customer", None)  # Remove if exists
        validated_data.pop("shop", None)  # Remove if exists
        validated_data.pop("payment_method", None)
        validated_data.pop("paid_amount", None)
        validated_data.pop("trx_id", None)
        validated_data.pop("due_amount", None)

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
        method = (payment_data.get("method") or "cash").strip()
        paid_amount = Decimal(str(payment_data.get("paid_amount") or 0))
        trx_id = payment_data.get("trx_id") or ""
        
        total = Decimal(str(validated_data.get("total") or 0))
        
        # Validate payment
        if paid_amount > total:
            raise serializers.ValidationError({"paid_amount": "Paid amount cannot be greater than total."})

        # IMPORTANT: Only require customer if payment method is 'due'
        if method == "due":
            if not customer:
                raise serializers.ValidationError({"customer_data": "Customer is required for due payments."})
        else:
            # For non-due payments, set paid_amount = total if not specified
            if paid_amount == 0:
                paid_amount = total

        # Create the sale with cleaned validated_data
        sale = Sale.objects.create(
            shop=shop,  # Explicitly set shop
            customer=customer,  # Explicitly set customer
            payment_method=method,
            paid_amount=paid_amount,
            trx_id=trx_id,
            redeemed_points=redeemed_points,
            **validated_data,  # Only remaining fields
        )
        
        # Calculate due_amount
        if method == "due":
            sale.due_amount = total - paid_amount
        else:
            sale.due_amount = Decimal("0.00")
        
        sale.save(update_fields=["due_amount"])

        # Update customer points if customer exists
        if customer and total > 0:
            # Calculate earned points (1 point per 100 Tk)
            earned_points = int(total / 100)
            
            # Update customer points: current + earned - redeemed
            customer.points = customer.points + earned_points - redeemed_points
            if customer.points < 0:
                customer.points = 0
            customer.save(update_fields=["points"])

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
    product_title = serializers.CharField(source="product.title", read_only=True, allow_null=True)
    variant_name = serializers.CharField(source="product_variant.variant_name", read_only=True, allow_null=True)
    
    class Meta:
        model = PurchaseItem
        fields = [
            "id", "product", "product_title", "product_variant", "variant_name",
            "pack_unit", "pack_size", "qty_packs", "price_per_pack",
            "batch_no", "expiry_date", "mrp",
            "total_base_qty", "cost_per_base_unit", "total"
        ]
        read_only_fields = ["total_base_qty", "cost_per_base_unit", "total"]


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
        read_only_fields = ['shop', 'subtotal', 'total', 'due_amount']

    def create(self, validated_data):
        from django.db import transaction
        
        shop = get_current_shop(self.context)
        if not shop:
            raise serializers.ValidationError({"shop": "Shop not found."})
            
        items_data = validated_data.pop("items", [])
        discount = Decimal(validated_data.get("discount", 0))
        
        with transaction.atomic():
            # Create purchase
            purchase = Purchase.objects.create(shop=shop, **validated_data)

            # Create purchase items and calculate totals
            subtotal = Decimal('0')
            for item_data in items_data:
                # Create purchase item (save method handles stock update and calculations)
                item = PurchaseItem.objects.create(purchase=purchase, **item_data)
                subtotal += item.total
                
                # Create stock ledger entry for batch tracking
                product = item.product_variant or item.product
                if product and item.batch_no:
                    StockLedger.objects.create(
                        shop=shop,
                        product=item.product,
                        product_variant=item.product_variant,
                        transaction_type='purchase',
                        batch_no=item.batch_no,
                        expiry_date=item.expiry_date,
                        quantity=item.total_base_qty,
                        remaining_qty=item.total_base_qty,
                        purchase_item=item,
                    )

            # Update purchase totals
            purchase.subtotal = subtotal
            purchase.total = subtotal - discount
            purchase.save(update_fields=['subtotal', 'total', 'due_amount'])

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
    username = serializers.CharField(source='user.username', read_only=True)
    phone = serializers.CharField(source='user.username', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)
    can_manage_products = serializers.BooleanField(default=False)
    can_manage_sales = serializers.BooleanField(default=False)
    can_manage_purchases = serializers.BooleanField(default=False)
    can_view_reports = serializers.BooleanField(default=False)
    is_active = serializers.BooleanField(source='user.is_active', read_only=True)

    class Meta:
        model = UserProfile
        fields = [
            "id", "username", "phone", "email", "role", "is_owner", 
            "profile_picture", "can_manage_products", "can_manage_sales",
            "can_manage_purchases", "can_view_reports", "is_active"
        ]
        read_only_fields = ["is_owner", "username", "phone", "email", "is_active"]

    def create(self, validated_data):
        user_data = validated_data.pop("user", {})
        password = user_data.pop("password", None)
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

    def to_representation(self, instance):
        """Ensure all fields are properly serialized as values, not field objects"""
        try:
            data = super().to_representation(instance)
            # Ensure role is a string value
            if hasattr(instance, 'role') and instance.role:
                data['role'] = str(instance.role)
            # Ensure other fields are properly serialized
            if 'profile_picture' in data and data['profile_picture']:
                # Profile picture URL is already handled by the field
                pass
            return data
        except Exception as e:
            print(f"Error in to_representation: {str(e)}")
            raise
    
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
    
        return None


# ------------------------------------------------------------
# CASH TRANSACTION / LEDGER SERIALIZER
# ------------------------------------------------------------
class CashTransactionSerializer(serializers.ModelSerializer):
    source_display = serializers.CharField(source='get_source_display', read_only=True)
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    created_by_name = serializers.SerializerMethodField()
    reference_details = serializers.SerializerMethodField()
    
    class Meta:
        model = CashTransaction
        fields = [
            'id', 'date', 'transaction_type', 'transaction_type_display',
            'source', 'source_display', 'amount', 'running_balance',
            'payment_method', 'payment_method_display',
            'description', 'reference_no', 'bank_name',
            'is_manual', 'created_by', 'created_by_name',
            'sale', 'expense', 'purchase', 'supplier_payment', 'customer_payment',
            'reference_details', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'running_balance', 'created_by', 'created_at', 'updated_at']
    
    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.username
        return None
    
    def get_reference_details(self, obj):
        """Get details from the referenced object (sale, expense, purchase, etc.)"""
        if obj.sale:
            return {
                'type': 'sale',
                'id': obj.sale.id,
                'customer': obj.sale.customer.name if obj.sale.customer else 'Walk-in',
                'total': float(obj.sale.total)
            }
        elif obj.expense:
            return {
                'type': 'expense',
                'id': obj.expense.id,
                'category': obj.expense.category,
                'description': obj.expense.description
            }
        elif obj.purchase:
            return {
                'type': 'purchase',
                'id': obj.purchase.id,
                'supplier': obj.purchase.supplier.name,
                'invoice_no': obj.purchase.invoice_no
            }
        elif obj.supplier_payment:
            return {
                'type': 'supplier_payment',
                'id': obj.supplier_payment.id,
                'supplier': obj.supplier_payment.supplier.name
            }
        elif obj.customer_payment:
            return {
                'type': 'customer_payment',
                'id': obj.customer_payment.id,
                'customer': obj.customer_payment.customer.name
            }
        return None
    
    def create(self, validated_data):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['created_by'] = request.user
            profile = getattr(request.user, 'profile', None)
            if profile:
                validated_data['shop'] = profile.shop
        validated_data['is_manual'] = True
        return super().create(validated_data)


class CashTransactionCreateSerializer(serializers.ModelSerializer):
    """Simplified serializer for creating manual transactions"""
    
    class Meta:
        model = CashTransaction
        fields = [
            'date', 'transaction_type', 'source', 'amount',
            'payment_method', 'description', 'reference_no', 'bank_name'
        ]
    
    def create(self, validated_data):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['created_by'] = request.user
            profile = getattr(request.user, 'profile', None)
            if profile:
                validated_data['shop'] = profile.shop
        validated_data['is_manual'] = True
        return super().create(validated_data)
