# app/models.py
from django.db import models
from django.utils import timezone
from django.conf import settings
from decimal import Decimal
from datetime import date, timedelta
from django.contrib.auth import get_user_model
import random

User = get_user_model()


# ============================================================
# SHOP (TENANT) MODEL
# ============================================================
def generate_shop_id():
    return str(random.randint(100000, 999999))


class Shop(models.Model):
    PLAN_CHOICES = [
        ("trial", "Free Trial (7 Days)"),
        ("monthly", "Monthly 750 BDT"),
        ("yearly", "Yearly 7990 BDT"),
    ]

    shop_id = models.CharField(max_length=6, unique=True, default=generate_shop_id)
    shop_name = models.CharField(max_length=120)
    location = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=20)
    email_or_link = models.CharField(max_length=200, blank=True, null=True)
    owner_name = models.CharField(max_length=100)

    logo = models.ImageField(upload_to="shop_logos/", blank=True, null=True)

    plan = models.CharField(max_length=10, choices=PLAN_CHOICES)
    is_active = models.BooleanField(default=False)
    expire_date = models.DateField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    # activate subscription periods
    def activate_trial(self):
        self.plan = "trial"
        self.is_active = True
        self.expire_date = date.today() + timedelta(days=7)
        self.save()

    def activate_monthly(self):
        self.plan = "monthly"
        self.is_active = True
        self.expire_date = date.today() + timedelta(days=30)
        self.save()

    def activate_yearly(self):
        self.plan = "yearly"
        self.is_active = True
        self.expire_date = date.today() + timedelta(days=365)
        self.save()

    def __str__(self):
        return f"{self.shop_name} ({self.shop_id})"


# ============================================================
# USER PROFILE (USER → SHOP)
# ============================================================
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="users")
    role = models.CharField(max_length=20, choices=[("admin", "Admin"), ("cashier", "Cashier"), ("manager", "Manager")])
    is_owner = models.BooleanField(default=True)
    profile_picture = models.ImageField(upload_to="profile_pics/", blank=True, null=True)

    def __str__(self):
        return f"{self.user.username} → {self.shop.shop_name} ({self.role})"
# ============================================================
# MANUAL PAYMENT REQUEST
# ============================================================
class PaymentRequest(models.Model):
    PAYMENT_METHODS = [
        ("bkash", "bKash"),
        ("nagad", "Nagad"),
    ]

    shop = models.OneToOneField(Shop, on_delete=models.CASCADE, related_name="payment_request")
    method = models.CharField(max_length=10, choices=PAYMENT_METHODS)
    sender_last4 = models.CharField(max_length=4)
    amount = models.PositiveIntegerField()
    transaction_id = models.CharField(max_length=50, blank=True, null=True)
    screenshot = models.ImageField(upload_to="payments/", blank=True, null=True)

    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.shop.shop_name} Payment ({self.method})"


# ============================================================
# CATEGORY
# ============================================================
class Category(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=100)

    class Meta:
        verbose_name_plural = "Categories"
        unique_together = ('shop', 'name')

    def __str__(self):
        return f"{self.name} ({self.shop.shop_id if self.shop else 'No Shop'})"


# ============================================================
# PRODUCT
# ============================================================
class Product(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, null=True, blank=True)
    title = models.CharField(max_length=200)
    product_code = models.CharField(max_length=50)
    sku = models.CharField(max_length=50, blank=True, null=True)
    barcode = models.CharField(max_length=64, blank=True, null=True)

    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")

    purchased_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    regular_price = models.DecimalField(max_digits=10, decimal_places=2)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    image = models.ImageField(upload_to="products/", blank=True, null=True)
    stock = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('shop', 'product_code')

    def save(self, *args, **kwargs):
        if self.selling_price is None:
            self.selling_price = max(0, self.regular_price - (self.discount or 0))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} ({self.shop.shop_id if self.shop else 'No Shop'})"


# ============================================================
# CUSTOMER
# ============================================================
class Customer(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    points = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("shop", "phone")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.phone}) [{self.shop.shop_id if self.shop else 'No Shop'}]"


