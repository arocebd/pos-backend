# pos/settings.py

import pymysql
pymysql.install_as_MySQLdb()

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'your-secret-key'
DEBUG = True
ALLOWED_HOSTS = []

INSTALLED_APPS = [
    "jazzmin",
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'rest_framework_simplejwt',
    'app',
    "django_filters",

]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'pos.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'pos.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'pos_db',
        'USER': 'pos_user',
        'PASSWORD': 'Strong#POS#Password',
        'HOST': '127.0.0.1',
        'PORT': '3310',
        'OPTIONS': {'charset': 'utf8mb4', 'init_command': "SET sql_mode='STRICT_TRANS_TABLES'"},
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Dhaka'
USE_I18N = True
USE_L10N = True  # enable localized formatting 
USE_TZ = False 

STATIC_URL = 'static/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CORS_ALLOW_ALL_ORIGINS = True

JAZZMIN_SETTINGS = {
    "site_title": "Al Zabeer POS Admin",
    "site_header": "Al Zabeer POS",
    "site_brand": "Al Zabeer POS",
    "welcome_sign": "Welcome to Al Zabeer POS Admin",
    "show_sidebar": True,
    "navigation_expanded": True,
    # Optional: path to your logo (place file in /static/img/)
    "copyright": "© Al Zabeer",
    "topmenu_links": [
        {"name": "Dashboard", "url": "admin:index", "permissions": ["auth.view_user"]},
        {"app": "apps.products"},
        {"app": "apps.sales"},
        {"name": "API Docs", "url": "/api/", "new_window": True},
    ],
    "icons": {
        "auth.user": "fas fa-user",
        "auth.Group": "fas fa-users",
        "products.product": "fas fa-barcode",
        "sales.sale": "fas fa-cash-register",
    },
    "order_with_respect_to": ["apps.sales", "apps.products"],
    "related_modal_active": True,   # edit related objects in a modal
    "show_ui_builder": False,       # set True to play with colors live
}

JAZZMIN_UI_TWEAKS = {
    "theme": "flatly",          # try: "darkly", "cyborg", etc.
    "navbar": "navbar-dark",
    "sidebar": "sidebar-dark-primary",
    "accent": "accent-teal",
    "dark_mode_theme": "darkly",
    "actions_sticky_top": True,
}

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    )
}

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
CORS_ALLOW_ALL_ORIGINS = True