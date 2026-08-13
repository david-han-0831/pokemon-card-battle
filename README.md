# 포켓몬 카드 배틀

랜덤으로 받은 6마리로 6라운드를 겨루는 1:1 실시간 배틀.
각 라운드는 **기술을 골라 가며 상대가 쓰러질 때까지 싸우는 턴제 전투**다.
**FastAPI(WebSocket) + React + Three.js + Postgres** 풀스택 예제 프로젝트.

```
로비 → 방 코드 매칭 → 서버가 6마리씩 딜링
  → [라운드 x6]  포켓몬 선택 (상대 패 비공개)
                   ↓ 양쪽 제출 — 여기서 처음 서로 공개
                 턴제 전투: 기술 4개 중 하나를 동시 선택 → 스피드 순 판정
                   ↓ 한쪽 HP 0
                 라운드 승패
  → 승수 비교
```

- 기획: [`docs/plan.md`](docs/plan.md)
- 확정 설계(로스터·티어·기술 선정·데미지 공식·WS 프로토콜·DB 스키마): [`docs/design.md`](docs/design.md)

---

## 빠르게 실행하기

### 0. 사전 준비

Docker · Python 3.12+ · Node 18+

### 1. DB 띄우기

```bash
docker compose up -d
```

호스트 **5433** 포트로 Postgres 16 이 뜬다 (5432 를 이미 쓰고 있어도 안 부딪히게).

### 2. 백엔드

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

로스터와 기술을 PokeAPI 에서 한 번 긁어 온다 (포켓몬 40마리 + 공격기술 314개, 약 1분):

```bash
python -m scripts.seed --show-movesets
```

서버 실행:

```bash
uvicorn app.main:app --reload --port 8000
```

> ⚠️ **워커는 1개**로 띄운다. 진행 중인 게임 상태가 프로세스 메모리에 있어서
> 워커가 여러 개면 방이 프로세스마다 갈라진다.

### 3. 프론트엔드

```bash
cd frontend
npm install
npm run dev
```

http://localhost:5173 접속. `/api` 와 `/ws` 는 Vite 프록시가 백엔드로 넘긴다.

### 4. 혼자서 테스트하기

일반 창에서 **방 만들기** → 방 코드 복사 → **시크릿 창**에서 그 코드로 **입장하기**.
양쪽에서 준비 완료를 누르면 시작된다.

---

## 배포된 곳

| 레이어 | 위치 | 주소 |
|---|---|---|
| 프론트 | Vercel (정적 빌드) | https://pokemon-card-battle-two.vercel.app |
| 백엔드 | NAS Docker `nb-pokemon-api` (호스트 8012) | https://pokemon-api.han-david.com |
| DB | NAS 공용 Postgres 16 의 `pokemon_battle` | — |

**왜 백엔드를 Vercel 에 안 올렸나**: 진행 중인 게임 상태가 프로세스 메모리에 있고
WebSocket 을 길게 붙들고 있어야 한다. 서버리스는 요청 단위로 뜨고 죽으므로 둘 다 안 맞는다.
(`vercel link` 가 `backend/` 를 감지해 서버리스 서비스로 넣으려 하는데, `vercel.json` 에서 뺐다.)

프론트는 빌드 시점에 `frontend/.env.production` 의 `VITE_API_BASE` 를 박아 넣는다.
개발에서는 이 값이 비어 있고 Vite 프록시가 `/api`·`/ws` 를 `localhost:8000` 으로 넘긴다.

### 백엔드 재배포

```bash
git archive HEAD:backend | ssh nas "tar -x -C /volume1/docker/nas-backend/pokemon-backend"
ssh nas 'cd /volume1/docker/nas-backend && sudo -n /usr/local/bin/docker compose up -d --build --no-deps pokemon-api'
ssh nas 'curl -s http://127.0.0.1:8012/health'
```

> 🔴 `--no-deps pokemon-api` 를 반드시 붙인다. 그 compose 파일에는 서비스가 15개 물려 있어서
> 서비스명을 빼면 전부가 대상이 되고, `--remove-orphans` 가 붙으면 남의 서비스가 삭제된다.

시딩은 컨테이너 안에서 한 번만:

```bash
ssh nas 'sudo -n /usr/local/bin/docker exec nb-pokemon-api python -m scripts.seed'
```