# ============================================================
# SALE + SALE ITEMS
# ============================================================
class Sale(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, null=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)

    date = models.DateTimeField(auto_now_add=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Add these missing fields:
    payment_method = models.CharField(
        max_length=20,
        choices=[
            ("cash", "Cash"),
            ("bkash", "bKash"),
            ("nagad", "Nagad"),
            ("card", "Card"),
            ("due", "Due"),
            ("rocket", "Rocket"),
            ("bank", "Bank Transfer"),
        ],
        default="cash"
    )
    paid_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )
    due_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )
    trx_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Transaction ID"
    )
    
    redeemed_points = models.PositiveIntegerField(default=0)
    earned_points = models.PositiveIntegerField(default=0)
    
    def save(self, *args, **kwargs):
        # calculate points
        self.earned_points = int(self.total // 100)

        # ✅ Payment logic - This should match your serializer logic
        if self.payment_method != "due":
            # For non-due payments, paid_amount should equal total
            self.paid_amount = Decimal(self.total or 0)
            self.due_amount = Decimal("0.00")
        else:
            # For due payments, use the provided paid_amount
            # (if any partial payment was made)
            self.paid_amount = Decimal(self.paid_amount or 0)
            self.due_amount = Decimal(self.total or 0) - Decimal(self.paid_amount or 0)

        # customer points update
        if self.customer:
            if self.redeemed_points > 0:
                self.customer.points = max(0, self.customer.points - self.redeemed_points)
            self.customer.points += self.earned_points
            self.customer.save()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"Sale #{self.id} [{self.shop.shop_id if self.shop else 'No Shop'}]"

class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)

    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.product.title} × {self.quantity}"


# ============================================================
# EXPENSE
# ============================================================
class Expense(models.Model):
    PAYMENT_METHODS = [
        ("cash", "Cash"),
        ("bank", "Bank"),
        ("mobile", "Mobile Wallet"),
        ("other", "Other"),
    ]

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, null=True, blank=True)

    date = models.DateField(auto_now_add=True)
    category = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=12, choices=PAYMENT_METHODS, default="cash")

    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="expenses",
    )

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.category} - {self.amount} [{self.shop.shop_id if self.shop else 'No Shop'}]"


# ============================================================
# SUPPLIER
# ============================================================
class Supplier(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)

    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("shop", "name")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} [{self.shop.shop_id if self.shop else 'No Shop'}]"


# ============================================================
# PURCHASE
# ============================================================
class Purchase(models.Model):
    PAYMENT_METHODS = [
        ("cash", "Cash"),
        ("bank", "Bank"),
        ("mobile", "Mobile Wallet"),
        ("due", "Due"),
    ]

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, null=True, blank=True)

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    invoice_no = models.CharField(max_length=50)

    date = models.DateField(default=timezone.now)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    due_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default="cash")
    remarks = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("shop", "invoice_no")
        ordering = ["-date", "-id"]

    def save(self, *args, **kwargs):
        self.due_amount = Decimal(self.total) - Decimal(self.paid_amount)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.invoice_no} | {self.supplier.name} [{self.shop.shop_id if self.shop else 'No Shop'}]"


# ============================================================
# PURCHASE ITEM
# ============================================================
class PurchaseItem(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)

    quantity = models.PositiveIntegerField(default=1)
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2)

    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def save(self, *args, **kwargs):
        self.total = Decimal(self.purchase_price) * Decimal(self.quantity)
        super().save(*args, **kwargs)

        # increase product stock
        self.product.stock += self.quantity
        self.product.save()

    def __str__(self):
        return f"{self.product.title} × {self.quantity}"


# ============================================================
# SUPPLIER PAYMENT
# ============================================================
class SupplierPayment(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, null=True, blank=True)

    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE)
    date = models.DateField(auto_now_add=True)

    memo_no = models.CharField(max_length=100, blank=True, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    payment_method = models.CharField(
        max_length=20,
        choices=[("cash", "Cash"), ("bank", "Bank"), ("mobile", "Mobile Wallet")],
        default="cash",
    )
    remarks = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.supplier.name} | {self.amount} [{self.shop.shop_id if self.shop else 'No Shop'}]"
    
class CustomerPayment(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, null=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="payments")

    date = models.DateField(auto_now_add=True)
    memo_no = models.CharField(max_length=100, blank=True, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    payment_method = models.CharField(
        max_length=20,
        choices=[("cash", "Cash"), ("bank", "Bank"), ("bkash", "Bkash"), ("nagad", "Nagad"), ("card", "Card")],
        default="cash",
    )
    remarks = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-date", "-id"]
    
    