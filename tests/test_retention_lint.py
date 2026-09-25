from production.contracts import FactPack, QualityStatus, SceneNarration, ScriptPlan
from production.retention_lint import RetentionLint
from production.script_quality_gate import ScriptQualityGate


def make_script(parts, duration=None):
    scenes = [
        SceneNarration(
            scene_index=index,
            narration=text,
            estimated_speech_duration_sec=seconds,
        )
        for index, (text, seconds) in enumerate(parts, start=1)
    ]
    full_script = " ".join(scene.narration for scene in scenes)
    return ScriptPlan(
        title="Retention fixture",
        scenes=scenes,
        full_script=full_script,
        estimated_total_duration_sec=duration or sum(seconds for _, seconds in parts),
    )


def warning_codes(result):
    return set(result.warnings)


def test_hook_followed_by_location_and_date_flags_background_tax():
    script = make_script([
        ("Một chiếc răng có vết cắt không thể hình thành tự nhiên.", 3),
        ("Năm 1932 tại tỉnh Quảng Tây, nhóm khảo cổ học của Đại học Đông Á bắt đầu phương pháp phân tầng.", 7),
        ("Hợp chất trên chiếc răng cho thấy một người từng nhai hạt cau.", 4),
        ("Dấu vết nhỏ ấy trả lại một thói quen thật cho người vô danh.", 4),
    ])
    result = RetentionLint().evaluate(script)
    assert "BACKGROUND_TOO_EARLY" in warning_codes(result)


def test_unpaid_curiosity_debt_is_detected():
    script = make_script([
        ("Một mảnh xương mang vết cắt lạ.", 3),
        ("Nhưng đó chưa phải điều lạ nhất.", 2),
        ("Năm 1920, viện nghiên cứu tại khu vực này bắt đầu phương pháp khảo cổ học kéo dài.", 10),
        ("Hóa ra vết cắt thuộc về bàn tay một người thợ cổ.", 4),
    ])
    result = RetentionLint().evaluate(script)
    assert "UNPAID_CURIOSITY_DEBT" in warning_codes(result)
    assert result.curiosity_debt == "unpaid"


def test_object_evidence_contradiction_in_first_seven_seconds_passes():
    script = make_script([
        ("Một chiếc răng còn giữ hợp chất từ hạt cau.", 3),
        ("Nhưng kết quả ấy sớm hơn giả thuyết cũ.", 3),
        ("Vết mòn thứ hai buộc họ hỏi ai đã nhai nó?", 4),
        ("Hóa ra bằng chứng đổi cách ta hiểu cuộc sống của người vô danh.", 4),
    ])
    result = RetentionLint().evaluate(script)
    assert result.pass_ is True
    assert result.first_10s_viability >= 6


def test_four_obscure_proper_nouns_in_first_ten_seconds_are_flagged():
    fact_pack = FactPack(
        topic="Di chỉ",
        entities=["Hang Lạc Sơn", "Đại học Bắc Hà", "Tạp chí Cổ Sinh", "Hệ tầng Lam Ngọc"],
    )
    script = make_script([
        ("Một mảnh xương ở Hang Lạc Sơn mang vết cắt bất thường.", 3),
        ("Đại học Bắc Hà và Tạp chí Cổ Sinh xếp nó vào Hệ tầng Lam Ngọc.", 6),
        ("Nhưng dấu vết thứ hai cho thấy một người từng dùng công cụ ở đây.", 4),
        ("Chiếc xương kể lại lao động của một người vô danh.", 4),
    ])
    result = RetentionLint().evaluate(script, fact_pack=fact_pack)
    assert "PROPER_NOUN_OVERLOAD" in warning_codes(result)
    assert result.proper_noun_load == "high"


def test_generic_ending_is_rejected():
    script = make_script([
        ("Một chiếc răng giữ lại hợp chất màu đỏ.", 3),
        ("Nhưng vết mòn cho thấy nó từng được nhai mỗi ngày.", 4),
        ("Bằng chứng đó sửa lại niên đại của tập tục.", 4),
        ("Lịch sử vẫn còn nhiều bí ẩn.", 3),
    ])
    result = RetentionLint().evaluate(script)
    assert "GENERIC_HUMAN_PAYOFF" in warning_codes(result)
    assert result.generic_ending is True
    assert result.pass_ is False


def test_sixty_second_script_with_one_reveal_has_weak_density():
    script = make_script([
        ("Một chiếc bình có vết cháy bất thường.", 5),
        ("Câu chuyện tiếp tục với nhiều lời mô tả chung chung không đổi cách hiểu.", 20),
        ("Phần tiếp theo vẫn chỉ diễn giải bối cảnh quen thuộc của câu chuyện.", 20),
        ("Người xem được nhắc lại nội dung ban đầu mà không có dấu vết mới.", 15),
    ], duration=60)
    result = RetentionLint().evaluate(script, target_duration_sec=60)
    assert "WEAK_INFORMATION_DENSITY" in warning_codes(result)


def test_evidence_reveal_correction_and_human_payoff_passes():
    script = make_script([
        ("Một chiếc răng giữ hợp chất từ hạt cau.", 3),
        ("Nhưng vết mòn thứ hai xuất hiện ở mặt trong.", 4),
        ("Vì sao hai dấu vết lại nằm trên cùng một chiếc răng?", 5),
        ("Mẫu quét cho thấy lớp men đã mòn qua nhiều năm sử dụng.", 10),
        ("Đến giây ba mươi, phép đo đồng vị tiết lộ chủ nhân đã di chuyển rất xa.", 10),
        ("Hóa ra đây không phải nghi lễ hiếm mà là một thói quen hằng ngày.", 8),
        ("Chiếc răng nhỏ giờ kể được hành trình và bữa ăn của một người vô danh.", 8),
    ], duration=48)
    result = RetentionLint().evaluate(script, target_duration_sec=48)
    assert result.pass_ is True
    assert result.correction_present is True
    assert result.human_payoff_present is True
    assert "WEAK_INFORMATION_DENSITY" not in warning_codes(result)


def test_quality_gate_blocks_bad_retention_only_when_policy_is_enabled():
    script = make_script([
        ("Hôm nay chúng ta sẽ tìm hiểu một câu chuyện thú vị.", 5),
        ("Năm 1920 tại một viện nghiên cứu, phương pháp khảo cổ học bắt đầu.", 7),
        ("Lịch sử vẫn còn nhiều bí ẩn.", 3),
    ])
    gate = ScriptQualityGate()
    legacy = gate.evaluate(script, target_duration_sec=15, enforce_retention=False)
    enforced = gate.evaluate(script, target_duration_sec=15, enforce_retention=True)

    assert legacy.status != QualityStatus.FAIL
    assert enforced.status == QualityStatus.FAIL
    assert enforced.retention_lint is not None
    assert enforced.retention_lint.pass_ is False
    assert any(v.rule_id == "GENERIC_HUMAN_PAYOFF" for v in enforced.violations)
