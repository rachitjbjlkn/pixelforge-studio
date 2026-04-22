from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('process/', views.process_image, name='process_image'),
    path('download/<str:filename>/', views.download_image, name='download_image'),
]
