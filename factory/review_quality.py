import json
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ReviewVerdictParseError(ValueError):
    pass


class ReviewVerdictStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"


class ReviewFindingSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ReviewFindingCategory(str, Enum):
    CORRECTNESS = "correctness"
    REGRESSION = "regression"
    SECURITY = "security"
    SCOPE = "scope"
    OTHER = "other"


@dataclass(frozen=True)
class ReviewFinding:
    severity: ReviewFindingSeverity
    category: ReviewFindingCategory
    message: str
    blocking: bool = False

    @property
    def effectively_blocking(self) -> bool:
        return bool(
            self.blocking
            or self.severity
            in {
                ReviewFindingSeverity.ERROR,
                ReviewFindingSeverity.CRITICAL,
            }
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity.value,
            "category": self.category.value,
            "message": self.message,
            "blocking": self.blocking,
            "effectively_blocking": (
                self.effectively_blocking
            ),
        }


@dataclass(frozen=True)
class ReviewVerdict:
    verdict: ReviewVerdictStatus
    summary: str
    findings: tuple[ReviewFinding, ...]

    @property
    def blocking_findings(
        self,
    ) -> tuple[ReviewFinding, ...]:
        return tuple(
            finding
            for finding in self.findings
            if finding.effectively_blocking
        )

    @property
    def blocks_quality_gate(self) -> bool:
        return (
            self.verdict
            == ReviewVerdictStatus.BLOCK
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "summary": self.summary,
            "findings": [
                finding.as_dict()
                for finding in self.findings
            ],
            "blocking_findings": [
                finding.as_dict()
                for finding
                in self.blocking_findings
            ],
            "blocks_quality_gate": (
                self.blocks_quality_gate
            ),
        }


def _require_non_blank(
    value: Any,
    field_name: str,
) -> str:
    normalized = str(
        value or ""
    ).strip()

    if not normalized:
        raise ReviewVerdictParseError(
            f"{field_name} must not be blank"
        )

    return normalized


def _extract_json_text(
    raw_text: str,
) -> str:
    text = _require_non_blank(
        raw_text,
        "review response",
    )

    if not text.startswith("```"):
        return text

    lines = text.splitlines()

    if len(lines) < 3:
        raise ReviewVerdictParseError(
            "Invalid fenced review JSON"
        )

    opening = lines[0].strip().lower()

    if opening not in {
        "```",
        "```json",
    }:
        raise ReviewVerdictParseError(
            "Unsupported review code fence"
        )

    if lines[-1].strip() != "```":
        raise ReviewVerdictParseError(
            "Review JSON fence is not closed"
        )

    return "\n".join(
        lines[1:-1]
    ).strip()


