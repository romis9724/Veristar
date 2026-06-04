"""자연어 Q&A — 그래프 statement를 근거로 로컬 LLM(Ollama qwen3)이 답변 (GraphRAG).

핵심 제약(CLAUDE.md §4-4, §5):
- 모든 답변은 OFFICIAL·비민감 statement에서 인용된 사실만.
- 추론·평가·예측·미확인 정보를 포함하면 안 됨.
- LLM이 답변을 만들 때 그래프 밖의 지식을 추가하지 않도록 프롬프트로 강제.
- Ollama 미연결 시 "모델 미연결" 오류 반환 (graceful).
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass

from veristar.graph import GraphRepository, StatementFilter, StatementView, statements_for
from veristar.ontology.enums import Grade, Status

from .llm import chat


@dataclass(frozen=True)
class QAResult:
    question: str
    answer: str
    grounded_in: list[str]  # 근거 statement id 목록
    entity_id: str | None = None
    model_used: str | None = None


def _statements_to_context(views: list[StatementView]) -> str:
    """statement 목록을 프롬프트용 컨텍스트 텍스트로 변환."""
    lines: list[str] = []
    for v in views:
        s = v.statement
        other = v.other.name if v.other else v.other_id
        q = f" ({s.qualifier})" if s.qualifier else ""
        yr = f" [{s.valid_from}]" if s.valid_from else ""
        lines.append(f"- {s.predicate.value}: {other}{q}{yr} (grade={s.grade.value})")
    return "\n".join(lines)


def answer_question(
    repo: GraphRepository,
    question: str,
    entity_id: str | None = None,
    max_statements: int = 30,
) -> QAResult:
    """그래프에서 OFFICIAL 사실을 검색해 로컬 LLM(Ollama qwen3)에 근거 제공, 답변 생성."""
    filt = StatementFilter(grades=frozenset({Grade.OFFICIAL}), statuses=frozenset({Status.ACTIVE}))

    # 엔티티 지정 시 해당 엔티티만, 아니면 전체 검색(키워드 매칭)
    if entity_id:
        views = statements_for(repo, entity_id, filt)
    else:
        # 질문 '안에 언급된' 엔티티를 찾아 관련 statement 수집
        matched_entities = repo.find_mentioned(question, limit=3)
        views = []
        for e in matched_entities:
            views.extend(statements_for(repo, e.id, filt))

    views = [v for v in views if not v.statement.sensitive][:max_statements]
    grounded_ids = [v.statement.id for v in views]
    context = _statements_to_context(views) if views else "(관련 OFFICIAL 사실 없음)"

    system_prompt = textwrap.dedent("""
        당신은 Veristar 지식그래프의 Q&A 어시스턴트입니다.
        아래 제공된 [공식 확인 사실]만을 근거로 질문에 답하세요.

        규칙:
        1. 제공된 사실에 없는 내용은 절대 추가하지 마세요 (추론·예측·평가 금지).
        2. 확인할 수 없으면 "해당 정보는 그래프에 없습니다"라고 답하세요.
        3. 답변에 사용한 사실의 관계(predicate)를 간략히 언급하세요.
        4. 한국어로 간결하게 답하세요.
    """).strip()

    user_prompt = f"[공식 확인 사실]\n{context}\n\n[질문]\n{question}"

    result = chat(system_prompt, user_prompt, max_tokens=512)
    if not result.ok:
        return QAResult(
            question=question,
            answer=f"[오류] {result.error}",
            grounded_in=grounded_ids,
            entity_id=entity_id,
            model_used=result.model,
        )

    return QAResult(
        question=question,
        answer=result.text or "(응답 없음)",
        grounded_in=grounded_ids,
        entity_id=entity_id,
        model_used=result.model,
    )
