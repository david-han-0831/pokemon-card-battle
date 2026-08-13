"""CORS 허용 규칙 테스트.

배포하고 나서 "왜 프론트에서 방이 안 만들어지지"로 헤매기 쉬운 부분이라 고정해 둔다.
"""

from __future__ import annotations

import re

import pytest

from app.config import Settings

# 미리보기 URL 은 두 형태가 있다.
#   배포 해시:  pokemon-card-battle-ag4cxan6u-davids-projects-2b1e0768.vercel.app
#   브랜치 이름: pokemon-card-battle-git-main-davids-projects-2b1e0768.vercel.app
# 브랜치 이름엔 하이픈이 들어가므로 가운데는 [a-z0-9-]+ 여야 한다.
# 점(.)은 문자 클래스에 없으므로 `...-evil.com-davids-projects-...` 같은 위장은 안 걸린다.
PREVIEW_REGEX = r"^https://pokemon-card-battle-[a-z0-9-]+-davids-projects-[a-z0-9]+\.vercel\.app$"


def test_origin_list_is_split_and_trimmed():
    s = Settings(cors_origins=" https://a.example , https://b.example ,, ")
    assert s.cors_origin_list == ["https://a.example", "https://b.example"]


def test_empty_regex_means_disabled():
    """빈 문자열이면 미들웨어에 None 을 넘겨 패턴 허용을 끈다."""
    assert Settings(cors_origin_regex="").cors_origin_regex == ""
    assert (Settings(cors_origin_regex="").cors_origin_regex or None) is None


@pytest.mark.parametrize(
    "origin",
    [
        "https://pokemon-card-battle-ag4cxan6u-davids-projects-2b1e0768.vercel.app",
        "https://pokemon-card-battle-abc123-davids-projects-2b1e0768.vercel.app",
        "https://pokemon-card-battle-git-main-davids-projects-2b1e0768.vercel.app",
        "https://pokemon-card-battle-git-feat-new-ui-davids-projects-2b1e0768.vercel.app",
    ],
)
def test_preview_urls_match(origin):
    assert re.match(PREVIEW_REGEX, origin)


@pytest.mark.parametrize(
    "origin",
    [
        # 남의 팀 프로젝트 — 팀 슬러그를 패턴에 넣은 이유
        "https://pokemon-card-battle-abc123-someone-else.vercel.app",
        # 점이 문자 클래스에 없어서 도메인을 끼워 넣을 수 없다
        "https://pokemon-card-battle-evil.com-davids-projects-2b1e0768.vercel.app",
        # 서브도메인을 덧붙인 위장
        "https://pokemon-card-battle-abc-davids-projects-2b1e0768.vercel.app.evil.com",
        # 앞에 뭔가 붙인 위장
        "https://evil.com/pokemon-card-battle-abc-davids-projects-2b1e0768.vercel.app",
        "http://pokemon-card-battle-abc-davids-projects-2b1e0768.vercel.app",  # http
    ],
)
def test_lookalike_origins_do_not_match(origin):
    assert re.match(PREVIEW_REGEX, origin) is None


def test_production_alias_is_in_the_exact_list_not_the_regex():
    """운영 별칭(-two)은 해시 형태가 아니라 패턴에 안 걸린다 → 목록으로 넣어야 한다."""
    assert re.match(PREVIEW_REGEX, "https://pokemon-card-battle-two.vercel.app") is None
