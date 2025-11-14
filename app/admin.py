from django.contrib import admin
from .models import Product, Category, Sale, Customer, Expense, Supplier, Purchase

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("title", "product_code", "sku", "barcode", "category", "purchased_price", "regular_price", "selling_price", "discount", "stock")
    search_fields = ("title", "product_code", "sku", "barcode")
    list_filter = ("category", "created_at")

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)

@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("date", "total")
    list_filter = ("date",)

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "points", "created_at")
    search_fields = ("name", "phone")
    list_filter = ("created_at",)

@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("date", "category", "amount", "payment_method", "added_by")
    list_filter = ("category", "payment_method", "date")
    search_fields = ("category", "description")

@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "phone", "address", "opening_balance", "created_at")
    search_fields = ("name", "phone")
    list_filter = ("created_at",)

@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ("id", "supplier", "invoice_no", "date", "total", "paid_amount", "due_amount", "payment_method", "created_at")
    search_fields = ("invoice_no", "supplier__name")
    list_filter = ("date", "supplier")
