from importlib.metadata import version


def main() -> None:
    import yoyo

    print(f"yoyo-migrations {version('yoyo-migrations')} ({yoyo.__name__})")
