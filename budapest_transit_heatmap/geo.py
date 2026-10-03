"""Shared geodesic helpers."""
import numpy as np

from config import EARTH_RADIUS_M, WALK_DETOUR_FACTOR


def haversine_m(lat1, lon1, lat2, lon2):
    """Vectorized great-circle distance in meters (inputs in degrees, broadcastable)."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dlmb = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def walk_speed_m_per_min(walk_speed_kmh):
    return walk_speed_kmh * 1000.0 / 60.0


def walk_minutes(dist_m, walk_speed_kmh):
    """Walking time for a straight-line distance, including the street detour factor."""
    return dist_m * WALK_DETOUR_FACTOR / walk_speed_m_per_min(walk_speed_kmh)


def max_walk_radius_m(minutes, walk_speed_kmh):
    """Straight-line radius reachable within `minutes` of walking."""
    return minutes * walk_speed_m_per_min(walk_speed_kmh) / WALK_DETOUR_FACTOR


def local_xy_m(lat, lon, lat0):
    """Equirectangular projection to meters around lat0; good enough for neighbor search."""
    k = np.radians(1.0) * EARTH_RADIUS_M
    return np.column_stack((np.asarray(lon) * k * np.cos(np.radians(lat0)), np.asarray(lat) * k))
