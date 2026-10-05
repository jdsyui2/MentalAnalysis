import re
import unicodedata


class CommentCleaner:
    def __init__(self, min_clean_length=None):
        # Compatibility argument: length no longer determines semantic validity.
        self.emoji_pattern = re.compile(r"\[[\u4e00-\u9fffA-Za-z0-9]+\]")

    def clean_text(self, text):
        return re.sub(
            r"\s+",
            " ",
            self.emoji_pattern.sub("", unicodedata.normalize("NFKC", text or "")),
        ).strip()

    def process(self, item):
        cleaned = self.clean_text(item.get("comment", ""))
        if not any(c.isalnum() for c in cleaned):
            return None
        return dict(
            item,
            cleaned_comment=cleaned,
            raw_length=len(item.get("comment", "")),
            clean_length=len(cleaned),
        )
