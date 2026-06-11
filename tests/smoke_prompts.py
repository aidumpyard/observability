"""Prompt repo unit smoke: save -> version bump -> load latest -> resolve -> render."""

import tempfile

from prism.prompts import PromptRepo


def main():
    root = tempfile.mkdtemp()
    repo = PromptRepo(root)

    p1 = repo.save("demo", "greet", "Hello {name} from v1", meta={"variables": ["name"]})
    assert p1.version == 1 and p1.ref == "demo/greet@v1"

    p2 = repo.save("demo", "greet", "Hi {name}, this is v2", meta={"variables": ["name"]})
    assert p2.version == 2, p2.version
    assert repo.versions("demo", "greet") == [1, 2]
    assert repo.latest_version("demo", "greet") == 2

    latest = repo.load("demo", "greet")
    assert latest.version == 2
    assert latest.render(name="Ada").strip() == "Hi Ada, this is v2"

    old = repo.resolve("demo/greet@v1")
    assert old.render(name="Ada").strip() == "Hello Ada from v1"

    assert repo.list_apps() == ["demo"]
    assert repo.list_prompts("demo") == ["greet"]

    # render with no values returns raw (literal braces preserved)
    repo.save("demo", "json", 'Return {{"k": 1}} exactly', meta={})
    assert repo.load("demo", "json").render().strip() == 'Return {{"k": 1}} exactly'

    print("✅ PROMPTS OK — save/version-bump/load/resolve/render all work")


if __name__ == "__main__":
    main()