스키마를 바꿨다면 `--force` 로 다시 긁거나, 테이블을 지우고 다시 만들어야 한다
(마이그레이션 도구를 안 쓰므로 `create_all` 은 기존 테이블을 바꾸지 않는다).

### 프론트 재배포

GitHub 연동이 걸려 있어 **main 에 push 하면 자동 배포**된다. 수동으로 하려면:

```bash
vercel deploy --prod --yes
```

### CORS — 미리보기 배포까지 받기

Vercel 미리보기 배포는 URL 이 매번 바뀐다.

```
pokemon-card-battle-ag4cxan6u-davids-projects-2b1e0768.vercel.app   (배포 해시)
pokemon-card-battle-git-main-davids-projects-2b1e0768.vercel.app    (브랜치 이름)
```

고정 목록으로는 못 받으므로 `CORS_ORIGIN_REGEX` 로 패턴 허용한다.
**팀 슬러그까지 패턴에 넣어** 이름이 비슷한 남의 프로젝트가 통과하지 못하게 좁혔다.

```
^https://pokemon-card-battle-[a-z0-9-]+-davids-projects-[a-z0-9]+\.vercel\.app$
```

점(`.`)이 문자 클래스에 없어서 `...-evil.com-davids-projects-...` 같은 위장도 안 걸린다.
경계 케이스는 `tests/test_cors.py` 가 고정한다.

> ⚠️ **CORS 는 WebSocket 에 적용되지 않는다.** 브라우저가 Origin 을 보내긴 하지만
> 프리플라이트가 없고 미들웨어도 HTTP 만 본다. 즉 소켓은 어느 오리진에서든 붙을 수 있다.
> 그래도 안전한 이유는 방 코드만으로는 못 들어오고 **`player_token` 을 제시해야** 하기 때문이다.

---

## 테스트

```bash
cd backend
python -m pytest -q
```

DB 도 서버도 안 띄우고 **87개**가 2초 안에 돈다. 세 갈래다:

- `tests/test_battle.py` — 타입 상성표, 능력치 환산, 데미지 공식, 명중, 턴 순서,
  발버둥, 라운드 종료 판정, 기술 선정 규칙, 딜링 알고리즘 (전부 순수 함수)
- `tests/test_game_flow.py` — 가짜 소켓으로 게임 루프 전체.
  **상대 손패·상대 PP·상대의 이번 턴 선택이 새지 않는지**가 핵심.
  **DB 가 영원히 멈춰 있어도 6라운드가 끝까지 도는지**도 여기서 검증한다.
- `tests/test_cors.py` — 배포 후 "왜 프론트에서 방이 안 만들어지지"로 헤매기 쉬운
  CORS 허용 규칙의 경계 케이스

---

## 프로젝트 구조

```
backend/
  app/
    main.py         FastAPI 앱, lifespan(테이블 생성 + 로스터 로드)
    config.py       .env → 설정 객체 (제한시간·라운드 수·턴 상한)
    db.py           비동기 엔진/세션
    models.py       DB 모델 (pokemon / moves / pokemon_moves / types / rooms / room_players / rounds)
    schemas.py      REST 스키마
    roster.py       로스터 명단 + 티어 컷라인 + ★기술 선정 규칙
    type_chart.py   18타입 상성표
    battle.py       ★전투 엔진 — 데미지 공식, 명중, 턴 처리 (DB·소켓 모름)
    dealing.py      가중치 비복원 추출
    game.py         ★게임 상태 머신. 히든 정보 필터링의 핵심
    ws.py           WebSocket 엔드포인트 (얇게 유지)
    routers/        REST (방 생성/입장, 로스터 조회)
  scripts/seed.py   PokeAPI → DB 시딩 (포켓몬 + 기술)
  tests/

frontend/src/
  api.js                 REST 클라이언트 + WS 주소 생성
  useGameSocket.js       ★소켓 메시지 → 화면 상태 (useReducer)
  screens/Lobby.jsx      방 만들기 / 입장
  screens/Battle.jsx     스테이지 + HP바 + 턴로그 + (손패 | 기술바)
  components/CardTile.jsx  손패 카드
  components/MoveBar.jsx   기술 4개 선택
  components/TypeChip.jsx  타입 아이콘 (서버에서 받은 공식 이미지)
  three/BattleStage.jsx  ★Three.js 2.5D 스테이지 + 파티클 엔진
  three/typeEffects.js   ★타입 18종 이펙트 정의
```

