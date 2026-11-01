import docopt
import idna
import localpkg
import six


def main() -> None:
    parts = [
        f"six {six.__version__}",
        f"idna {idna.__version__}",
        f"docopt {docopt.__version__}",
        localpkg.name(),
    ]
    print(", ".join(parts))
