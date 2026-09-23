"""따릉이 월별 이용정보 전수 재수집 (#7, #16).

기존 스냅샷은 월마다 약 30,000행에서 잘려 있었다. 서버 상한이 아니라 수집 쪽
정지 조건 때문이다 — spike에서 ``RNUM`` 100,000까지 반환되는 것을 확인했다.

## 왜 이어받지 않고 처음부터 다시 받는가

``RNUM``은 조밀한 인덱스가 아니다. 1,000행짜리 창이 525~786행만 돌려주고,
``LIST_TOTAL_COUNT``(93,187)를 넘는 위치에서도 행이 나온다. 즉 잘린 지점부터
이어받으면 **앞 구간에 빠진 행이 그대로 남는다.** 월마다 창을 끝까지 훑고, 받은
것을 논리 키로 접어 유니크 수가 보고된 총계에 닿는지 검증한다.

논리 키는 ``(대여소, 권종, 성별, 연령대)``다. 한 달 안에서 이 조합은 한 번만
나와야 한다 — 기존 스냅샷 1,832,580행에서도 이 키의 중복은 0이었다.

## 잘림이 무작위가 아니었다는 점

원천은 ``권종 → 성별 → 연령대 → 대여소`` 순으로 정렬돼 오고, 30,000에서 자르면
정렬 뒤쪽 범주가 통째로 사라진다. 기존 수집본은 60개월 중 39개월에 남성(M)이
아예 없고 54개월이 정기권만 갖고 있었다. 재수집이 필요한 이유는 "행이 모자라서"가
아니라 **범주가 빠져서**다.

## 실행

    KPUBDATA_SEOUL_API_KEY=<key> python collect_bike.py --out <dir>

월별로 파일을 하나씩 쓰므로 중간에 끊겨도 받은 달은 남는다. 다시 실행하면 이미
완료된 달은 건너뛴다. ``--months``로 나눠 받을 수 있다 — 서비스에 일일 호출
한도가 있고 60개월 전수는 수천 회다.

끝나면 ``--merge``로 월별 파일을 ``raw_records.jsonl`` 하나로 합치고, 그것을
``kpx snapshot register``로 등록한다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

BASE = "http://openapi.seoul.go.kr:8088"
SERVICE = "tbCycleRentUseMonthInfo"
ENVELOPE = "cycleRentUseMonthInfo"

#: 한 요청이 돌려줄 수 있는 최대 행 수 (catalogue의 max_page_size).
WINDOW = 1000

#: 새 행이 하나도 없는 창이 이만큼 연속되면 그 달은 끝난 것으로 본다.
#: 창이 듬성듬성해서 한 번 비었다고 끝이라고 볼 수 없다.
EMPTY_STREAK = 5

#: 보고된 총계의 몇 배까지 훑어볼 것인가. RNUM이 총계를 넘는 위치에도 있으므로
#: 총계에서 멈추면 안 되고, 그렇다고 무한정 돌 수도 없다.
REACH = 3

#: 동시에 띄울 요청 수. 측정해 보니 6창을 받는 데 동시 1이 78초, 동시 3이 39초,
#: 동시 6이 27초였다. 수익이 체감하고 동시 6에서는 응답이 깨져 JSONDecodeError가
#: 났다 — 서버가 키 단위로 처리량을 제한하는 것으로 보인다. 3이 2배를 얻으면서
#: 실패가 없는 지점이다.
WORKERS = 3

#: 한 달 안에서 한 번만 나와야 하는 조합.
KEY = ("STATION_NO", "RENT_TYPE", "GENDER_CD", "AGE_TYPE")


def months(start: str, end: str) -> list[str]:
    out, year, month = [], int(start[:4]), int(start[4:])
    while f"{year:04d}{month:02d}" <= end:
        out.append(f"{year:04d}{month:02d}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return out


def fetch(key: str, month: str, start: int, end: int, retries: int = 3) -> dict[str, Any]:
    """창 하나. 실패는 그대로 올린다 — 조용히 건너뛰면 구멍이 생긴다."""
    url = f"{BASE}/{key}/json/{SERVICE}/{start}/{end}/{month}"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    body = payload.get(ENVELOPE)
    if body is None:
        detail = json.dumps(payload, ensure_ascii=False)[:200]
        raise RuntimeError(f"{month} {start}-{end}: {detail}")
    return body


def absorb(records: dict[tuple[str, ...], dict], body: dict[str, Any]) -> None:
    """받은 행을 논리 키로 접어 넣는다. 같은 키가 다시 오면 덮어쓴다."""
    for row in body.get("row") or []:
        records[tuple(str(row.get(k, "")) for k in KEY)] = row


def collect_month(
    key: str, month: str, pause: float, workers: int
) -> tuple[dict[tuple[str, ...], dict], int]:
    """한 달을 논리 키로 접어 모은다. ``(레코드, 보고된 총계)``."""
    records: dict[tuple[str, ...], dict] = {}
    body = fetch(key, month, 1, WINDOW)
    total = int(body.get("list_total_count") or 0)
    absorb(records, body)

    start, empty = WINDOW + 1, 0
    ceiling = max(total * REACH, WINDOW * 10)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while len(records) < total and start <= ceiling and empty < EMPTY_STREAK:
            batch = [
                (s, s + WINDOW - 1)
                for s in range(start, min(start + WINDOW * workers, ceiling + 1), WINDOW)
            ]
            if not batch:
                break
            before = len(records)
            for body in pool.map(lambda w: fetch(key, month, w[0], w[1]), batch):
                absorb(records, body)
            # 창 하나가 아니라 묶음 단위로 센다. workers=3이면 빈 묶음 5회는
            # 빈 창 15개와 같아서, 듬성한 구간에서 성급히 멈추지 않는다.
            empty = 0 if len(records) > before else empty + 1
            start += WINDOW * len(batch)
            if pause:
                time.sleep(pause)
    return records, total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="월별 파일을 쓸 디렉터리")
    parser.add_argument("--months", nargs=2, default=("202001", "202412"), metavar=("START", "END"))
    parser.add_argument("--pause", type=float, default=0.1, help="묶음 사이 대기 (초)")
    parser.add_argument("--workers", type=int, default=WORKERS, help="동시 요청 수")
    parser.add_argument("--merge", action="store_true", help="월별 파일을 하나로 합치고 끝낸다")
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    wanted = months(*args.months)

    if args.merge:
        target = args.out / "raw_records.jsonl"
        written = 0
        with target.open("w", encoding="utf-8") as sink:
            for month in wanted:
                path = args.out / f"{month}.jsonl"
                if not path.exists():
                    print(f"[!] {month}: 파일이 없다 — 합치지 않는다")
                    continue
                for line in path.open(encoding="utf-8"):
                    sink.write(line)
                    written += 1
        print(f"{target}  {written:,}행")
        return 0

    key = os.environ.get("KPUBDATA_SEOUL_API_KEY")
    if not key:
        print("KPUBDATA_SEOUL_API_KEY 가 없다.", file=sys.stderr)
        return 2

    shortfall = []
    for month in wanted:
        path = args.out / f"{month}.jsonl"
        if path.exists():
            print(f"{month}  건너뜀 (이미 있음)", flush=True)
            continue

        started = time.perf_counter()
        records, total = collect_month(key, month, args.pause, args.workers)
        # 임시 파일에 쓰고 옮긴다 — 중간에 죽으면 반쯤 쓴 파일이 '완료'로 보인다.
        temp = path.with_suffix(".partial")
        with temp.open("w", encoding="utf-8") as sink:
            for row in records.values():
                sink.write(json.dumps(row, ensure_ascii=False) + "\n")
        temp.replace(path)

        got, elapsed = len(records), time.perf_counter() - started
        mark = "ok" if got >= total else "SHORT"
        print(
            f"{month}  {got:>7,} / {total:>7,}  {got / total:6.1%}  {elapsed:5.1f}s  {mark}",
            flush=True,
        )
        if got < total:
            shortfall.append((month, got, total))

    if shortfall:
        print(f"\n총계에 못 미친 달 {len(shortfall)}개:")
        for month, got, total in shortfall:
            print(f"  {month}  {got:,} / {total:,}")
        print("이 달들은 창 상한이나 연속 빈 창에서 멈춘 것이다. REACH/EMPTY_STREAK를")
        print("올려 다시 받거나, 그 달만 따로 확인해야 한다.")
        return 1

    print("\n모든 달이 보고된 총계에 도달했다. --merge 로 합쳐 스냅샷에 등록하라.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