---

## 이 예제에서 배울 것

### 1. 히든 정보는 서버가 지킨다 (핵심)

상대 정보를 클라이언트에 보내면 개발자도구로 다 보인다. **필터링은 서버에서 해야 한다.**
이 게임은 숨겨야 할 층이 **세 겹**이다.

| 단계 | 공개 | 비공개 |
|---|---|---|
| 카드 선택 | 상대 손패 **장수** | 손패 내용, 상대가 무엇을 냈는지 |
| 전투 시작 | 상대 포켓몬·스탯·**기술 목록** | 상대 기술의 **남은 PP** |
| 매 턴 | (양쪽 제출 후) 두 기술과 데미지 | 상대가 이번 턴에 고른 기술 |

같은 객체를 보는 사람에 따라 다르게 직렬화하는 게 전부다:

```python
# app/battle.py — private 하나로 내 것/상대 것이 갈린다
def to_payload(self, *, private: bool, versus: Card | None = None) -> dict:
    ...
    entry = m.to_payload(current_pp=self.pp.get(m.move_id) if private else None)
    if private and versus is not None:
        entry["effectiveness"] = move_multiplier(m, versus)
```

상대가 뭔가를 했을 때 나가는 건 `opponent_played` / `opponent_move_selected`
**빈 페이로드**뿐이다. `tests/test_game_flow.py` 가
"내 소켓이 받은 모든 바이트에 상대 카드 ID 가 없다",
"상대가 기술을 골랐을 때 추가로 온 메시지는 빈 알림 하나뿐이다"를 실제로 검사한다.

### 2. 서버 권위 (anti-cheat)

클라이언트가 보내는 건 "이 카드/기술을 쓰겠다"는 의사표시뿐이고, 서버가 전부 검증한다.

```python
# 그 기술을 정말 갖고 있고 PP 가 남았는가? 발버둥은 쓸 게 없을 때만 허용.
if move_id not in player.fighter.usable_move_ids():
    await self._send_error(player, "INVALID_MOVE", "지금 쓸 수 없는 기술입니다.")
```

프론트도 **서버가 승인(`play_accepted` / `move_accepted`)한 뒤에야** 화면을 바꾼다.
낙관적 업데이트를 하면 거부당했을 때 화면과 서버가 어긋난다.

### 3. 규칙은 한 군데에만 둔다

기술 버튼의 ×2 / ×0.5 배지는 **프론트가 계산하지 않는다.** 서버가 `effectiveness` 를 실어 보낸다.
타입 상성표를 프론트에도 두면 규칙이 두 군데 살게 되고, 한쪽만 고치는 순간 화면과 판정이 어긋난다.

### 4. 외부 API 캐싱 — 합집합 먼저, 요청은 나중에

PokeAPI 를 게임 턴마다 부르면 느리고, 남의 서버에 민폐고, 그쪽이 죽으면 우리도 죽는다.
그래서 시딩 스크립트로 한 번만 긁어 우리 DB 에 복사한다.

기술이 특히 그렇다. 포켓몬 40마리가 배우는 기술을 순진하게 부르면 **3853번**이지만,
이름으로 **합집합을 먼저 만들면 508번**이면 끝난다.

```python
move_names = sorted(set().union(*(learnable_move_names(m) for m in mons)))
```

### 5. 데이터로 만든 밸런스

티어(S/A/B/C)는 손으로 정하지 않는다. base stat 총합(BST)에서 계산한다.

| 티어 | BST | 마릿수 | 딜링 확률 |
|---|---|---|---|
| S | ≥ 520 | 11 | 12.1% |
| A | 470~519 | 15 | 33.0% |
| B | 420~469 | 10 | 33.0% |
| C | < 420 | 4 | 22.0% |

낮은 티어일수록 가중치를 높여 S급이 가끔만 나오게 한다(손패 6장당 평균 0.7마리).
가중치 비복원 추출은 Efraimidis-Spirakis 알고리즘 — `app/dealing.py`.

