from django.urls import path
from . import views

app_name = 'editor'

urlpatterns = [
    path('', views.home, name='home'),
    path('upload/', views.upload_and_edit, name='upload'),
    path('edit/<int:asset_id>/', views.editor_view, name='edit'),
    path('api/save_actions/<int:asset_id>/', views.save_actions, name='save_actions'),
    path('api/export/<int:asset_id>/', views.export_actions, name='export_actions'),
    path('generator/', views.generator_page, name='generator'),
    path('generator/create/', views.create_generator_job, name='generator_create'),
    path('generator/status/<int:job_id>/', views.generator_status, name='generator_status'),
    path('generator/regenerate/<int:asset_id>/', views.regenerate_preview, name='regenerate_preview'),
    path('generator/admin/batch/', views.batch_regenerate_page, name='batch_regenerate'),
    path('generator/admin/batch_enqueue/', views.batch_enqueue_previews, name='batch_enqueue_previews'),
]
