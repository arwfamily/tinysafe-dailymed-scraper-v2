# TinySafe 성분 정답지 파이프라인

리포: `github.com/arwfamily/tinysafe-dailymed-scraper-v2`

성분 데이터를 **스냅샷 → 시계열 → 정답지**로 바꾸는 전체 구조입니다.
전부 실제 데이터(520 제품 · 6,279 리콜)로 실행 검증했습니다.

---

## 무엇이 문제였나

| 문제 | 상태 |
|---|---|
| 결과가 30일 아티팩트로만 나가고 리포에 `data/` 없음 | → 커밋 구조 |
| 과거 스냅샷이 없어 리포뮬레이션 추적 불가 | → 이력 로그 |
| 그물이 ZnO/TiO2 활성 검색뿐이라 화학필터 제품 수집 불가 | → UNII 확장 |
| 성분 DB와 리콜 DB가 따로 놀아 교차가 수작업 | → 자동 조인 |

---

## 파일 4개

```
scripts/resolve_uniis.py          신규 — UV필터 이름 → UNII 코드 (API에서 조회)
scripts/snapshot_and_history.py   신규 — 스냅샷 + 리포뮬레이션 이력
scripts/build_answer_keys.py      신규 — 클레임 감사 · 리콜 조인 · 관할 매트릭스
scripts/dailymed_scraper.py       수정 — UNII 시드를 파일에서 (scraper_patch.md 참조)
.github/workflows/scrape.yml      교체
```

## 적용 (GitHub 웹, 터미널 불필요)

1. `scripts/` 아래 파이썬 3개 추가
2. `scripts/dailymed_scraper.py`에 `scraper_patch.md`의 한 블록 적용
3. `.github/workflows/scrape.yml` 교체
4. Actions → Run workflow → **먼저 limit `10`** (스모크) → 확인 후 **limit `0`**

---

## 생기는 구조

```
data/
  reference/uv_filter_uniis.json        검색 시드 + 조회 근거
  raw/dailymed/YYYY-MM-DD/master.json   ★ 불변 원본. 진짜 자산
  canonical/us_sunscreens.jsonl         최신 상태 (미여과 전량)
  history/us_formulation_history.jsonl  ★ append-only 관측 로그. 시간이 만드는 자산
  history/_state.json
  views/claim_audit.jsonl               정답지 ①
  views/recall_join.jsonl               정답지 ②
  views/jurisdiction_matrix.json        정답지 ③ (규제 파일 있을 때만)
  views/mineral_sunscreens.json         파생 뷰
```

**`raw/`와 `history/`만 자산입니다.** `views/`는 지우고 다시 돌리면 복구됩니다.

---

## 정답지 3종 — 실측 결과

### ① 클레임 감사 (`claim_audit.jsonl`)

라벨의 말이 전성분과 일치하는가. 기계적으로 답이 나오는 질문만 검사합니다.
`all_mineral_actives` · `no_hidden_uv_boosters` · `fragrance_free` ·
`hawaii_act_104_compatible` · `hundred_percent_mineral`.

모든 판정에 **근거 성분이 붙습니다.** 전성분표가 비면 PASS가 아니라 UNKNOWN입니다.

520개 실행 결과:
```
all_mineral_actives        PASS 518  FAIL 2
fragrance_free             PASS 514  FAIL 6
no_hidden_uv_boosters      PASS 520  FAIL 0   ← 경고 발동
hawaii_act_104_compatible  PASS 520  FAIL 0   ← 경고 발동
```

**★ UNIFORMITY WARNING이 스스로 울렸습니다.** 실패 0건은 시장이 완벽해서가 아니라
**입력이 같은 조건으로 사전필터됐다**는 뜻입니다. 8월 24일에 직접 잡으신 순환논리를
이제 도구가 매번 자동으로 감시합니다.

### ② 리콜 조인 (`recall_join.jsonl`)

성분 DB의 브랜드를 리콜 6,279건에 대조합니다. **52/520 매칭.**

여기 오기까지 두 번 고쳤습니다:
- 1차 토큰 겹침 → **282/520 오탐** ("REPAIR", "NATURAL", "CARE"가 의료기기 리콜과 매칭)
- 수리 1: **데이터 기반 변별력** — 리콜 18건 이상에 나오는 토큰은 일반어로 강등 (16,320개만 변별력 인정)
- 수리 2: 전체 브랜드 구절이 **브랜드 필드 안에** 있어야 함 + 일반 단어 단독 브랜드("Zinc", "Cloud") 차단

최종 상위: Coppertone 6 · **Badger 2 (2013 미생물오염 정확히 회수)** · Aveeno 2.

⚠️ 매 레코드에 caveat가 박힙니다 — **브랜드 매칭이지 동일 제품 증명이 아닙니다.**
(Boon Flair↔Costway 오매칭 전과를 구조로 막는 부분)

### ③ 관할 매트릭스 (`jurisdiction_matrix.json`)

`data/regulatory/`에 규제 파일을 넣으면 자동 생성됩니다. **지금은 없어서 안 만들어집니다**
— 그리고 없다는 사실을 로그에 명시합니다(조용히 건너뛰지 않음).

넣어야 할 파일 (이미 만드셨는데 리포에 없는 것들):
```
data/regulatory/eu_annex_vi.jsonl               EU Annex VI (UV필터 33종)
data/regulatory/au_permissible_ingredients.json TGA 법령 (성분 5,246)
data/regulatory/kr_uv_filters.jsonl             식약처 별표2
data/regulatory/us_monograph_m020.jsonl         FDA M020
```