def parse_review_verdict(
    raw_text: str,
) -> ReviewVerdict:
    json_text = _extract_json_text(
        raw_text
    )

    try:
        payload = json.loads(
            json_text
        )
    except json.JSONDecodeError as exc:
        raise ReviewVerdictParseError(
            "Review response is not valid JSON"
        ) from exc

    if not isinstance(payload, dict):
        raise ReviewVerdictParseError(
            "Review response must be a JSON object"
        )

    raw_verdict = _require_non_blank(
        payload.get("verdict"),
        "review verdict",
    ).lower()

    try:
        verdict = ReviewVerdictStatus(
            raw_verdict
        )
    except ValueError as exc:
        raise ReviewVerdictParseError(
            "Unsupported review verdict: "
            f"{raw_verdict}"
        ) from exc

    summary = _require_non_blank(
        payload.get("summary"),
        "review summary",
    )

    raw_findings = payload.get(
        "findings",
        [],
    )

    if not isinstance(
        raw_findings,
        list,
    ):
        raise ReviewVerdictParseError(
            "review findings must be a list"
        )

    findings: list[ReviewFinding] = []

    for index, item in enumerate(
        raw_findings,
        start=1,
    ):
        if not isinstance(item, dict):
            raise ReviewVerdictParseError(
                "review finding "
                f"{index} must be an object"
            )

        raw_severity = _require_non_blank(
            item.get("severity"),
            f"finding {index} severity",
        ).lower()

        try:
            severity = ReviewFindingSeverity(
                raw_severity
            )
        except ValueError as exc:
            raise ReviewVerdictParseError(
                "Unsupported finding severity: "
                f"{raw_severity}"
            ) from exc

        raw_category = _require_non_blank(
            item.get("category"),
            f"finding {index} category",
        ).lower()

        try:
            category = ReviewFindingCategory(
                raw_category
            )
        except ValueError as exc:
            raise ReviewVerdictParseError(
                "Unsupported finding category: "
                f"{raw_category}"
            ) from exc

        message = _require_non_blank(
            item.get("message"),
            f"finding {index} message",
        )

        blocking = item.get(
            "blocking",
            False,
        )

        if not isinstance(
            blocking,
            bool,
        ):
            raise ReviewVerdictParseError(
                "finding blocking must be boolean"
            )

        findings.append(
            ReviewFinding(
                severity=severity,
                category=category,
                message=message,
                blocking=blocking,
            )
        )

    result = ReviewVerdict(
        verdict=verdict,
        summary=summary,
        findings=tuple(findings),
    )

    if (
        verdict
        in {
            ReviewVerdictStatus.PASS,
            ReviewVerdictStatus.WARN,
        }
        and result.blocking_findings
    ):
        raise ReviewVerdictParseError(
            "PASS/WARN review cannot contain "
            "blocking findings"
        )

    if (
        verdict
        == ReviewVerdictStatus.BLOCK
        and not result.blocking_findings
    ):
        raise ReviewVerdictParseError(
            "BLOCK review requires at least "
            "one blocking finding"
        )

    return result


class QualityGateDecisionStatus(str, Enum):
    ALLOW = "allow"
    ALLOW_WITH_WARNING = "allow_with_warning"
    BLOCK = "block"


@dataclass(frozen=True)
class QualityGateDecision:
    status: QualityGateDecisionStatus
    review_verdict: ReviewVerdict
    reason: str

    @property
    def allowed(self) -> bool:
        return (
            self.status
            != QualityGateDecisionStatus.BLOCK
        )

    @property
    def blocked(self) -> bool:
        return not self.allowed

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "allowed": self.allowed,
            "blocked": self.blocked,
            "reason": self.reason,
            "review": (
                self.review_verdict.as_dict()
            ),
        }


def evaluate_review_quality_gate(
    review: ReviewVerdict,
) -> QualityGateDecision:
    if (
        review.verdict
        == ReviewVerdictStatus.BLOCK
    ):
        return QualityGateDecision(
            status=(
                QualityGateDecisionStatus.BLOCK
            ),
            review_verdict=review,
            reason=(
                "Reviewer reported blocking "
                "quality findings."
            ),
        )

    if (
        review.verdict
        == ReviewVerdictStatus.WARN
    ):
        return QualityGateDecision(
            status=(
                QualityGateDecisionStatus
                .ALLOW_WITH_WARNING
            ),
            review_verdict=review,
            reason=(
                "Reviewer reported "
                "non-blocking warnings."
            ),
        )

    return QualityGateDecision(
        status=(
            QualityGateDecisionStatus.ALLOW
        ),
        review_verdict=review,
        reason=(
            "Reviewer found no blocking "
            "quality problems."
        ),
    )


def evaluate_review_checkpoint_quality_gate(
    checkpoint: dict[str, Any],
) -> QualityGateDecision:
    if not isinstance(
        checkpoint,
        dict,
    ):
        raise ReviewVerdictParseError(
            "review checkpoint must be an object"
        )

    summary = checkpoint.get(
        "summary"
    )

    if summary is None:
        raise ReviewVerdictParseError(
            "review checkpoint has no summary"
        )

    review = parse_review_verdict(
        str(summary)
    )

    return evaluate_review_quality_gate(
        review
    )


