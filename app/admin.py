# app/admin.py
from email.mime import message
from urllib import request
from django.contrib import admin
from rest_framework.utils import timezone
from .models import (
    Product, ProductVariant, Category, Sale, Customer, Expense, Supplier,
    Purchase, Shop, UserProfile, PaymentRequest, SaleItem,
    PurchaseItem, SupplierPayment, StockLedger, CustomerPayment
)


# -------------------------------
# Admin Helper – Auto-assign shop
# -------------------------------
class ShopOwnedAdmin(admin.ModelAdmin):
    """
    Automatically sets the shop to the logged-in admin user's shop,
    Except if superuser → can manage all shops.
    """

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            # assign this item to the admin's shop
            if hasattr(request.user, "profile"):
                obj.shop = request.user.profile.shop
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if hasattr(request.user, "profile"):
            return qs.filter(shop=request.user.profile.shop)
        return qs.none()


# -------------------------------
# INLINE ADMIN CLASSES
# -------------------------------
class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 1
    readonly_fields = ('total',)


class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    extra = 1
    readonly_fields = ('total',)


# -------------------------------
# SHOP ADMIN
# -------------------------------
@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ("shop_id", "shop_name", "owner_name", "phone", "plan", "is_active", "expire_date", "created_at")
    list_filter = ("plan", "is_active", "created_at")
    search_fields = ("shop_id", "shop_name", "owner_name", "phone")
    readonly_fields = ("shop_id", "created_at")
    fieldsets = (
        ("Shop Information", {
            'fields': ('shop_id', 'shop_name', 'owner_name', 'phone', 'location', 'email_or_link', 'logo')
        }),
        ("Subscription", {
            'fields': ('plan', 'is_active', 'expire_date')
        }),
        ("Metadata", {
            'fields': ('created_at',),
            'classes': ('collapse',)
        })
    )


# -------------------------------
# USER PROFILE ADMIN
# -------------------------------
@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "shop", "profile_picture")
    search_fields = ("user__username", "shop__shop_name")
    list_filter = ("shop",)
    readonly_fields = ('user', 'shop')


# -------------------------------
# PAYMENT REQUEST ADMIN
# -------------------------------
@admin.register(PaymentRequest)
class PaymentRequestAdmin(admin.ModelAdmin):
    list_display = ("shop", "method", "amount", "sender_last4", "is_verified", "created_at")
    list_filter = ("method", "is_verified", "created_at")
    search_fields = ("shop__shop_name", "sender_last4", "transaction_id")
    readonly_fields = ("created_at",)
    actions = ['verify_payments']

    def verify_payments(self, request, queryset):
        activated_shops = 0
        already_active = 0
    
        for payment in queryset:
            if not payment.is_verified:
                payment.is_verified = True
                payment.verified_by = request.user
                payment.verified_at = timezone.now()
                payment.save()
            
                # Activate shop
                shop = payment.shop
            
            # IMPORTANT: Check if shop already has an active subscription
                if not shop.is_active:
                    if shop.plan == "monthly":
                        shop.activate_monthly()
                        print(f"✅ Activated monthly subscription for {shop.shop_name}")
                        activated_shops += 1
                    elif shop.plan == "yearly":
                        shop.activate_yearly()
                        print(f"✅ Activated yearly subscription for {shop.shop_name}")
                        activated_shops += 1
                    elif shop.plan == "trial":
                        shop.activate_trial()
                        print(f"✅ Activated trial for {shop.shop_name}")
                        activated_shops += 1
                    else:
                        shop.is_active = True
                        shop.save()
                        print(f"✅ Activated shop {shop.shop_name}")
                        activated_shops += 1
                else:
                    print(f"⚠️ Shop {shop.shop_name} already active, skipping activation")
                    already_active += 1
                
        message = f"{queryset.count()} payments verified. "
        if activated_shops > 0:
            message += f"{activated_shops} shops activated. "
        if already_active > 0:
            message += f"{already_active} shops were already active."
    
        self.message_user(request, message)
    
    verify_payments.short_description = "Verify selected payments and activate shops"


# -------------------------------
# CATEGORY (Tenant-aware)
# -------------------------------
@admin.register(Category)
class CategoryAdmin(ShopOwnedAdmin):
    list_display = ("name", "shop")
    search_fields = ("name",)
    list_filter = ("shop",)