**이게 세 정답지 중 가장 값어치 있는 것입니다.** 정답이 명확하고, 출처가 법령이고,
지금 LLM들이 계속 틀리는 질문이니까요. `/mnt/user-data/outputs/`에서 꺼내 커밋하세요.

---

## 그물 확장 — 검증된 것과 막힌 것

| 경로 | 결과 |
|---|---|
| `marketing_category_code` 파라미터 | ✅ 지원됨. **OTC Monograph Drug = C200263** (FDA 코드표 확인) |
| C200263으로 선크림 선별 | ❌ 모든 OTC 모노그래프 의약품 — 제산제·기침약 포함. 너무 넓음 |
| **M020으로 질의** | ❌ **불가.** M020은 marketing category 안의 하위 번호이고, `/spls` 필터 목록에 없음 |
| **UNII 합집합 확장** | ✅ 채택. 검증된 경로, 리스크 0 |

`resolve_uniis.py`가 UV필터 20여 종의 UNII를 API에서 조회합니다. 판정 5종
(ok / single_inexact / ambiguous / not_found / zero_spls) 전부 가짜 API로 검증 완료.
`ok`가 아닌 것도 파일에 기록되어 **구멍이 보이게** 남습니다.

### ★ 지금 그물을 넓혀야 하는 진짜 이유 — 타이밍

FDA 제안명령 **OTC000039**가 M020에 **베모트리지놀을 6%까지 추가**하려 하고 있습니다.
베모트리지놀은 호주 데이터에서 **3위권 필터(145개)**인데 미국엔 미승인이었습니다.

확정되면 미국 선크림 처방이 대규모로 움직입니다. 그런데 **전후를 말하려면 그 전의
스냅샷이 있어야 합니다.** 화학필터 제품이 DB에 없으면 이 사건을 한 건도 못 잡습니다.

---

## 안전장치 (전부 실행 검증)

| 상황 | 동작 |
|---|---|
| 스모크런 (limit≠0) | `--partial` — 스냅샷만, canonical/history 무접촉 |
| master 0개 | 실행 거부 |
| setid 20% 이상 실종 | 중단 — 시장 이벤트가 아니라 실패한 스크레이프 |
| UNII 시드 파일 없음/깨짐 | 미네랄 2종 자동 폴백 — 수집이 멈추지 않음 |
| 사용 가능 시드 2개 미만 | resolver가 거부 |
| 동시 런 충돌 | pull --rebase 3회 |

## 변경 판정 규칙

`formulation_hash` = 활성(정렬+함량) + 부형제(**원순서 유지**) + 제형.
제목·회사·날짜 제외 — 로고만 바꿔도 처방 변경으로 찍히면 이력이 오염됩니다.

| change | 뜻 |
|---|---|
| `new` | 처음 관측 |
| `reformulated` | 성분 지문 이동 (+ **confidence high/low**) |
| `metadata` | 처방 동일, 표시만 변경 (from→to diff 기록) |
| `delisted` | 이전 런엔 있었고 이번엔 없음 |

**`delisted`와 `reformulated`는 절대 안 섞입니다.** 2013 Badger 로션과 2026 Badger
크림을 같은 제품의 전후로 착각한 것이 정확히 이 오류였습니다 — 앞의 것은 단종,
뒤의 것은 원래 따로 있던 라인이었습니다.

**confidence 등급**: 바뀐 성분이 전부 UNII 식별이면 `high`, UNII 없는 게 섞이면 `low`.
실측 케이스 — `SUNFLOWER OIL` → `HELIANTHUS ANNUUS (SUNFLOWER) OIL`은 표기 변경일 뿐인데
통용명↔라틴명은 문자열로 같게 만들 수 없습니다. 그래서 지우지 않고 **표시**합니다.
`keys_added`/`keys_removed`에 뭐가 움직였는지 그대로 나옵니다.

---

## 첫 풀런 후 확인 3가지

1. **`inactive rows without UNII` 비율** — 앞으로 `low confidence` 이벤트가 얼마나
   나올지를 결정합니다. 높으면 Phase D의 XML 경로를 손봐야 합니다.

2. **babyganics 존재 여부** (`setid edced0dc-dd43-4ac9-b816-f4edb45fc87b`)
   raw에 **있으면** → 누락은 `tinysafe-data`의 `build_baby_feed.py` 사전필터 문제.
   **없으면** → 스크레이퍼 문제. 지금 열려 있는 유일한 데이터 무결성 질문입니다.

3. **UNIFORMITY WARNING이 사라졌는지** — 그물이 제대로 넓어졌으면
   `no_hidden_uv_boosters`에 FAIL이 나와야 정상입니다. 여전히 0이면 그물이 안 넓어진 것.

---

## 다음 사이클

이 파이프라인이 매주 돌면 앤젤라가 손으로 할 일은 사라집니다. 남는 건 두 가지:

- **`data/regulatory/` 채우기** — 이미 만든 EU·AU·KR 파일을 커밋. 정답지 ③이 켜집니다
- **발행** — `views/`의 산출물을 tinysafe.app에 인용 가능한 페이지로

발행되지 않은 정답지는 정답지가 아닙니다. 이 리포가 공개인데 데이터가 없어서
검증도 인용도 불가능했던 것이 오늘 확인한 상태였습니다.
