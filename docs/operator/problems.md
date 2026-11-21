---
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
title: Common problems
eyebrow: When something goes wrong
columns: [You see, Do]
---

## “library folder not reachable”

The library folder or the NAS is not reachable. Check it, wait a minute, run `partitor` again. See `STORAGE-SMB.md`.

## The wizard stopped (<kbd>q</kbd>, lost connection)

The item is kept. Open it from the menu and continue; <kbd>r</kbd> asks what is still open.

## A part is missing on some lines

Check the red systems on the proof; correct with <kbd>t</kbd> or analyse again with <kbd>y</kbd>.

## A page shows two systems (for example 4 and 13 staves) where the score has one

Answer <kbd>j</kbd> in the choices, or `partitor analyse ID --join p5:4`. The bar numbers of that page are then counted once.

## Bar numbers are off from some line on

<kbd>n</kbd>, then `f N=B` for the first wrong line.

## A part rests for whole systems

Normal: those bars become one rest line with the count (for example 14), so the numbers continue.
