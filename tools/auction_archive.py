"""Auction ledger archive and origin-market cycle summaries."""
from __future__ import annotations

import csv
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean, median

ARCHIVE_CSV = Path(__file__).parent.parent / "auction_history.csv"

COLUMNS = [
    "거래일자",
    "경락일시",
    "도매시장",
    "법인",
    "품목",
    "품종",
    "출하지",
    "단량",
    "수량",
    "단량당 경락가(원)",
    "등급",
    "archived_at",
]

KEY_COLUMNS = [
    "거래일자",
    "경락일시",
    "도매시장",
    "법인",
    "품종",
    "출하지",
    "단량",
    "수량",
    "단량당 경락가(원)",
]


def _key(row: dict) -> tuple[str, ...]:
    return tuple(str(row.get(col, "") or "") for col in KEY_COLUMNS)


def _read_rows() -> list[dict]:
    if not ARCHIVE_CSV.exists():
        return []
    with ARCHIVE_CSV.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _price(row: dict) -> float | None:
    try:
        value = str(row.get("단량당 경락가(원)", "")).replace(",", "")
        price = float(value)
        return price if price > 0 else None
    except (TypeError, ValueError):
        return None


def archive_ledger_snapshot(ledger: dict) -> dict:
    """Append non-duplicate ledger rows to the local CSV archive."""
    rows = ledger.get("rows") or []
    if not rows:
        return {"file": str(ARCHIVE_CSV), "added": 0, "skipped": 0, "total_rows": len(_read_rows())}

    existing = _read_rows()
    seen = {_key(row) for row in existing}
    now = datetime.now().isoformat(timespec="seconds")
    new_rows = []
    skipped = 0

    for row in rows:
        if row.get("이상값"):
            skipped += 1
            continue
        item = {col: row.get(col, "") for col in COLUMNS}
        item["archived_at"] = now
        row_key = _key(item)
        if row_key in seen:
            skipped += 1
            continue
        seen.add(row_key)
        new_rows.append(item)

    if new_rows:
        write_header = not ARCHIVE_CSV.exists()
        with ARCHIVE_CSV.open("a", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            if write_header:
                writer.writeheader()
            writer.writerows(new_rows)

    return {
        "file": str(ARCHIVE_CSV),
        "added": len(new_rows),
        "skipped": skipped,
        "total_rows": len(existing) + len(new_rows),
    }


def archive_summary() -> dict:
    rows = _read_rows()
    dates = sorted({r.get("거래일자", "") for r in rows if r.get("거래일자")})
    origins = {r.get("출하지", "") for r in rows if r.get("출하지")}
    markets = {r.get("도매시장", "") for r in rows if r.get("도매시장")}
    prices = [p for r in rows if (p := _price(r)) is not None]
    return {
        "file": str(ARCHIVE_CSV),
        "rows": len(rows),
        "date_start": dates[0] if dates else None,
        "date_end": dates[-1] if dates else None,
        "origin_count": len(origins),
        "market_count": len(markets),
        "avg_price": int(mean(prices)) if prices else None,
    }


def _price_per_kg(row: dict) -> float | None:
    price = _price(row)
    if price is None:
        return None
    m = re.search(r"([\d.]+)\s*kg", str(row.get("단량", "")))
    if not m:
        return None
    kg = float(m.group(1))
    return price / kg if kg > 0 else None


def grade_avg_for_date(target: date) -> dict[str, int | None] | None:
    """우리 실시간 경매 아카이브에서 지정일 낙찰가를 상/중/하 3등분해 4kg 기준 평균가 반환.

    aT 실시간 API가 일일 호출 한도(429)로 막혔을 때 쓰는 대체 경로 — 이미 archive_ledger
    로 저장해둔 당일 낙찰 원자료가 있으면 그걸로 같은 방식(tools/at_client._compute_grades와
    동일한 tercile 분류)으로 계산한다. 해당 날짜 데이터가 아카이브에 아예 없으면 None을
    반환하고, 호출부는 그대로 "데이터 없음"으로 처리해야 한다(값을 지어내지 않는다).
    """
    target_str = target.isoformat()
    prices = sorted(
        p for r in _read_rows()
        if r.get("거래일자") == target_str and (p := _price_per_kg(r)) is not None
    )
    if not prices:
        return None
    n = len(prices)
    t1 = max(n // 3, 1)
    t2 = max(2 * n // 3, t1)
    bot = prices[:t1]
    mid = prices[t1:t2] if t2 > t1 else prices
    top = prices[t2:] if n > t2 else prices[-1:]
    return {
        "상": int(mean(top) * 4),
        "중": int(mean(mid) * 4),
        "하": int(mean(bot) * 4),
    }


def market_avg_in_range(start: date, end: date, min_count: int = 1) -> list[dict]:
    """지정 기간(포함) 동안 우리 실시간 경매 아카이브에 쌓인 시장별 평균 경락가.

    아카이브는 오늘 시점부터 쌓이기 시작했으므로(과거로 백필 불가), 이 기간에
    데이터가 없으면 빈 리스트를 반환한다 — 호출부는 이 경우 KAMIS 등 다른
    출처로 대체해야 한다.
    """
    rows = _read_rows()
    buckets: dict[str, list[float]] = {}
    for row in rows:
        d_raw = row.get("거래일자", "")
        try:
            d = date.fromisoformat(d_raw)
        except ValueError:
            continue
        if not (start <= d <= end):
            continue
        price = _price(row)
        if price is None:
            continue
        market = row.get("도매시장") or "시장 미상"
        buckets.setdefault(market, []).append(price)

    return sorted(
        (
            {"도매시장": m, "평균가": int(mean(p)), "건수": len(p)}
            for m, p in buckets.items() if len(p) >= min_count
        ),
        key=lambda x: x["평균가"],
        reverse=True,
    )


def origin_market_cycle(days: int = 180, min_count: int = 3) -> dict:
    """Summarize historical premium by origin, market, and month."""
    rows = _read_rows()
    cutoff = date.today() - timedelta(days=days)
    buckets: dict[tuple[str, str, str], list[float]] = {}
    market_buckets: dict[tuple[str, str], list[float]] = {}

    for row in rows:
        d_raw = row.get("거래일자", "")
        try:
            d = date.fromisoformat(d_raw)
        except ValueError:
            continue
        if d < cutoff:
            continue
        price = _price(row)
        if price is None:
            continue
        origin = row.get("출하지") or "출하지 미상"
        market = row.get("도매시장") or "시장 미상"
        month = d.strftime("%m월")
        buckets.setdefault((origin, market, month), []).append(price)
        market_buckets.setdefault((market, month), []).append(price)

    result = []
    for (origin, market, month), prices in buckets.items():
        if len(prices) < min_count:
            continue
        market_prices = market_buckets.get((market, month), prices)
        avg_price = mean(prices)
        market_avg = mean(market_prices)
        result.append({
            "출하지": origin,
            "도매시장": market,
            "월": month,
            "평균가": int(avg_price),
            "건수": len(prices),
            "시장월평균대비": int(avg_price - market_avg),
        })

    result.sort(key=lambda x: (x["시장월평균대비"], x["평균가"], x["건수"]), reverse=True)

    # 시장별 전체 평균(출하지 구분 없이, 기간 전체) — 물류비 반영 순수익 비교용.
    # origin_market_cycle의 rows는 프리미엄 상위 30건만 노출해 일부 시장이
    # 통째로 빠질 수 있으므로, 순수익 비교에는 이 전체 집계를 따로 둔다.
    market_totals: dict[str, list[float]] = {}
    for (market, _month), prices in market_buckets.items():
        market_totals.setdefault(market, []).extend(prices)
    market_summary = sorted(
        (
            {"도매시장": market, "평균가": int(mean(prices)), "건수": len(prices)}
            for market, prices in market_totals.items()
            if len(prices) >= min_count
        ),
        key=lambda x: x["평균가"],
        reverse=True,
    )

    return {
        "summary": archive_summary(),
        "days": days,
        "min_count": min_count,
        "rows": result[:30],
        "market_summary": market_summary,
    }


def monthly_seasonal_cycle(min_count: int = 20) -> dict:
    """월별 계절 가격 사이클 — 아카이브 전체 기간·전체 연도 기준 시장별·통합 kg당 중앙값.

    tools/price_advisor.py의 계절 평균과 프론트 차트("AI상담 가격정보")가 같은
    계산을 공유하도록 단일 출처로 둔다. 연도별 변동폭(combined_range_4kg)도 함께
    반환해 "다음 달 X% 상승" 같은 문구가 단일 확정값처럼 보이지 않게 한다 — 실제로는
    연도마다 같은 달 가격도 크게 다르다(예: 3월 중앙값이 연도별로 1만~1.9만원대까지
    벌어짐, 2026-07-10 확인).
    """
    rows = _read_rows()
    by_market_month: dict[tuple[str, int], list[float]] = {}
    by_month: dict[int, list[float]] = {}
    by_year_month: dict[tuple[int, int], list[float]] = {}

    for row in rows:
        try:
            d = date.fromisoformat(row.get("거래일자", ""))
        except ValueError:
            continue
        ppk = _price_per_kg(row)
        if ppk is None:
            continue
        market = row.get("도매시장") or "시장 미상"
        by_market_month.setdefault((market, d.month), []).append(ppk)
        by_month.setdefault(d.month, []).append(ppk)
        by_year_month.setdefault((d.year, d.month), []).append(ppk)

    markets = sorted({m for (m, _mo) in by_market_month})

    chart = []
    for mo in range(1, 13):
        entry: dict = {"월": f"{mo}월"}
        for market in markets:
            vals = by_market_month.get((market, mo), [])
            if len(vals) >= min_count:
                entry[market] = round(median(vals) * 4)  # 4kg 환산(단량 규격 차이 보정)
        chart.append(entry)

    combined_4kg: dict[int, int] = {}
    combined_range_4kg: dict[int, dict] = {}
    for mo in range(1, 13):
        vals = by_month.get(mo, [])
        if len(vals) < min_count:
            continue
        combined_4kg[mo] = round(median(vals) * 4)
        yearly = [
            round(median(v) * 4)
            for (y, m2), v in by_year_month.items()
            if m2 == mo and len(v) >= min_count
        ]
        if len(yearly) >= 2:
            combined_range_4kg[mo] = {"연도수": len(yearly), "최소": min(yearly), "최대": max(yearly)}

    years = sorted({y for (y, _m) in by_year_month})

    # 연도별 보기(시장 통합) — "3월 중앙값이 연도별로 크게 벌어진다"를 숫자 대신
    # 실제 곡선으로 보고 싶다는 요청(2026-07-10)에 대응. 시장×연도까지 나누면
    # 선이 너무 많아져(최대 6개 시장 × 6개 연도) 시장은 통합하고 연도만 나눈다.
    year_chart = []
    for mo in range(1, 13):
        entry: dict = {"월": f"{mo}월"}
        for y in years:
            vals = by_year_month.get((y, mo), [])
            if len(vals) >= min_count:
                entry[str(y)] = round(median(vals) * 4)
        year_chart.append(entry)

    # 등급별 보기(시장·연도 통합) — 월별로 전체 거래를 가격 기준 3등분(상/중/하 tercile)
    # 해 계절에 따라 등급별 가격이 어떻게 벌어지는지 본다. daily_grade_history와 같은
    # 방식이나 하루 단위가 아니라 달 단위로 묶은 값(요청, 2026-07-10).
    grade_chart = []
    for mo in range(1, 13):
        vals = sorted(by_month.get(mo, []))
        n = len(vals)
        entry: dict = {"월": f"{mo}월"}
        if n >= min_count:
            t1 = max(n // 3, 1)
            t2 = max(2 * n // 3, t1)
            bot, mid, top = vals[:t1], vals[t1:t2] or vals, vals[t2:] or vals[-1:]
            entry["상"] = round(mean(top) * 4)
            entry["중"] = round(mean(mid) * 4)
            entry["하"] = round(mean(bot) * 4)
        grade_chart.append(entry)

    return {
        "markets": markets,
        "chart": chart,
        "combined_4kg": combined_4kg,
        "combined_range_4kg": combined_range_4kg,
        "year_range": f"{years[0]}~{years[-1]}" if years else None,
        "years": [str(y) for y in years],
        "year_chart": year_chart,
        "grade_chart": grade_chart,
    }


# 하루 단위로 펼쳐볼 때 한 번에 너무 넓은 기간을 요청하면(예: 5년 전체) 응답이
# 수백~수천 포인트가 되어 차트가 무의미해진다 — 월별 사이클 카드의 "확대" 진입점은
# 항상 특정 구간(최대 아래 상한)만 보여주는 용도로 제한한다.
MAX_DAILY_RANGE_DAYS = 400


def daily_price_history(start: date, end: date, min_count: int = 1) -> dict:
    """지정 기간의 시장별 일자별 kg당 중앙값(4kg 환산) — 월별 사이클 차트의 "확대" 보기용.

    origin_market_cycle()/monthly_seasonal_cycle()은 월 단위로 뭉쳐서 계절 패턴을 보는
    용도라 특정 기간의 일자별 등락은 안 보인다. 이 함수는 같은 아카이브를 날짜 그대로
    묶어(월 단위로 다시 뭉치지 않고) 하루 단위 시계열을 돌려준다.
    """
    if end < start:
        start, end = end, start
    if (end - start).days > MAX_DAILY_RANGE_DAYS:
        start = end - timedelta(days=MAX_DAILY_RANGE_DAYS)

    rows = _read_rows()
    by_market_day: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        d_raw = row.get("거래일자", "")
        try:
            d = date.fromisoformat(d_raw)
        except ValueError:
            continue
        if not (start <= d <= end):
            continue
        ppk = _price_per_kg(row)
        if ppk is None:
            continue
        market = row.get("도매시장") or "시장 미상"
        by_market_day.setdefault((market, d_raw), []).append(ppk)

    markets = sorted({m for (m, _d) in by_market_day})
    all_days = sorted({d for (_m, d) in by_market_day})

    chart = []
    for d in all_days:
        entry: dict = {"날짜": d}
        for market in markets:
            vals = by_market_day.get((market, d), [])
            if len(vals) >= min_count:
                entry[market] = round(median(vals) * 4)
        chart.append(entry)

    return {
        "markets": markets,
        "chart": chart,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


def daily_grade_history(start: date, end: date) -> dict:
    """지정 기간의 시장별·일자별 상/중/하 등급 추정가(4kg 환산) — daily_price_history의
    등급별 버전. 시장×등급을 함께 보고 싶다는 요청(2026-07-10)에 맞춰 시장 단위로 나눈다.

    원본 경매 데이터엔 실제 "품종 등급" 필드가 없다(익산 제외 3개 시장 전부 품종은
    "완숙토마토"로 동일) — grade_avg_for_date()/tools/at_client._compute_grades와 같은
    방식으로, 시장별 하루 거래를 kg당 가격 기준 3등분(상/중/하 tercile)해 추정한다.
    실제 등급 판정이 아니라 그 시장·그날의 상대적 가격 구간 추정치임에 유의.
    """
    if end < start:
        start, end = end, start
    if (end - start).days > MAX_DAILY_RANGE_DAYS:
        start = end - timedelta(days=MAX_DAILY_RANGE_DAYS)

    rows = _read_rows()
    by_market_day: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        d_raw = row.get("거래일자", "")
        try:
            d = date.fromisoformat(d_raw)
        except ValueError:
            continue
        if not (start <= d <= end):
            continue
        ppk = _price_per_kg(row)
        if ppk is None:
            continue
        market = row.get("도매시장") or "시장 미상"
        by_market_day.setdefault((market, d_raw), []).append(ppk)

    markets = sorted({m for (m, _d) in by_market_day})
    by_market: dict[str, list[dict]] = {}
    for market in markets:
        days = sorted(d for (m, d) in by_market_day if m == market)
        chart = []
        for d in days:
            prices = sorted(by_market_day[(market, d)])
            n = len(prices)
            if n < 3:
                continue
            t1 = max(n // 3, 1)
            t2 = max(2 * n // 3, t1)
            bot, mid, top = prices[:t1], prices[t1:t2] or prices, prices[t2:] or prices[-1:]
            chart.append({
                "날짜": d,
                "상": round(mean(top) * 4),
                "중": round(mean(mid) * 4),
                "하": round(mean(bot) * 4),
            })
        by_market[market] = chart

    return {
        "markets": markets,
        "grades": ["상", "중", "하"],
        "by_market": by_market,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


def _same_month_day(base: date, year: int) -> date | None:
    """base와 같은 월-일을 year로 옮긴 날짜. 2/29처럼 해당 연도에 없는 날짜는 None."""
    try:
        return base.replace(year=year)
    except ValueError:
        return None


def daily_price_by_year(start: date, end: date, min_count: int = 1) -> dict:
    """일자별 확대 차트의 연도별 보기 — 시장별 미니차트는 그대로 두고, 고른 기간의
    월-일 구간을 아카이브에 있는 모든 연도에 겹쳐 그린다(요청, 2026-07-10).
    예: 5/10~7/9를 고르면 2021~2026년 각각의 5/10~7/9 구간을 시장별로 겹쳐본다.
    """
    if end < start:
        start, end = end, start
    span_days = min((end - start).days, MAX_DAILY_RANGE_DAYS)

    rows = _read_rows()
    years: set[int] = set()
    for row in rows:
        try:
            years.add(date.fromisoformat(row.get("거래일자", "")).year)
        except ValueError:
            continue
    years = sorted(years)

    # year_starts[y] = 그 해의 시작일(월-일 동일), None이면 그 해엔 존재 안 하는 날짜(윤년 2/29)
    year_starts = {y: _same_month_day(start, y) for y in years}

    by_market_offset_year: dict[tuple[str, int, int], list[float]] = {}
    offset_label: dict[int, str] = {}

    for row in rows:
        d_raw = row.get("거래일자", "")
        try:
            d = date.fromisoformat(d_raw)
        except ValueError:
            continue
        ppk = _price_per_kg(row)
        if ppk is None:
            continue
        market = row.get("도매시장") or "시장 미상"
        for y in years:
            y_start = year_starts[y]
            if y_start is None:
                continue
            offset = (d - y_start).days
            if 0 <= offset <= span_days:
                by_market_offset_year.setdefault((market, offset, y), []).append(ppk)
                offset_label.setdefault(offset, (start + timedelta(days=offset)).strftime("%m-%d"))

    markets = sorted({m for (m, _o, _y) in by_market_offset_year})
    by_market: dict[str, list[dict]] = {}
    for market in markets:
        chart = []
        for offset in range(0, span_days + 1):
            entry: dict = {"월일": offset_label.get(offset, f"D+{offset}")}
            has_any = False
            for y in years:
                vals = by_market_offset_year.get((market, offset, y), [])
                if len(vals) >= min_count:
                    entry[str(y)] = round(median(vals) * 4)
                    has_any = True
            if has_any:
                chart.append(entry)
        by_market[market] = chart

    return {
        "markets": markets,
        "years": [str(y) for y in years],
        "by_market": by_market,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