def _checkpoint_payload(
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    payload = checkpoint.get("payload")

    if isinstance(payload, dict):
        return payload

    return {}


def _is_quality_gate_review_checkpoint(
    checkpoint: dict[str, Any],
    checkpoints_by_id: dict[
        str,
        dict[str, Any],
    ],
) -> bool:
    payload = _checkpoint_payload(
        checkpoint
    )

    source_checkpoint_id = str(
        payload.get(
            "source_checkpoint_id",
            "",
        )
        or ""
    ).strip()

    if not source_checkpoint_id:
        return False

    source_checkpoint = (
        checkpoints_by_id.get(
            source_checkpoint_id
        )
    )

    if source_checkpoint is None:
        return False

    source_payload = _checkpoint_payload(
        source_checkpoint
    )

    handoff_request = source_payload.get(
        "handoff_request"
    )

    if not isinstance(
        handoff_request,
        dict,
    ):
        return False

    if (
        handoff_request.get(
            "quality_gate"
        )
        is not True
    ):
        return False

    capabilities = handoff_request.get(
        "required_capabilities",
        [],
    )

    if not isinstance(
        capabilities,
        (list, tuple, set, frozenset),
    ):
        return False

    return "review_code" in {
        str(item).strip().lower()
        for item in capabilities
    }


def build_review_quality_report(
    checkpoints: list[dict[str, Any]],
) -> dict[str, Any]:
    checkpoints_by_id = {
        str(
            checkpoint.get(
                "checkpoint_id",
                "",
            )
        ): checkpoint
        for checkpoint in checkpoints
        if str(
            checkpoint.get(
                "checkpoint_id",
                "",
            )
        ).strip()
    }

    reviews: list[
        dict[str, Any]
    ] = []

    for checkpoint in checkpoints:
        if not (
            _is_quality_gate_review_checkpoint(
                checkpoint,
                checkpoints_by_id,
            )
        ):
            continue

        review_item: dict[str, Any] = {
            "checkpoint_id": (
                checkpoint.get(
                    "checkpoint_id"
                )
            ),
            "step_index": (
                checkpoint.get(
                    "step_index"
                )
            ),
            "agent_name": (
                checkpoint.get(
                    "agent_name"
                )
            ),
            "provider_name": (
                checkpoint.get(
                    "provider_name"
                )
            ),
            "checkpoint_status": (
                checkpoint.get(
                    "status"
                )
            ),
        }

        try:
            decision = (
                evaluate_review_checkpoint_quality_gate(
                    checkpoint
                )
            )
        except ReviewVerdictParseError as exc:
            review_item.update(
                {
                    "status": "invalid",
                    "decision": None,
                    "error": str(exc),
                }
            )
        else:
            review_item.update(
                {
                    "status": "parsed",
                    "decision": (
                        decision.as_dict()
                    ),
                    "error": None,
                }
            )

        reviews.append(
            review_item
        )

    passed = 0
    warnings = 0
    blocked = 0
    invalid = 0

    for review in reviews:
        if review["status"] == "invalid":
            invalid += 1
            continue

        decision = review.get(
            "decision"
        ) or {}

        status = str(
            decision.get(
                "status",
                "",
            )
        )

        if (
            status
            == QualityGateDecisionStatus.BLOCK.value
        ):
            blocked += 1

        elif (
            status
            == QualityGateDecisionStatus
            .ALLOW_WITH_WARNING
            .value
        ):
            warnings += 1

        elif (
            status
            == QualityGateDecisionStatus.ALLOW.value
        ):
            passed += 1

    if invalid:
        overall_status = "invalid"
    elif blocked:
        overall_status = "blocked"
    elif warnings:
        overall_status = "warning"
    elif passed:
        overall_status = "passed"
    else:
        overall_status = "not_reviewed"

    return {
        "overall_status": overall_status,
        "total_reviews": len(reviews),
        "passed": passed,
        "warnings": warnings,
        "blocked": blocked,
        "invalid": invalid,
        "reviews": reviews,
    }
