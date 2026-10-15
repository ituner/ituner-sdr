# Bundled fonts

These are unmodified font files supplied for the Python UI. Each family keeps
its original license in its own directory.

| Family | Files | UI use |
| --- | --- | --- |
| Oxanium | Variable font | Frequency readout; already bundled |
| Roboto | Regular, Bold | First choice for shared button text |
| Liberation Sans | Regular, Bold | Labels across the radio UI |
| Liberation Mono | Regular, Bold | Receiver and decoder data screens |
| Liberation Serif | Regular, Bold | Optional Font Lab frequency face |
| DejaVu Sans | Regular, Bold | Shared button fallback and other text |

Roboto comes from the Roboto distribution (`OFL.txt`). Liberation Sans, Mono,
and Serif come from Liberation Fonts 2.1.5 (`LICENSE`). DejaVu Sans comes
from the DejaVu Sans distribution (`LICENSE.txt`).

Adding these files does not change the current font selection: the Python UI
still resolves these families through Pygame's system-font lookup. Oxanium is
installed separately by the CM5 installer. This preserves the current CM5
appearance while making the supplied files available in the repository.
