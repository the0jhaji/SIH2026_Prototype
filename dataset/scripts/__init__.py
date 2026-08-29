"""dataset — local capture tooling for building the BAS-AI custom dataset.

Everything is stored locally and never uploaded. Structure:

    raw/          untouched recording sessions (one directory per take)
    frames/       organized/curated frames for training (populated later)
    annotations/  label files for training (populated later)
    scripts/      recorder + shared logic
"""