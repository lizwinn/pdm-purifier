from importlib.metadata import version


def main() -> None:
    import docutils
    import yoyo

    print(
        f"yoyo-migrations {version('yoyo-migrations')} ({yoyo.__name__}), "
        f"docutils {version('docutils')} ({docutils.__name__})"
    )
