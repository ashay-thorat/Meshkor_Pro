from django.urls import path

from . import views

urlpatterns = [
    path("meta", views.meta),
    path("drugs", views.drugs),
    path("drugs/<str:hcpcs>", views.drug_detail),
    path("hospitals", views.hospitals),
    path("hospitals/<str:key>", views.hospital_detail),
    path("rates", views.rates),
    path("rates.csv", views.rates_csv),
    path("quality", views.quality),
]
