from django.urls import path

from .api_views import (
    IDCardDetailView,
    IDCardGenerateView,
    IDCardHolderDetailView,
    IDCardHolderListView,
    IDCardListView,
    IDCardPhotoSearchView,
    IDCardStatusChangeView,
    IDCardTemplateDetailView,
    IDCardTemplateListView,
)

app_name = 'idcard'

urlpatterns = [
    path('templates/', IDCardTemplateListView.as_view(), name='template-list'),
    path('templates/<int:pk>/', IDCardTemplateDetailView.as_view(), name='template-detail'),

    path('holders/', IDCardHolderListView.as_view(), name='holder-list'),
    path('holders/<int:pk>/', IDCardHolderDetailView.as_view(), name='holder-detail'),

    path('photo-search/', IDCardPhotoSearchView.as_view(), name='photo-search'),

    path('cards/', IDCardListView.as_view(), name='card-list'),
    path('cards/generate/', IDCardGenerateView.as_view(), name='card-generate'),
    path('cards/<int:pk>/', IDCardDetailView.as_view(), name='card-detail'),
    path('cards/<int:pk>/status/', IDCardStatusChangeView.as_view(), name='card-status'),
]