### 6. "데이터가 그대로 게임이 되지는 않는다" — 기술 선정

PokeAPI 가 준 기술을 그냥 쓰면 게임이 망가진다. 두 번 걸러야 했다.

- **위력 110 상한**: 1세대 포켓몬이 배우는 위력 120+ 기술은 사실상 전부 대가가 붙어 있다
  (이판사판태클=반동, 솔라빔=차지, 역린=혼란, 엄청난힘=능력하락, 대폭발=자폭).
  그 대가를 구현하지 않은 채 넣으면 **"무조건 이거 쓰면 됨"** 이 되어 기술 선택이 사라진다.
- **타입 다양성 강제**: 위력순으로 4개를 뽑으면 리자몽이
  플레어드라이브/연옥/열풍/화염방사 — 전부 불꽃을 들고 나온다.
  자속 1개를 먼저 넣고 나머지는 서로 다른 타입에서 채운다.
- **기대 위력(위력 × 명중률)으로 비교**: 그냥 위력순이면 눈보라(110/70)가
  냉동빔(90/100)을 밀어내는데 기댓값은 77 vs 90 으로 오히려 손해다.

결과: 40마리 전부가 서로 다른 4타입 기술을 갖는다.
`python -m scripts.seed --show-movesets` 로 확인할 수 있다.

### 7. 느린 DB 를 사용자가 기다리게 하지 마라

배포하고 나서 **방 만들기가 23초** 걸려 화면이 멈춘 것처럼 보이는 일이 있었다.
원인은 서버가 올라간 NAS 가 단일 HDD 였고 그 디스크가 포화 상태였다는 것
(iowait 22%, `select count(*)` 한 번에 2~8초).

디스크는 우리가 어쩔 수 없지만, **애초에 기다릴 이유가 없는 구조**였다.
방·손패·판정은 전부 메모리에 있고 DB 는 나중에 볼 기록일 뿐인데
방 생성 API 가 커밋을 `await` 하고 있었다. 그래서 기록용 쓰기를 전부 뒤로 뺐다.

```python
# app/game.py — 방마다 DB 쓰기를 하나의 체인으로 이어 붙인다
def schedule_db(self, game, make_coro):
    previous = game.db_task
    async def runner():
        if previous is not None:
            try: await previous          # 순서 보장: rooms → players → rounds (FK)
            except Exception: pass       # 앞이 실패해도 뒤는 시도
        try: await make_coro()
        except Exception: logger.exception(...)
    game.db_task = asyncio.create_task(runner())
```

`/api/types` 도 시작할 때 메모리에 올려 DB 경유를 없앴다.

결과: 방 생성 **23초 → 0.3초**(연결이 따뜻할 때). 남은 지연은 Cloudflare 터널 왕복이다.

교훈은 "비동기로 던져라"가 아니라 **어떤 데이터가 진행에 필요하고 어떤 게 기록일 뿐인지
구분하라**는 것이다. 기록은 늦어도 되지만, 순서가 필요하면(FK) 그 순서는 지켜야 한다.
`tests/test_game_flow.py` 가 "DB 가 영원히 멈춰 있어도 6라운드가 끝까지 돈다"를 검증한다.

### 8. 순수 함수로 분리하면 테스트가 싸진다

`battle.py` 는 DB 도 소켓도 모르고, **난수까지 인자로 받는다**(`rng`).
그래서 데미지 공식을 `roll=1.0` 으로 고정해 정확한 값을 검증할 수 있다.

`game.py` 가 DB 를 건드리는 지점도 두 곳(`_persist_round`, `_mark_room_finished`)뿐이라,
그것만 막으면 게임 루프 전체를 서버 없이 테스트할 수 있다.

### 9. Three.js — 에셋 없이 3D처럼 보이게

PokeAPI 는 **2D 스프라이트만** 준다. 그래서 섞는다:

- 바닥은 진짜 3D — 회전하는 원기둥 발판 + 발광 링 + 그리드
- 캐릭터는 `THREE.Sprite` = 항상 카메라를 향하는 **빌보드**
- 피격 순간엔 스프라이트 흔들림 + 적색 플래시

렌더 루프는 React 바깥에서 돈다 — **매 프레임 setState 하면 초당 60번 리렌더된다.**

### 10. 없는 에셋은 코드로 만든다 — 기술 이펙트

