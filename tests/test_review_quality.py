import pytest

from factory.review_quality import (
    ReviewFindingCategory,
    ReviewFindingSeverity,
    ReviewVerdictParseError,
    ReviewVerdictStatus,
    parse_review_verdict,
)


def test_parse_pass_review():
    verdict = parse_review_verdict(
        """
        {
            "verdict": "pass",
            "summary": "Implementation is sound.",
            "findings": []
        }
        """
    )

    assert (
        verdict.verdict
        == ReviewVerdictStatus.PASS
    )

    assert verdict.blocks_quality_gate is False
    assert verdict.blocking_findings == ()


def test_parse_warn_review():
    verdict = parse_review_verdict(
        """
        {
            "verdict": "warn",
            "summary": "Minor scope concern.",
            "findings": [
                {
                    "severity": "warning",
                    "category": "scope",
                    "message": "Extra refactor detected.",
                    "blocking": false
                }
            ]
        }
        """
    )

    assert (
        verdict.verdict
        == ReviewVerdictStatus.WARN
    )

    finding = verdict.findings[0]

    assert (
        finding.severity
        == ReviewFindingSeverity.WARNING
    )

    assert (
        finding.category
        == ReviewFindingCategory.SCOPE
    )

    assert finding.effectively_blocking is False


def test_parse_block_review():
    verdict = parse_review_verdict(
        """
        {
            "verdict": "block",
            "summary": "Security problem found.",
            "findings": [
                {
                    "severity": "critical",
                    "category": "security",
                    "message": "Unsafe command execution.",
                    "blocking": true
                }
            ]
        }
        """
    )

    assert (
        verdict.verdict
        == ReviewVerdictStatus.BLOCK
    )

    assert verdict.blocks_quality_gate is True

    assert len(
        verdict.blocking_findings
    ) == 1


def test_error_severity_is_effectively_blocking():
    verdict = parse_review_verdict(
        """
        {
            "verdict": "block",
            "summary": "Correctness failure.",
            "findings": [
                {
                    "severity": "error",
                    "category": "correctness",
                    "message": "Wrong result returned.",
                    "blocking": false
                }
            ]
        }
        """
    )

    assert (
        verdict.findings[0]
        .effectively_blocking
        is True
    )


def test_fenced_json_is_supported():
    verdict = parse_review_verdict(
        """```json
{
    "verdict": "pass",
    "summary": "Looks good.",
    "findings": []
}
```"""
    )

    assert (
        verdict.verdict
        == ReviewVerdictStatus.PASS
    )


def test_invalid_json_is_rejected():
    with pytest.raises(
        ReviewVerdictParseError,
        match="valid JSON",
    ):
        parse_review_verdict(
            "not-json"
        )


def test_unknown_verdict_is_rejected():
    with pytest.raises(
        ReviewVerdictParseError,
        match="Unsupported review verdict",
    ):
        parse_review_verdict(
            """
            {
                "verdict": "maybe",
                "summary": "Unknown",
                "findings": []
            }
            """
        )


def test_warn_cannot_hide_blocking_finding():
    with pytest.raises(
        ReviewVerdictParseError,
        match="PASS/WARN",
    ):
        parse_review_verdict(
            """
            {
                "verdict": "warn",
                "summary": "Claims warning only.",
                "findings": [
                    {
                        "severity": "critical",
                        "category": "security",
                        "message": "Critical issue.",
                        "blocking": false
                    }
                ]
            }
            """
        )


def test_block_requires_blocking_finding():
    with pytest.raises(
        ReviewVerdictParseError,
        match="requires at least",
    ):
        parse_review_verdict(
            """
            {
                "verdict": "block",
                "summary": "Blocked without cause.",
                "findings": [
                    {
                        "severity": "warning",
                        "category": "other",
                        "message": "Minor issue.",
                        "blocking": false
                    }
                ]
            }
            """
        )


def test_quality_gate_allows_pass():
    from factory.review_quality import (
        QualityGateDecisionStatus,
        evaluate_review_quality_gate,
    )

    verdict = parse_review_verdict(
        """
        {
            "verdict": "pass",
            "summary": "All checks passed.",
            "findings": []
        }
        """
    )

    decision = evaluate_review_quality_gate(
        verdict
    )

    assert (
        decision.status
        == QualityGateDecisionStatus.ALLOW
    )

    assert decision.allowed is True
    assert decision.blocked is False


def test_quality_gate_allows_warning():
    from factory.review_quality import (
        QualityGateDecisionStatus,
        evaluate_review_quality_gate,
    )

    verdict = parse_review_verdict(
        """
        {
            "verdict": "warn",
            "summary": "Minor issue.",
            "findings": [
                {
                    "severity": "warning",
                    "category": "scope",
                    "message": "Small extra change.",
                    "blocking": false
                }
            ]
        }
        """
    )

    decision = evaluate_review_quality_gate(
        verdict
    )

    assert (
        decision.status
        == QualityGateDecisionStatus
        .ALLOW_WITH_WARNING
    )

    assert decision.allowed is True


