"""
Parser for DeepSeek-R1 <think>...</think> tags in streaming output.

Handles tags split across chunk boundaries using a simple state machine.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import re


class ThinkTagParser:
    """Streaming parser that separates <think>...</think> content from response text."""

    NORMAL = "normal"
    THINKING = "thinking"

    OPEN_TAG = "<think>"
    CLOSE_TAG = "</think>"

    def __init__(self):
        self.state = self.NORMAL
        self.buffer = ""
        self.thinking_text = ""
        self.response_text = ""

    def feed(self, chunk: str) -> tuple[str, str]:
        """Process a streaming chunk. Returns (thinking_delta, response_delta)."""
        thinking_delta = ""
        response_delta = ""
        text = self.buffer + chunk
        self.buffer = ""

        i = 0
        while i < len(text):
            if self.state == self.NORMAL:
                lt_pos = text.find("<", i)
                if lt_pos == -1:
                    response_delta += text[i:]
                    i = len(text)
                else:
                    response_delta += text[i:lt_pos]
                    remaining = text[lt_pos:]
                    if remaining.startswith(self.OPEN_TAG):
                        self.state = self.THINKING
                        i = lt_pos + len(self.OPEN_TAG)
                    elif self.OPEN_TAG.startswith(remaining):
                        self.buffer = remaining
                        i = len(text)
                    else:
                        response_delta += "<"
                        i = lt_pos + 1

            elif self.state == self.THINKING:
                lt_pos = text.find("<", i)
                if lt_pos == -1:
                    thinking_delta += text[i:]
                    i = len(text)
                else:
                    thinking_delta += text[i:lt_pos]
                    remaining = text[lt_pos:]
                    if remaining.startswith(self.CLOSE_TAG):
                        self.state = self.NORMAL
                        i = lt_pos + len(self.CLOSE_TAG)
                    elif self.CLOSE_TAG.startswith(remaining):
                        self.buffer = remaining
                        i = len(text)
                    else:
                        thinking_delta += "<"
                        i = lt_pos + 1

        self.thinking_text += thinking_delta
        self.response_text += response_delta
        return thinking_delta, response_delta

    def finish(self) -> tuple[str, str]:
        """Flush remaining buffer when stream ends."""
        thinking_delta = ""
        response_delta = ""
        if self.buffer:
            if self.state == self.THINKING:
                thinking_delta = self.buffer
                self.thinking_text += thinking_delta
            else:
                response_delta = self.buffer
                self.response_text += response_delta
            self.buffer = ""
        return thinking_delta, response_delta

    @staticmethod
    def strip_think_tags(text: str) -> str:
        """Remove all <think>...</think> blocks from complete text."""
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    @staticmethod
    def extract_think_and_response(text: str) -> tuple[str, str]:
        """Split complete text into (thinking, response)."""
        thinking_parts = re.findall(r"<think>(.*?)</think>", text, flags=re.DOTALL)
        thinking = "\n".join(part.strip() for part in thinking_parts if part.strip())
        response = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        return thinking, response
