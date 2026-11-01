"""Usage: simple <name>"""

import attrs
import docopt


@attrs.define
class Greeting:
    name: str

    def text(self) -> str:
        return f"Hello, {self.name}, from simple"


def main() -> None:
    arguments = docopt.docopt(__doc__)
    print(Greeting(arguments["<name>"]).text())