# -------------------------------
# PRODUCT (Tenant-aware)
# -------------------------------
@admin.register(Product)
class ProductAdmin(ShopOwnedAdmin):
    list_display = ("title", "product_code", "category", "base_unit", "has_variants", "regular_price", "selling_price", "stock", "shop")
    list_filter = ("category", "shop", "base_unit", "has_variants", "created_at")
    search_fields = ("title", "product_code", "sku", "barcode")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Basic Info", {
            'fields': ('title', 'product_code', 'sku', 'barcode', 'category', 'shop')
        }),
        ("Inventory Settings", {
            'fields': ('base_unit', 'has_variants')
        }),
        ("Pricing", {
            'fields': ('purchased_price', 'regular_price', 'discount', 'selling_price')
        }),
        ("Inventory", {
            'fields': ('stock', 'image')
        }),
        ("Metadata", {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )


# -------------------------------# PRODUCT VARIANT
# -------------------------------
@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ("product", "variant_name", "sku", "barcode", "purchase_price", "selling_price", "stock")
    list_filter = ("product__shop", "created_at")
    search_fields = ("variant_name", "sku", "barcode", "product__title")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ["product"]


# -------------------------------# SALE
# -------------------------------
@admin.register(Sale)
class SaleAdmin(ShopOwnedAdmin):
    list_display = ("id", "shop", "customer", "date", "total", "discount", "redeemed_points", "earned_points")
    list_filter = ("date", "shop")
    search_fields = ("customer__name", "customer__phone")
    readonly_fields = ("subtotal", "total", "earned_points", "date")
    inlines = [SaleItemInline]
    fieldsets = (
        ("Sale Info", {
            'fields': ('shop', 'customer', 'date')
        }),
        ("Pricing", {
            'fields': ('subtotal', 'discount', 'total')
        }),
        ("Loyalty Points", {
            'fields': ('redeemed_points', 'earned_points')
        })
    )


# -------------------------------
# SALE ITEM
# -------------------------------
@admin.register(SaleItem)
class SaleItemAdmin(ShopOwnedAdmin):
    list_display = ("sale", "product", "quantity", "price", "total")
    list_filter = ("sale__shop", "sale__date")
    search_fields = ("product__title", "sale__id")
    readonly_fields = ("total",)


# -------------------------------
# CUSTOMER
# -------------------------------
@admin.register(Customer)
class CustomerAdmin(ShopOwnedAdmin):
    list_display = ("name", "phone", "points", "shop", "created_at")
    list_filter = ("shop", "created_at")
    search_fields = ("name", "phone")
    readonly_fields = ("created_at", "updated_at", "points")


# -------------------------------
# EXPENSE
# -------------------------------
@admin.register(Expense)
class ExpenseAdmin(ShopOwnedAdmin):
    list_display = ("date", "category", "amount", "payment_method", "shop", "added_by")
    list_filter = ("category", "payment_method", "shop", "date")
    search_fields = ("category", "description")
    readonly_fields = ("date", "added_by")


# -------------------------------
# SUPPLIER
# -------------------------------
@admin.register(Supplier)
class SupplierAdmin(ShopOwnedAdmin):
    list_display = ("name", "phone", "shop", "created_at")
    list_filter = ("shop", "created_at")
    search_fields = ("name", "phone", "address")
    readonly_fields = ("created_at",)


# -------------------------------
# PURCHASE
# -------------------------------
@admin.register(Purchase)
class PurchaseAdmin(ShopOwnedAdmin):
    list_display = ("invoice_no", "supplier", "date", "total", "paid_amount", "due_amount", "shop")
    list_filter = ("date", "supplier", "shop", "payment_method")
    search_fields = ("invoice_no", "supplier__name", "remarks")
    readonly_fields = ("subtotal", "total", "due_amount", "created_at")
    inlines = [PurchaseItemInline]
    fieldsets = (
        ("Purchase Info", {
            'fields': ('shop', 'supplier', 'invoice_no', 'date')
        }),
        ("Pricing", {
            'fields': ('subtotal', 'discount', 'total')
        }),
        ("Payment", {
            'fields': ('paid_amount', 'due_amount', 'payment_method')
        }),
        ("Notes", {
            'fields': ('remarks',)
        }),
        ("Metadata", {
            'fields': ('created_at',),
            'classes': ('collapse',)
        })
    )


# -------------------------------
# PURCHASE ITEM
# -------------------------------
@admin.register(PurchaseItem)
class PurchaseItemAdmin(ShopOwnedAdmin):
    list_display = ("purchase", "product", "product_variant", "pack_unit", "qty_packs", "price_per_pack", "total_base_qty", "total")
    list_filter = ("purchase__shop", "purchase__date", "pack_unit")
    search_fields = ("product__title", "product_variant__variant_name", "purchase__invoice_no", "batch_no")
    readonly_fields = ("total", "total_base_qty", "cost_per_base_unit")


# -------------------------------
# SUPPLIER PAYMENT
# -------------------------------
@admin.register(SupplierPayment)
class SupplierPaymentAdmin(ShopOwnedAdmin):
    list_display = ("supplier", "date", "amount", "payment_method", "shop", "memo_no")
    list_filter = ("date", "supplier", "shop", "payment_method")
    search_fields = ("supplier__name", "memo_no", "remarks")
    readonly_fields = ("date",)


# -------------------------------
# CUSTOMER PAYMENT
# -------------------------------
@admin.register(CustomerPayment)
class CustomerPaymentAdmin(ShopOwnedAdmin):
    list_display = ("customer", "date", "amount", "payment_method", "shop", "memo_no")
    list_filter = ("date", "customer", "shop", "payment_method")
    search_fields = ("customer__name", "memo_no", "remarks")
    readonly_fields = ("date",)


# -------------------------------
# STOCK LEDGER
# -------------------------------
@admin.register(StockLedger)
class StockLedgerAdmin(ShopOwnedAdmin):
    list_display = ("transaction_date", "transaction_type", "product", "product_variant", "batch_no", "expiry_date", "quantity", "remaining_qty", "shop")
    list_filter = ("transaction_type", "shop", "expiry_date", "transaction_date")
    search_fields = ("batch_no", "product__title", "product_variant__variant_name")
    readonly_fields = ("transaction_date",)
    date_hierarchy = "transaction_date"
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("product", "product_variant", "shop")