import math

EARTH_RADIUS_KM = 6371.0


def distance_km(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    """Distância em linha reta entre dois pontos do globo (fórmula de haversine)."""
    lat_a = math.radians(latitude_a)
    lat_b = math.radians(latitude_b)
    delta_lat = math.radians(latitude_b - latitude_a)
    delta_lon = math.radians(longitude_b - longitude_a)

    half_chord = math.sin(delta_lat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2

    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(half_chord))
