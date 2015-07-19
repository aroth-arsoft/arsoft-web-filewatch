from django.conf.urls import patterns, include, url
from django.conf import settings
from arsoft.web.utils import django_debug_urls

# Uncomment the next two lines to enable the admin:
from django.contrib import admin
admin.autodiscover()

urlpatterns = patterns('',
    # Examples:
    url(r'^$', 'arsoft.web.filewatch.views.home', name='home'),

    # Uncomment the next line to enable the admin:
    url(r'^admin/', include(admin.site.urls)),

    # Uncomment the next line to enable the admin:
    url(r'^debug/', include(django_debug_urls())),
)
