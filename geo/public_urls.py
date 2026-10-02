from rest_framework.routers import DefaultRouter

from .views import (
    PublicCorridorViewSet,
    PublicJunctionViewSet,
    PublicRestrictedZoneViewSet,
)

router = DefaultRouter()
router.register("corridors", PublicCorridorViewSet, basename="public-corridor")
router.register("junctions", PublicJunctionViewSet, basename="public-junction")
router.register(
    "restricted-zones", PublicRestrictedZoneViewSet, basename="public-restricted-zone"
)

urlpatterns = router.urls
