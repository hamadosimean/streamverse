from rest_framework import serializers

from apps.catalog.models import Category, Tag


class CategorySerializer(serializers.ModelSerializer):
    """`slug` is the frontend's translation key; `name` is the fallback label."""

    video_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Category
        fields = ("id", "slug", "name", "description", "icon", "accent_color",
                  "display_order", "video_count")
        read_only_fields = fields


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ("id", "name", "slug", "usage_count")
        read_only_fields = fields
