"""Run the supported Flight Data Recorder command from a source checkout.

For installed use, invoke ``xpwebapi-fdr`` directly. This thin example keeps
the same command-line interface while demonstrating the public subpackage.
"""

import xpwebapi.fdr  # noqa: F401 - make the public subpackage explicit in this example.
from xpwebapi.fdr.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
