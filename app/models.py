# app/models.py
from django.db import models
from django.utils import timezone
from django.conf import settings
from decimal import Decimal

class Category(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name

class Product(models.Model):
    title = models.CharField(max_length=200)
    product_code = models.CharField(max_length=50, unique=True)
    sku = models.CharField(max_length=50, unique=True, blank=True, null=True)
    barcode = models.CharField(max_length=64, unique=True, blank=True, null=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    purchased_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    regular_price = models.DecimalField(max_digits=10, decimal_places=2)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    image = models.ImageField(upload_to="products/", blank=True, null=True)
    stock = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if self.selling_price is None:
            self.selling_price = max(0, self.regular_price - (self.discount or 0))
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

class Customer(models.Model):
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, unique=True)
    points = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)  # Fixed: using default
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.phone})"

    class Meta:
        ordering = ['-created_at']

class Sale(models.Model):
    customer = models.ForeignKey(Customer, related_name="sales", on_delete=models.SET_NULL, null=True, blank=True)
    date = models.DateTimeField(auto_now_add=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    redeemed_points = models.PositiveIntegerField(default=0)
    earned_points = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"Sale #{self.id} - Total: {self.total}"

    def save(self, *args, **kwargs):
        self.earned_points = int(self.total // 100)
        
        if self.customer:
            if self.redeemed_points > 0:
                self.customer.points = max(0, self.customer.points - self.redeemed_points)
            self.customer.points += self.earned_points
            self.customer.save()
        
        super().save(*args, **kwargs)

class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey("Product", on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.product.title} x {self.quantity}"


class Expense(models.Model):
    PAYMENT_METHODS = [
        ("cash", "Cash"),
        ("bank", "Bank"),
        ("mobile", "Mobile Wallet"),
        ("other", "Other"),
    ]

    date = models.DateField(auto_now_add=True)
    category = models.CharField(max_length=100)  # e.g., Rent, Salary, Utilities…
    description = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=12, choices=PAYMENT_METHODS, default="cash")
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="expenses"
    )

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.date} • {self.category} • ৳{self.amount}"
    
class Supplier(models.Model):
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.phone or 'No Phone'})"


# -----------------------------
# 🧾  PURCHASE MODEL
# -----------------------------
class Purchase(models.Model):
    PAYMENT_METHODS = [
        ("cash", "Cash"),
        ("bank", "Bank"),
        ("mobile", "Mobile Wallet"),
        ("due", "Due"),
    ]

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchases")
    invoice_no = models.CharField(max_length=50, unique=True)
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
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.invoice_no} | {self.supplier.name}"

    def save(self, *args, **kwargs):
        # auto calculate due before saving
        self.due_amount = Decimal(self.total) - Decimal(self.paid_amount)
        super().save(*args, **kwargs)


# -----------------------------
# 📦  PURCHASE ITEM MODEL
# -----------------------------
class PurchaseItem(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("Product", on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.product.title} × {self.quantity}"

    def save(self, *args, **kwargs):
        # calculate total
        self.total = Decimal(self.quantity) * Decimal(self.purchase_price)
        super().save(*args, **kwargs)

        # increase product stock
        self.product.stock += self.quantity
        self.product.save(update_fields=["stock"])


# -----------------------------
# 💰  SUPPLIER PAYMENT MODEL
# -----------------------------
class SupplierPayment(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="payments")
    date = models.DateField(auto_now_add=True)
    memo_no = models.CharField(max_length=100, blank=True, null=True)   # supplier memo / receipt ref
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
        return f"{self.supplier.name} | Memo: {self.memo_no or '-'} | ৳{self.amount}"