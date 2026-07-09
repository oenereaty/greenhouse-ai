"""Auction ledger archive and origin-market cycle summaries."""
from __future__ import annotations

import csv
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean

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
