from django.urls import path, include
from django.conf.urls import url
from django.conf.urls.static import static
from django.conf import settings

from . import views

# dataset actions
app_name='datasets'
urlpatterns = [

    path('create/', views.DatasetCreateView.as_view(), name='dataset-create'),
    path('<int:id>/delete', views.DatasetDeleteView.as_view(), name='dataset-delete'),

    # also handles update for name, description fields
    path('<int:id>/detail', views.DatasetDetailView.as_view(), name='dataset-detail'),

    # insert validated delimited (csv for short) file data to db
    path('<int:pk>/insert_csv/', views.ds_insert_csv, name="ds_insert_csv"),

    # insert validated lpf file data to db
    path('<int:pk>/insert_lpf/', views.ds_insert_lpf, name="ds_insert_lpf"),

    # initiate reconciliation
    path('<int:pk>/recon/', views.ds_recon, name="ds_recon"), # form submit

    # review, validate hits
    path('<int:pk>/review/<str:tid>/<str:passnum>', views.review, name="review"),

    # list places (for table)
    path('<str:label>/datatable/<str:f>', views.drf_table, name='drf_table'),

    # list places in a dataset
    #path('<str:label>/places/<str:format>', views.ds_list, name='ds_list'),
    path('<str:label>/places/', views.ds_list, name='ds_list'),

    # delete TaskResult & associated hits
    path('task-delete/<str:tid>/<str:scope>', views.task_delete, name="task-delete"),

] + static(settings.MEDIA_URL, document_root = settings.MEDIA_ROOT)
