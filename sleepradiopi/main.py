"""Entry point. Currently a placeholder -- wires nothing up yet.

See docs/ROADMAP.md for build order: audio-out smoke test comes first,
before this ties the modules together into a running appliance.
"""

from sleepradiopi.io.display import NullDisplay


def main() -> None:
    display = NullDisplay()
    display.show_status("SleepRadioPi", "not yet implemented")


if __name__ == "__main__":
    main()
