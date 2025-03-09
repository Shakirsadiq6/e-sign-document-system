from django.urls import path
from . import views

app_name = 'documents'

urlpatterns = [
    path('', views.index, name='index'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('upload/', views.upload_document, name='upload'),
    path('view/<uuid:document_id>/', views.view_document, name='view'),
    path('sign/<uuid:document_id>/', views.sign_document, name='sign'),
    path('submit/<uuid:document_id>/', views.submit_document, name='submit'),
    path('document/<uuid:document_id>/<str:access_token>/', views.direct_document_access, name='direct_access'),
    path('thank-you/', views.thank_you, name='thank_you'),
]