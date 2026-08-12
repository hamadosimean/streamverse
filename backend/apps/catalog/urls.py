from django.urls import path

from apps.catalog.views import CategoryListView, TagListView

app_name = "catalog"

urlpatterns = [
    path("categories/", CategoryListView.as_view(), name="category-list"),
    path("tags/", TagListView.as_view(), name="tag-list"),
]
