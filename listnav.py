"""Vim-style cursor movement for selectable lists."""

STEPS = {"j": 1, "KEY_DOWN": 1, "k": -1, "KEY_UP": -1}
HALF_PAGES = {"\x04": 1, "\x15": -1}
PAGES = {"\x06": 1, "KEY_NPAGE": 1, "\x02": -1, "KEY_PPAGE": -1}


class ListNavigation:
    def __init__(self):
        self.count = ""
        self.pending_g = False
        self.back = []
        self.forward = []

    def move(self, key, index, size, page):
        """Return a row index for navigation keys, or None for other actions."""
        if len(key) == 1 and key in "0123456789":
            self.count = (self.count + key)[:6]
            return index
        count = int(self.count or 1)
        numbered = bool(self.count)
        self.count = ""
        pending_g = self.pending_g
        self.pending_g = key == "g" and not pending_g

        if key == "g" and not pending_g:
            self.count = str(count) if numbered else ""
            return index
        if key in ("u", "\x12"):
            source, target = (
                (self.back, self.forward) if key == "u" else (self.forward, self.back)
            )
            for _ in range(min(count, len(source))):
                target.append(index)
                index = source.pop()
            return index
        if key in ("g", "G"):
            destination = count - 1 if numbered else (0 if key == "g" else size - 1)
        elif key in STEPS:
            destination = index + count * STEPS[key]
        elif key in HALF_PAGES:
            destination = index + count * max(1, page // 2) * HALF_PAGES[key]
        elif key in PAGES:
            destination = index + count * max(1, page) * PAGES[key]
        else:
            return None

        destination = max(0, min(size - 1, destination))
        if destination != index:
            self.back.append(index)
            self.forward.clear()
        return destination
