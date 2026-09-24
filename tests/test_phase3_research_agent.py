"""
Unit Tests for Phase 3 - Research Agent & FactPack Engine
Tests:
- FactPack & ClaimItem schema validation.
- LocalResearchProvider deterministic extraction from instructions and transcripts.
- ResearchAgent fallback mechanism from Gemini to Local.
- Entity extraction, claim criticality, and suggested angles.
"""

from unittest.mock import MagicMock
import pytest

from production.contracts import ClaimItem, FactPack
from production.research_service import (
    GeminiResearchProvider,
    LocalResearchProvider,
    ResearchAgent,
)


def test_fact_pack_and_claim_item_schema():
    claim = ClaimItem(
        claim="Mộng gỗ Kigumi không sử dụng đinh sắt.",
        evidence="Kỹ thuật mộc truyền thống Nhật Bản.",
        confidence=0.98,
        is_critical=True,
        allowed_wording="Kỹ thuật mộc mộng hoàn toàn không cần tới đinh kim loại.",
        source_ref="manual_01",
    )
    assert claim.is_critical is True
    assert claim.confidence == 0.98

    fact_pack = FactPack(
        topic="Kỹ thuật mộng gỗ Kigumi",
        claims=[claim],
        confidence_score=0.96,
        entities=["Kigumi", "gỗ", "đục"],
        suggested_angles=["Nghệ thuật ghép gỗ không dùng đinh"],
        contradictions=[],
    )
    assert fact_pack.topic == "Kỹ thuật mộng gỗ Kigumi"
    assert len(fact_pack.claims) == 1
    assert "Kigumi" in fact_pack.entities


def test_local_research_provider_extraction():
    provider = LocalResearchProvider()
    instruction = "Làm video về quy trình chế tác mộng gỗ tinh xảo với độ chính xác 0.1 mm"
    transcripts = [
        "Người thợ dùng đục và bào thủ công để gọt từng thớ gỗ.",
        "Mỗi thanh gỗ ghép lại khít khao chịu lực hàng trăm năm.",
    ]

    fact_pack = provider.extract_fact_pack(instruction, source_transcripts=transcripts)

    assert isinstance(fact_pack, FactPack)
    assert len(fact_pack.claims) >= 3
    # Check that topic was identified
    assert fact_pack.topic
    # Check domain entities detected
    entity_text = " ".join(fact_pack.entities).lower()
    assert "gỗ" in entity_text or "đục" in entity_text or "0.1 mm" in entity_text

    # Verify at least one critical claim exists
    critical_claims = [c for c in fact_pack.claims if c.is_critical]
    assert len(critical_claims) >= 1

    # Verify suggested angles
    assert len(fact_pack.suggested_angles) >= 2


def test_research_agent_fallback_on_gemini_error():
    mock_gemini = MagicMock(spec=GeminiResearchProvider)
    mock_gemini.extract_fact_pack.side_effect = RuntimeError("API quota exceeded or network down")

    agent = ResearchAgent(provider=mock_gemini)
    fact_pack = agent.generate_fact_pack(
        instruction="Hướng dẫn nấu nước dùng mì Ramen Tonkotsu đậm đà",
        source_transcripts=["Xương heo hầm trong 12 giờ ở nhiệt độ cao để chiết xuất collagen."],
    )

    # Should fall back gracefully to LocalResearchProvider without throwing
    assert isinstance(fact_pack, FactPack)
    assert "Ramen" in fact_pack.topic or "Tonkotsu" in fact_pack.topic or "nấu" in fact_pack.topic
    assert len(fact_pack.claims) >= 3
    assert fact_pack.confidence_score >= 0.80