**PokeAPI 에 기술 이미지는 아예 없다.** `/move/{name}` 에 sprite·image·icon 계열 키가 하나도 없다.
있는 건 타입 아이콘(`/type/{name}` → sprites)과 한글 설명뿐이다. 그래서 나눠서 처리한다.

| 필요한 것 | 방법 |
|---|---|
| 타입 배지 | PokeAPI 공식 이미지를 시딩 |
| 기술 설명 | PokeAPI 한글 flavor text 를 툴팁으로 |
| **기술 이펙트** | **Three.js 파티클로 직접 생성** |

`frontend/src/three/typeEffects.js` 에 **분사 패턴 11가지 × 타입 18종**을 정의한다.

```js
fire:  { mode: 'projectile', colors: [0xff4d00, 0xffd166], speed: 11, gravity:  2.2, ... }
ground:{ mode: 'ground',     colors: [0xc08a4a, 0x7a5227], speed:  8, gravity: -9,   ... }
dark:  { mode: 'implode',    colors: [0x6b4dff, 0x160f28], speed:  6, gravity:  0,   ... }
```

불꽃은 날아가며 위로 뜨고, 땅은 발밑에서 솟았다 떨어지고, 악은 바깥에서 안으로 빨려든다.
상성 배율에 따라 크기도 바뀐다(2배 1.35× / 0배 0.3× / 빗나감 0.45×) — 결과가 눈에 보이게.

한편 **타입 아이콘은 두 종류를 다 받는다.** 이름이 적힌 가로 배지(200×40)와
정사각 심볼(60×60)이 있는데, 118px 짜리 손패 카드에 가로 배지 2개는 안 들어간다.
넓은 자리(기술 버튼)엔 배지, 좁은 자리(카드)엔 심볼을 쓴다.

> 파티클 크기는 `PointsMaterial` 의 객체 단위 속성이라 하나의 `Points` 로는
> 타입마다 다르게 줄 수 없다. per-particle 크기엔 `ShaderMaterial` 이 필요한데
> 예제엔 과하므로 방출기 4개를 돌려 쓴다 — 동시 재생도 이걸로 해결된다.

---

## 전투 공식 요약

```
능력치(레벨 50) = 종족값 + 20        (HP 는 종족값 + 75)

base = ((2*50/5 + 2) * 위력 * 공격 / 방어) / 50 + 2
데미지 = floor( base × 자속(1.5) × 타입상성(0~4) × 난수(0.85~1.00) )
```

- 물리기는 공격/방어, 특수기는 특공/특방
- 스피드가 빠른 쪽이 먼저 — **먼저 쓰러뜨리면 상대는 반격 못 한다**
- 빗나가도 PP 는 소모된다
- PP 가 전부 떨어지면 **발버둥**(위력 50, 상성 무시, 준 데미지의 1/4 반동)
- 30턴을 넘기면 남은 HP 비율로 승부를 가른다

---

## 알려진 한계 (의도적으로 범위 밖)

- **상태이상·능력변화·반동·차지·급소·날씨·특성 미구현.** 그래서 변화기를 통째로 빼고
  위력 110 초과 기술을 후보에서 제외했다(§6 참조).
- **발버둥은 거의 발동하지 않는다.** 기술 4개 × PP 10~15 = 40회 이상인데
  전투는 보통 2~5턴에 끝나기 때문. 교착 상황의 안전장치에 가깝다.
- **단일 프로세스 전제.** 게임 상태가 메모리에 있어 워커를 늘리면 방이 갈라진다.
  실무라면 Redis 같은 공유 저장소로 뺀다.
- **마이그레이션 도구 없음.** `Base.metadata.create_all` 로 테이블을 만든다.
  스키마를 바꾸면 `docker compose down -v` 로 갈아엎어야 한다. 실무라면 Alembic.
- **서버 재시작 시 진행 중 게임 소실.** 끝난 라운드 기록만 DB 에 남는다.
- **방이 메모리에서 회수되지 않는다.** 오래 띄워 둘 거라면 정리 작업이 필요하다.
  (새로고침 재접속을 살려 두려고 일부러 즉시 삭제하지 않았다.)
- 계정/로그인, 랭킹, 3인 이상, 교체 없음.
