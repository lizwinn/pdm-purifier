from simple import Greeting


def test_greeting() -> None:
    assert Greeting("World").text() == "Hello, World, from simple"
