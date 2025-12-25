# app/middleware.py
from datetime import date
from django.http import JsonResponse
from django.urls import resolve
from django.utils.deprecation import MiddlewareMixin
from rest_framework_simplejwt.tokens import UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from jwt import decode as jwt_decode
from django.conf import settings

class SubscriptionMiddleware(MiddlewareMixin):
    """
    Middleware to block access to all POS features unless:
    - Shop subscription is ACTIVE
    - Subscription is not EXPIRED
    - OR Payment is verified but shop not yet activated
    """

    PUBLIC_PATHS = [
        "/api/auth/register-shop/",
        "/api/auth/login/",
        "/api/auth/refresh/", 
        "/api/payment-request/", 
        "/subscription-status/", 
        "/check-shop-status/",  
        "/api/payment-verification-status/", 
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        print(f"\n🔍 SubscriptionMiddleware checking path: {path}")

        if path.startswith("/admin/"):
            return self.get_response(request)

        if path.startswith("/static/") or path.startswith("/media/"):
            return self.get_response(request)

        for public_path in self.PUBLIC_PATHS:
            if path.startswith(public_path):
                print(f"✓ Allowing public path: {path}")
                return self.get_response(request)

        if request.method == "OPTIONS":
            return self.get_response(request)

        user = self.get_user_from_request(request)
        
        if not user or not user.is_authenticated:
            user = request.user
        
        if not user or not user.is_authenticated:
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]
                try:
                    decoded_data = jwt_decode(token, settings.SECRET_KEY, algorithms=["HS256"])
                    user_id = decoded_data.get('user_id')
                    if user_id:
                        from django.contrib.auth import get_user_model
                        User = get_user_model()
                        try:
                            user = User.objects.get(id=user_id)
                            request.user = user  # Set user on request
                        except User.DoesNotExist:
                            pass
                except Exception:
                    pass

        if not user or not user.is_authenticated:
            if path == "/api/check-shop-status/":
                return self.get_response(request)
            return JsonResponse({"detail": "Authentication required."}, status=401)

        profile = getattr(user, "profile", None)
        if not profile:
            return JsonResponse(
                {"detail": "User profile not found. Please contact support."},
                status=400,
            )

        shop = profile.shop
        print(f"Shop: {shop.shop_name}, ID: {shop.shop_id}, Plan: {shop.plan}, Active: {shop.is_active}")
        print(f"Expire Date: {shop.expire_date}, Today: {date.today()}")

        if shop.plan == "trial" and shop.expire_date and shop.expire_date < date.today():
            shop.is_active = False
            shop.save()

        if not shop.is_active and hasattr(shop, 'payment_request'):
            pr = shop.payment_request
            print(f"Payment Request exists: Verified={pr.is_verified}")
            
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

        # Subscription inactive
        if not shop.is_active:
            print(f"✗ Shop {shop.shop_id} is NOT active after check")
            
            # Check if there's a pending payment request
            if hasattr(shop, 'payment_request'):
                pr = shop.payment_request
                if pr.is_verified:
                    return JsonResponse(
                        {
                            "detail": "Payment verified but activation pending. Please try logging in again.",
                            "shop_id": shop.shop_id,
                            "plan": shop.plan,
                            "payment_verified": True,
                            "error_code": "ACTIVATION_PENDING",
                        },
                        status=402,
                    )
                else:
                    return JsonResponse(
                        {
                            "detail": "Payment pending verification. Please wait for admin approval.",
                            "shop_id": shop.shop_id,
                            "plan": shop.plan,
                            "payment_submitted": True,
                            "error_code": "PAYMENT_PENDING",
                        },
                        status=402,
                    )
            
            return JsonResponse(
                {
                    "detail": "Your subscription is inactive. Please make payment to activate.",
                    "shop_id": shop.shop_id,
                    "plan": shop.plan,
                    "expire_date": str(shop.expire_date) if shop.expire_date else None,
                    "requires_payment": shop.plan in ["monthly", "yearly"],
                    "error_code": "SUBSCRIPTION_INACTIVE",
                },
                status=402,  # Payment Required
            )

        # Subscription expired (for non-trial plans)
        if shop.expire_date and shop.expire_date < date.today() and shop.plan != "trial":
            return JsonResponse(
                {
                    "detail": "Your subscription has expired. Please renew to continue.",
                    "shop_id": shop.shop_id,
                    "expired_on": str(shop.expire_date),
                    "plan": shop.plan,
                    "error_code": "SUBSCRIPTION_EXPIRED",
                },
                status=402,
            )

        print(f"✓ Shop {shop.shop_id} is ACTIVE, allowing access")
        
        # Add shop info to request for easy access
        request.shop = shop
        return self.get_response(request)

    def get_user_from_request(self, request):
        """Extract user from JWT token if present"""
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            try:
                from rest_framework_simplejwt.authentication import JWTAuthentication
                jwt_auth = JWTAuthentication()
                validated_token = jwt_auth.get_validated_token(token)
                return jwt_auth.get_user(validated_token)
            except Exception:
                pass
        return request.user