"""기상청 단기예보 API 래퍼"""
import os
import urllib.parse
import requests
from datetime import datetime, timedelta


KMA_BASE_URL = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0"


def _get_base_time() -> tuple[str, str]:
    """API 호출용 기준 날짜/시각 반환 (발표 시각: 0200, 0500, 0800, 1100, 1400, 1700, 2000, 2300)"""
    now = datetime.now()
    base_hours = [2, 5, 8, 11, 14, 17, 20, 23]
    hour = now.hour
    base_hour = max(h for h in base_hours if h <= hour) if hour >= 2 else 23
    if base_hour == 23 and hour < 2:
        now -= timedelta(days=1)
    return now.strftime("%Y%m%d"), f"{base_hour:02d}00"


def get_short_forecast(nx: int, ny: int) -> list[dict]:
    """단기예보 조회 (3일치).

    data.go.kr 단기예보(getVilageFcst)는 aT 실시간 경매정보와 같은 data.go.kr
    일반 인증키를 공유하므로 AT_API_KEY를 그대로 사용한다(KMA_API_KEY는
    apihub.kma.go.kr AWS 실황 전용, 별도 키).
    """
    api_key = os.getenv("AT_API_KEY")
    if not api_key:
        raise ValueError("AT_API_KEY 환경변수가 없습니다")
    api_key = urllib.parse.unquote(api_key)

    base_date, base_time = _get_base_time()
    params = {
        "serviceKey": api_key,
        "pageNo": 1,
        "numOfRows": 1000,
        "dataType": "JSON",
        "base_date": base_date,
        "base_time": base_time,
        "nx": nx,
        "ny": ny,
    }

    resp = requests.get(f"{KMA_BASE_URL}/getVilageFcst", params=params, timeout=10)
    resp.raise_for_status()
    items = resp.json()["response"]["body"]["items"]["item"]

    # TMP(기온), REH(습도), POP(강수확률) 필터링
    result = {}
    for item in items:
        key = (item["fcstDate"], item["fcstTime"])
        if key not in result:
            result[key] = {"date": item["fcstDate"], "time": item["fcstTime"]}
        # TMP(기온) REH(습도) POP(강수확률) SKY(하늘상태/운량) PTY(강수형태) WSD(풍속)
        if item["category"] in ("TMP", "REH", "POP", "TMX", "TMN", "SKY", "PTY", "WSD"):
            result[key][item["category"]] = item["fcstValue"]

    return sorted(result.values(), key=lambda x: (x["date"], x["time"]))


def get_daily_summary(nx: int, ny: int, days: int = 3) -> list[dict]:
    """일별 최고·최저기온, 평균습도 요약"""
    items = get_short_forecast(nx, ny)
    daily: dict[str, dict] = {}

    for item in items:
        d = item["date"]
        if d not in daily:
            daily[d] = {"date": d, "temps": [], "humidity": []}
        if "TMP" in item:
            daily[d]["temps"].append(float(item["TMP"]))
        if "REH" in item:
            daily[d]["humidity"].append(float(item["REH"]))

    summary = []
    for d, data in sorted(daily.items())[:days]:
        temps = data["temps"]
        humidity = data["humidity"]
        summary.append({
            "date": d,
            "tmax": max(temps) if temps else None,
            "tmin": min(temps) if temps else None,
            "avg_humidity": round(sum(humidity) / len(humidity), 1) if humidity else None,
        })

    return summary


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    nx = int(os.getenv("GREENHOUSE_NX", 60))
    ny = int(os.getenv("GREENHOUSE_NY", 127))
    for day in get_daily_summary(nx, ny):
        print(day)
