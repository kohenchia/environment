import pytest

from stella import address


@pytest.mark.parametrize("text", ["Stella, do x", "stella do x", "S, do x", "s: do x", "  S , x", "@stella x",
                                  "can you ask Stella about it", "Stella"])
def test_addressed(text):
    assert address.is_addressed(text)


@pytest.mark.parametrize("text", ["So, do x", "Sure, do x", "fix the tests", "s3 bucket", "uses stellar", "S3, x", "This is S, x"])
def test_not_addressed(text):
    assert not address.is_addressed(text)


def test_kind():
    assert address.kind("S, what's running?") == "question"
    assert address.kind("S, review the PR") == "instruction"
    assert address.kind("S, can you build me a tool that does X and Y and tell me when it's done") == "instruction"


@pytest.mark.parametrize("text,ok", [("yes", True), ("S, yes", True), ("yes push it", True), ("looks good", False),
                                     ("ship it", False), ("go ahead", False), ("yes but wait", False)])
def test_affirmative(text, ok):
    assert address.is_affirmative(text) is ok
