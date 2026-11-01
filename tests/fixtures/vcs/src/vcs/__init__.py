from importlib.metadata import version


def main() -> None:
    import dateutil
    import docutils
    import yoyo

    parts = [
        f"yoyo-migrations {version('yoyo-migrations')} ({yoyo.__name__})",
        f"docutils {version('docutils')} ({docutils.__name__})",
        f"python-dateutil {version('python-dateutil')} ({dateutil.__name__})",
    ]
    print(", ".join(parts))
