from ..config import Settings


def get_platform(db, settings: Settings):
    """Pick the ad platform: real Google Ads, or the offline simulator (default)."""
    if settings.ads_backend == "google":
        from .google_ads import GoogleAdsPlatform
        return GoogleAdsPlatform(settings)
    from .simulated import SimulatedGoogleAds
    return SimulatedGoogleAds(db)
