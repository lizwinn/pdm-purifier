import docopt
import idna
import localpkg
import six
import xxhash


def main() -> None:
    parts = [
        f"six {six.__version__}",
        f"idna {idna.__version__}",
        f"docopt {docopt.__version__}",
        f"xxh64 {xxhash.xxh64_hexdigest(b'pdm-purifier')}",
        localpkg.name(),
    ]
    print(", ".join(parts))