def test_quality_gate_blocks_block_verdict():
    from factory.review_quality import (
        QualityGateDecisionStatus,
        evaluate_review_quality_gate,
    )

    verdict = parse_review_verdict(
        """
        {
            "verdict": "block",
            "summary": "Security issue.",
            "findings": [
                {
                    "severity": "critical",
                    "category": "security",
                    "message": "Unsafe execution.",
                    "blocking": true
                }
            ]
        }
        """
    )

    decision = evaluate_review_quality_gate(
        verdict
    )

    assert (
        decision.status
        == QualityGateDecisionStatus.BLOCK
    )

    assert decision.allowed is False
    assert decision.blocked is True


def test_quality_gate_reads_review_checkpoint():
    from factory.review_quality import (
        QualityGateDecisionStatus,
        evaluate_review_checkpoint_quality_gate,
    )

    checkpoint = {
        "checkpoint_id": "CP-1",
        "summary": """
        {
            "verdict": "pass",
            "summary": "Review passed.",
            "findings": []
        }
        """,
    }

    decision = (
        evaluate_review_checkpoint_quality_gate(
            checkpoint
        )
    )

    assert (
        decision.status
        == QualityGateDecisionStatus.ALLOW
    )


def test_quality_gate_rejects_checkpoint_without_summary():
    from factory.review_quality import (
        evaluate_review_checkpoint_quality_gate,
    )

    with pytest.raises(
        ReviewVerdictParseError,
        match="no summary",
    ):
        evaluate_review_checkpoint_quality_gate(
            {
                "checkpoint_id": "CP-1",
            }
        )


def _quality_source_checkpoint(
    checkpoint_id="CP-SOURCE",
):
    return {
        "checkpoint_id": checkpoint_id,
        "step_index": 0,
        "agent_name": "coder-agent",
        "provider_name": "test-provider",
        "status": "completed",
        "payload": {
            "handoff_request": {
                "required_capabilities": [
                    "review_code"
                ],
                "quality_gate": True,
            }
        },
    }


def _quality_review_checkpoint(
    summary,
    *,
    checkpoint_id="CP-REVIEW",
    source_checkpoint_id="CP-SOURCE",
):
    return {
        "checkpoint_id": checkpoint_id,
        "step_index": 0,
        "agent_name": "reviewer-agent",
        "provider_name": "test-provider",
        "status": "completed",
        "summary": summary,
        "payload": {
            "source_checkpoint_id": (
                source_checkpoint_id
            )
        },
    }


def test_quality_report_reads_persisted_review():
    from factory.review_quality import (
        build_review_quality_report,
    )

    report = build_review_quality_report(
        [
            _quality_source_checkpoint(),
            _quality_review_checkpoint(
                """
                {
                    "verdict": "pass",
                    "summary": "Looks good.",
                    "findings": []
                }
                """
            ),
        ]
    )

    assert (
        report["overall_status"]
        == "passed"
    )

    assert report["total_reviews"] == 1
    assert report["passed"] == 1
    assert report["blocked"] == 0
    assert report["invalid"] == 0


def test_quality_report_ignores_non_gate_handoff():
    from factory.review_quality import (
        build_review_quality_report,
    )

    source = (
        _quality_source_checkpoint()
    )

    source["payload"][
        "handoff_request"
    ]["quality_gate"] = False

    report = build_review_quality_report(
        [
            source,
            _quality_review_checkpoint(
                "not structured"
            ),
        ]
    )

    assert (
        report["overall_status"]
        == "not_reviewed"
    )

    assert report["total_reviews"] == 0


def test_quality_report_aggregates_block():
    from factory.review_quality import (
        build_review_quality_report,
    )

    report = build_review_quality_report(
        [
            _quality_source_checkpoint(),
            _quality_review_checkpoint(
                """
                {
                    "verdict": "block",
                    "summary": "Critical issue.",
                    "findings": [
                        {
                            "severity": "critical",
                            "category": "security",
                            "message": "Unsafe behavior.",
                            "blocking": true
                        }
                    ]
                }
                """
            ),
        ]
    )

    assert (
        report["overall_status"]
        == "blocked"
    )

    assert report["blocked"] == 1


def test_quality_report_marks_invalid_review():
    from factory.review_quality import (
        build_review_quality_report,
    )

    report = build_review_quality_report(
        [
            _quality_source_checkpoint(),
            _quality_review_checkpoint(
                "legacy natural language review"
            ),
        ]
    )

    assert (
        report["overall_status"]
        == "invalid"
    )

    assert report["invalid"] == 1
    assert (
        report["reviews"][0]["decision"]
        is None
    )
