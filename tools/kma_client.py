"""KMA weather clients: DFS 동네예보 (no key) + AWS 실시간 관측 (API key)."""
import math
import os
import requests
from datetime import datetime, timedelta
from xml.etree import ElementTree

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

# AWS 매분자료 조회 — apihub.kma.go.kr > 지상관측 > 방재기상관측(AWS)
# 실제 프록시 경로: /api/typ01/cgi-bin/url/nph-aws2_min
AWS_BASE = "https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-aws2_min"

DFS_URL = "http://www.kma.go.kr/wid/queryDFS.jsp"

# Default location: user's greenhouse (lat, lon)
DEFAULT_LAT = 35.84754869736184
DEFAULT_LON = 127.1355093641714

# Wind direction index → Korean label
_WD_KOR = ["북", "북동", "동", "남동", "남", "남서", "서", "북서"]

# Precipitation type code → label
_PTY_LABEL = {0: "없음", 1: "비", 2: "비/눈", 3: "눈", 4: "소나기"}

# Sky condition code → label
_SKY_LABEL = {1: "맑음", 3: "구름많음", 4: "흐림"}


def latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
    """Convert WGS84 lat/lon to KMA Lambert Conformal Conic grid (X, Y)."""
    RE = 6371.00877; GRID = 5.0
    SLAT1 = 30.0; SLAT2 = 60.0; OLON = 126.0; OLAT = 38.0
    XO = 43; YO = 136
    D = math.pi / 180.0

    re = RE / GRID
    sn = math.log(math.cos(SLAT1*D) / math.cos(SLAT2*D)) / \
         math.log(math.tan(math.pi*.25 + SLAT2*D*.5) / math.tan(math.pi*.25 + SLAT1*D*.5))
    sf = math.pow(math.tan(math.pi*.25 + SLAT1*D*.5), sn) * math.cos(SLAT1*D) / sn
    ro = re * sf / math.pow(math.tan(math.pi*.25 + OLAT*D*.5), sn)
    ra = re * sf / math.pow(math.tan(math.pi*.25 + lat*D*.5), sn)
    theta = (lon - OLON) * D * sn
    if theta > math.pi:  theta -= 2*math.pi
    if theta < -math.pi: theta += 2*math.pi
    return (int(ra * math.sin(theta) + XO + 0.5),
            int(ro - ra * math.cos(theta) + YO + 0.5))


def _parse_xml(xml_text: str) -> dict:
    """Parse DFS XML response, return seq=0 (current/nearest) data."""
    root = ElementTree.fromstring(xml_text)

    def _f(el, tag, default=0.0):
        node = el.find(tag)
        if node is None or node.text is None:
            return default
        try:
            v = float(node.text)
            return default if v <= -900 else v
        except ValueError:
            return default

    def _s(el, tag, default=""):
        node = el.find(tag)
        return node.text.strip() if node is not None and node.text else default

    header = root.find("header")
    tm_raw = _s(header, "tm")          # e.g. "202506291400"
    grid_x = int(_f(header, "x"))
    grid_y = int(_f(header, "y"))

    data = root.find("body/data[@seq='0']") or root.findall("body/data")[0]

    temp = _f(data, "temp")
    rh   = _f(data, "reh")
    wd_i = int(_f(data, "wd"))
    pty  = int(_f(data, "pty"))

    # Build obs_time string
    try:
        obs_time = datetime.strptime(tm_raw, "%Y%m%d%H%M").strftime("%Y-%m-%d %H:%M")
    except Exception:
        obs_time = tm_raw

    return {
        "grid_x":       grid_x,
        "grid_y":       grid_y,
        "obs_time":     obs_time,
        "outdoor_temp": temp,
        "outdoor_rh":   rh,
        "outdoor_vpd":  _calc_vpd(temp, rh),
        "wind_speed":   round(_f(data, "ws"), 1),
        "wind_dir_idx": wd_i,
        "wind_dir_kor": _WD_KOR[wd_i] if 0 <= wd_i <= 7 else _s(data, "wdKor"),
        "precipitation": _f(data, "r06") or _f(data, "r12"),
        "pty":          pty,
        "pty_label":    _PTY_LABEL.get(pty, ""),
        "sky_label":    _SKY_LABEL.get(int(_f(data, "sky")), _s(data, "wfKor")),
        "wf_kor":       _s(data, "wfKor"),
        "fetched_at":   datetime.now().isoformat(timespec="seconds"),
        "source":       "KMA DFS",
    }


def _calc_vpd(temp_c: float, rh: float) -> float:
    es = 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))
    return round(es * (1 - rh / 100), 3)


def fetch_outdoor(lat: float = DEFAULT_LAT, lon: float = DEFAULT_LON) -> dict:
    """Fetch current weather from KMA DFS. No API key needed."""
    x, y = latlon_to_grid(lat, lon)
    resp = requests.get(DFS_URL, params={"gridx": x, "gridy": y}, timeout=10)
    resp.raise_for_status()
    data = _parse_xml(resp.text)
    data["lat"] = lat
    data["lon"] = lon
    return data


