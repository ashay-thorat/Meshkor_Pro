from django.urls import path

from . import auth_views, views

urlpatterns = [
    path("auth/csrf", auth_views.csrf),
    path("auth/login", auth_views.login_view),
    path("auth/logout", auth_views.logout_view),
    path("auth/me", auth_views.me),
    path("signoff", auth_views.signoff),
    path("meta", views.meta),
    path("drugs", views.drugs),
    path("drugs/<str:hcpcs>", views.drug_detail),
    path("hospitals", views.hospitals),
    path("hospitals/<str:key>", views.hospital_detail),
    path("rates", views.rates),
    path("rates.csv", views.rates_csv),
    path("report.pdf", views.report_pdf),
    path("quality", views.quality),
]
