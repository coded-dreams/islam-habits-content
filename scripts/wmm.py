"""World Magnetic Model evaluator - the same algorithm as the app's WorldMagneticModel.kt.

Used to check that a coefficient set reproduces NOAA's own published test values before it is
committed to calculation.json. Standard library only.
"""
import math
import re

WGS84_A_KM = 6378.137
WGS84_F = 1 / 298.257223563
WGS84_E2 = WGS84_F * (2 - WGS84_F)
REFERENCE_RADIUS_KM = 6371.2


def parse_cof(text):
    """NOAA WMM.COF -> (epoch, name, [[n, m, g, h, gDot, hDot], ...])."""
    lines = [l.split() for l in text.splitlines() if l.strip()]
    epoch, name = float(lines[0][0]), lines[0][1]
    rows = [[int(p[0]), int(p[1])] + [float(x) for x in p[2:6]] for p in lines[1:] if len(p) == 6]
    return epoch, name, rows


def parse_test_values(text):
    """NOAA test values -> [[year, heightKm, lat, lon, declination], ...].

    NOAA has shipped the file in more than one column layout (the zip's WMMyyyy_TestValues.txt and
    the website's WMMyyyy_TEST_VALUES.txt differ), so columns are found from the "# Field N: label"
    header rather than assumed.
    """
    columns = {}
    for line in text.splitlines():
        match = re.match(r"#\s*Field\s+(\d+)\s*:\s*(.+)", line, re.I)
        if match:
            columns[match.group(2).strip().lower()] = int(match.group(1)) - 1

    def find(*prefixes):
        for label, index in columns.items():
            if any(label.startswith(p) for p in prefixes):
                return index
        raise ValueError(f"no test-values column starting with {prefixes}")

    year = find("decimal year", "date")
    height = find("altitude", "height")
    lat = find("geodetic latitude")
    lon = find("geodetic longitude")
    decl = find("declination")
    out = []
    for line in text.splitlines():
        p = line.split()
        if not p or p[0].startswith("#") or len(p) <= max(year, height, lat, lon, decl):
            continue
        out.append([float(p[year]), float(p[height]), float(p[lat]), float(p[lon]), float(p[decl])])
    return out


def declination(epoch, rows, lat, lon, height_km, year):
    deg = max(r[0] for r in rows)
    g = [[0.0] * (deg + 1) for _ in range(deg + 1)]
    h = [[0.0] * (deg + 1) for _ in range(deg + 1)]
    dt = year - epoch
    for n, m, gg, hh, gd, hd in rows:
        g[n][m] = gg + dt * gd
        h[n][m] = hh + dt * hd
    lat = max(-89.999, min(89.999, lat))
    phi = math.radians(lat)
    lam = math.radians(lon)
    rc = WGS84_A_KM / math.sqrt(1 - WGS84_E2 * math.sin(phi) ** 2)
    p = (rc + height_km) * math.cos(phi)
    z = (rc * (1 - WGS84_E2) + height_km) * math.sin(phi)
    r = math.hypot(p, z)
    phic = math.asin(z / r)
    x, s = math.sin(phic), math.cos(phic)

    # Schmidt semi-normalised recurrences, stable to high degree (WMMHR is degree 133).
    P = [[0.0] * (deg + 1) for _ in range(deg + 1)]
    P[0][0] = 1.0
    for m in range(deg + 1):
        if m >= 1:
            P[m][m] = s if m == 1 else math.sqrt((2 * m - 1) / (2 * m)) * s * P[m - 1][m - 1]
        for n in range(m + 1, deg + 1):
            prev2 = P[n - 2][m] if n - 2 >= m else 0.0
            P[n][m] = ((2 * n - 1) * x * P[n - 1][m]
                       - math.sqrt((n - 1) ** 2 - m * m) * prev2) / math.sqrt(n * n - m * m)
    dP = [[0.0] * (deg + 1) for _ in range(deg + 1)]
    for n in range(1, deg + 1):
        for m in range(n + 1):
            prev = P[n - 1][m] if n - 1 >= m else 0.0
            dP[n][m] = (n * x * P[n][m] - math.sqrt(n * n - m * m) * prev) / s

    cos_m = [math.cos(m * lam) for m in range(deg + 1)]
    sin_m = [math.sin(m * lam) for m in range(deg + 1)]
    bt = bl = br = 0.0
    ratio = REFERENCE_RADIUS_KM / r
    for n in range(1, deg + 1):
        rp = ratio ** (n + 2)
        for m in range(n + 1):
            c, sn = cos_m[m], sin_m[m]
            bt -= rp * (g[n][m] * c + h[n][m] * sn) * dP[n][m]
            bl += rp * m * (g[n][m] * sn - h[n][m] * c) * P[n][m]
            br += (n + 1) * rp * (g[n][m] * c + h[n][m] * sn) * P[n][m]
    bl /= s
    north_c, east, down = -bt, bl, -br
    psi = phic - phi
    north = north_c * math.cos(psi) - down * math.sin(psi)
    return math.degrees(math.atan2(east, north))


def reproduces(wmm, tolerance=0.01):
    """True when the model reproduces every one of its own NOAA test values."""
    tests = wmm.get("testValues") or []
    if len(tests) < 6:
        return False
    for year, height, lat, lon, decl in tests:
        if abs(declination(wmm["epoch"], wmm["coefficients"], lat, lon, height, year) - decl) > tolerance:
            return False
    return True