def ventilation_hint(outdoor: dict, indoor_temp: float) -> str:
    """Brief ventilation recommendation based on outdoor conditions."""
    ot  = outdoor["outdoor_temp"]
    ws  = round(outdoor["wind_speed"], 1)
    pty = outdoor["pty"]
    hints = []

    if pty > 0:
        hints.append(f"{outdoor['pty_label']} 중 → 천창 개방 주의")
    if ws > 5:
        hints.append(f"강풍 {ws}m/s → 천창 개방 제한")
    elif ws > 2:
        hints.append(f"바람 {ws}m/s({outdoor['wind_dir_kor']}) → 자연환기 효율 양호")
    else:
        hints.append(f"무풍 {ws}m/s → 자연환기 효율 낮음")

    diff = indoor_temp - ot
    if diff > 5:
        hints.append(f"외기 {ot}℃ (실내보다 {diff:.1f}℃ 낮음) → 환기 냉각 효과 큼")
    elif diff > 0:
        hints.append(f"외기 {ot}℃ ({diff:.1f}℃ 낮음) → 환기 냉각 제한적")
    else:
        hints.append(f"외기 {ot}℃ (실내보다 {abs(diff):.1f}℃ 높음) → 차광·포그 필수")

    return " / ".join(hints)


# ---------------------------------------------------------------------------
# KMA AWS 실시간 관측 (API key required)
# ---------------------------------------------------------------------------

def fetch_aws(
    stn: int | None = None,
    api_key: str | None = None,
) -> dict:
    """Fetch real-time AWS 1-minute observation from KMA API Hub.

    Endpoint: /cgi-bin/url/nph-aws2_min (AWS 매분자료 조회)
    Parameters: tm1/tm2 (YYYYMMDDHHMM), stn (지점번호), authKey
    """
    key = api_key or os.getenv("KMA_API_KEY", "")
    if not key:
        raise RuntimeError("KMA_API_KEY가 .env에 설정되지 않았습니다.")

    stn_no = stn or int(os.getenv("KMA_AWS_STN", "285"))
    now = datetime.now()
    # 최근 10분 구간 — 결측 분이 있어도 직전 유효값 사용
    tm2 = now.replace(second=0, microsecond=0)
    tm1 = tm2 - timedelta(minutes=10)

    resp = requests.get(
        AWS_BASE,
        params={
            "tm1":     tm1.strftime("%Y%m%d%H%M"),
            "tm2":     tm2.strftime("%Y%m%d%H%M"),
            "stn":     stn_no,
            "authKey": key,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return _parse_aws(resp.text, stn_no, tm2.strftime("%Y%m%d%H%M"))


def _parse_aws(text: str, stn: int, tm_str: str) -> dict:
    """Parse nph-aws2_min response.

    Column order (0-indexed):
      0:YYMMDDHHMI  1:STN  2:WD1  3:WS1  4:WDS  5:WSS
      6:WD10  7:WS10  8:TA  9:RE  10:RN-15m  11:RN-60m
      12:RN-12H  13:RN-DAY  14:HM  15:PA  16:PS  17:TD
    """
    lines = [l for l in text.splitlines()
             if l and not l.startswith("#") and not l.startswith("#7777")]
    if not lines:
        raise ValueError("AWS 응답 데이터 없음 (지점번호 또는 시각 확인)")

    def _v(parts: list, idx: int, default: float = 0.0) -> float:
        try:
            v = float(parts[idx])
            # KMA 결측값 코드: -99.9, -999, -9999, -900 등 (한국 기온 최저 ~-30℃ 기준 -50 이하를 결측 처리)
            return default if v <= -50 else v
        except (IndexError, ValueError):
            return default

    # 최신 줄부터 역순으로 유효한 온도값(TA)이 있는 줄 선택
    parts = lines[-1].split()
    for line in reversed(lines):
        candidate = line.split()
        try:
            v = float(candidate[8])
            if v > -50:
                parts = candidate
                break
        except (IndexError, ValueError):
            continue

    ta   = _v(parts, 8)
    hm   = _v(parts, 14)
    ws   = _v(parts, 7)    # 10m wind speed
    wd   = _v(parts, 6)    # 10m wind direction (degrees)

    # Convert wind direction degrees → 8-direction Korean label
    wd_i = int((wd + 22.5) / 45) % 8

    try:
        raw_tm = parts[0]   # YYYYMMDDHHMI
        obs_time = datetime.strptime(raw_tm, "%Y%m%d%H%M").strftime("%Y-%m-%d %H:%M")
    except Exception:
        obs_time = tm_str

    return {
        "stn":          stn,
        "obs_time":     obs_time,
        "temp":         ta,
        "rh":           hm,
        "vpd":          _calc_vpd(ta, hm),
        "wind_speed":   round(ws, 1),
        "wind_dir_deg": round(wd, 1),
        "wind_dir_kor": _WD_KOR[wd_i],
        "pressure_hpa": round(_v(parts, 15), 1),
        "rainfall_60m": _v(parts, 11),
        "rainfall_day": _v(parts, 13),
        "dewpoint":     _v(parts, 17),
        "source":       "KMA AWS",
        "fetched_at":   datetime.now().isoformat(timespec="seconds"),
    }


# Kept for backward compatibility (unused)
STATIONS = {}


def read_api_key() -> str:
    return os.getenv("KMA_API_KEY", "")


if __name__ == "__main__":
    print(f"위치: {DEFAULT_LAT}, {DEFAULT_LON}")
    gx, gy = latlon_to_grid(DEFAULT_LAT, DEFAULT_LON)
    print(f"격자: X={gx}, Y={gy}")
    data = fetch_outdoor()
    for k, v in data.items():
        print(f"  {k}: {v}")
    print(f"\n환기 힌트: {ventilation_hint(data, indoor_temp=28.0)}")
