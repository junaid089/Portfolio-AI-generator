"""Django settings for pr1 project.

The file is organized in clearly labelled sections so it is easier to spot
security-sensitive configuration. Values that differ between environments
use environment variables with sensible defaults for local development.
"""

from __future__ import annotations

import os
from pathlib import Path


# --- Paths & environment ----------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
ENVIRONMENT = os.environ.get('DJANGO_ENV', 'development')


# --- Core security settings -------------------------------------------------

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'dev-insecure-key')
DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'
ALLOWED_HOSTS = [
    host.strip() for host in os.environ.get('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')
    if host.strip()
]


# --- Application definition -------------------------------------------------


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'startup',
    'portfolio',
    'editor',
    'sentinel',
    'pr1',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'pr1.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'pr1' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'pr1.wsgi.application'


# --- Database ---------------------------------------------------------------

DATABASES = {
    'default': {
        'ENGINE': os.environ.get('DB_ENGINE', 'django.db.backends.sqlite3'),
        'NAME': os.environ.get('DB_NAME', BASE_DIR / 'db.sqlite3'),
        'USER': os.environ.get('DB_USER', ''),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST': os.environ.get('DB_HOST', ''),
        'PORT': os.environ.get('DB_PORT', ''),
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# --- Static & media ---------------------------------------------------------

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# --- Caching layer ----------------------------------------------------------

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'pr1-cache',
    }
}

HOME_CACHE_SECONDS = int(os.environ.get('HOME_CACHE_SECONDS', 300))

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Use custom user model defined in project package
AUTH_USER_MODEL = 'pr1.User'

# Celery / Broker
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = CELERY_BROKER_URL

# Hugging Face + LLM integration
HUGGINGFACE_API_TOKEN = os.environ.get('HUGGINGFACE_API_TOKEN', '')
HUGGINGFACE_DEFAULT_MODEL = os.environ.get('HUGGINGFACE_DEFAULT_MODEL', 'stabilityai/stable-diffusion-2')
LLM_API_KEY = os.environ.get('LLM_API_KEY', '')


# --- Logging ----------------------------------------------------------------

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
        'sentinel_db': {
            'level': 'ERROR',
            'class': 'sentinel.handlers.DatabaseErrorHandler',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'sentinel_db'],
            'level': 'ERROR',
            'propagate': True,
        },
        'django.request': {
            'handlers': ['console', 'sentinel_db'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}


# --- Environment-specific tweaks -------------------------------------------

if ENVIRONMENT == 'production':
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
