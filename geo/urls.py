from rest_framework.routers import DefaultRouter

from .views import CorridorViewSet, JunctionViewSet, RestrictedZoneViewSet

router = DefaultRouter()
router.register("corridors", CorridorViewSet, basename="corridor")
router.register("junctions", JunctionViewSet, basename="junction")
router.register("restricted-zones", RestrictedZoneViewSet, basename="restricted-zone")

urlpatterns = router.urls
