"""아주 단순한 프로세스 내 TTL 캐시 — 단일 사용자 로컬 앱이라 라이브러리 불필요.

dict + timestamp 만으로 충분한 규모(고정된 8개 내외 리소스)이므로
cachetools/fastapi-cache2 같은 의존성을 추가하지 않는다.
"""
import time
from typing import Callable, TypeVar

T = TypeVar("T")

_CACHE: dict[str, tuple[float, object]] = {}


def cached(key: str, ttl_seconds: float, fn: Callable[[], T]) -> T:
    """key로 캐시된 값이 ttl_seconds 이내면 재사용, 아니면 fn()을 호출해 갱신."""
    now = time.time()
    hit = _CACHE.get(key)
    if hit is not None and (now - hit[0]) < ttl_seconds:
        return hit[1]  # type: ignore[return-value]
    value = fn()
    _CACHE[key] = (now, value)
    return value


def invalidate(key: str) -> None:
    _CACHE.pop(key, None)


def set_value(key: str, value: object) -> None:
    """외부에서 강제로 최신값을 채워넣을 때(예: '새로고침' 버튼) 사용."""
    _CACHE[key] = (time.time(), value)


def clear_all() -> None:
    _CACHE.clear()
