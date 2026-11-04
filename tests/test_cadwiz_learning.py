from integrations.cadwiz_plugin.learning import lesson_request


def test_guided_learning_keeps_user_in_control():
    request = lesson_request("Guide me", "Round an edge")
    assert request["topic"] == "Round an edge"
    assert "Do not modify" in request["ask"]
    assert "inspect my result" in request["ask"]


def test_demonstration_protects_original_and_waits_between_steps():
    request = lesson_request("Show me", "")
    assert request["topic"] == "the current model"
    assert "practice copy" in request["ask"]
    assert "wait for me" in request["ask"]


def test_explanation_does_not_request_edits():
    assert "Do not modify" in lesson_request("Explain this", "fillet")["ask"]
