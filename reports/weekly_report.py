"""주간 자동 리포트 생성기"""
from datetime import datetime, timedelta
from agent.agent import ask


REPORT_PROMPT = """
지난 7일간 온실 토마토 생육 주간 리포트를 작성해줘.
다음 항목을 포함해:
1. 이번 주 온실 환경 요약 (평균 VPD, 최고·최저 온도)
2. 착과 상태 및 위험 발생 여부
3. 병해 발생 위험 및 방제 이력
4. 이번 주 GDD 누적량 및 현재 생육 단계
5. 다음 주 예상 기상 조건 및 주요 관리 포인트
"""


def generate_weekly_report() -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    report = ask(REPORT_PROMPT)
    return f"# 온실 토마토 주간 리포트\n생성일시: {timestamp}\n\n{report}"


def save_report(report: str) -> str:
    filename = f"reports/report_{datetime.now().strftime('%Y%m%d')}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(report)
    return filename


if __name__ == "__main__":
    report = generate_weekly_report()
    path = save_report(report)
    print(f"리포트 저장: {path}")
    print(report)
