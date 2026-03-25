import logging
import os
from collections import deque


class LineLimitedFileHandler(logging.FileHandler):
    def __init__(
        self,
        filename,
        mode="a",
        encoding=None,
        delay=False,
        max_lines=2000,
        check_interval=50,
    ):
        self.max_lines = max(1, int(max_lines))
        self.check_interval = max(1, int(check_interval))
        self._records_since_trim = 0
        super().__init__(filename, mode=mode, encoding=encoding, delay=delay)
        self._trim_file(force=True)

    def emit(self, record):
        super().emit(record)
        self._records_since_trim += 1
        if self._records_since_trim >= self.check_interval:
            self._records_since_trim = 0
            self._trim_file(force=False)

    def _trim_file(self, force):
        self.acquire()
        try:
            if not self.baseFilename or not os.path.exists(self.baseFilename):
                return

            overflow = False
            tail = deque(maxlen=self.max_lines)
            with open(self.baseFilename, "r", encoding=self.encoding or "utf-8", errors="replace") as infile:
                for line in infile:
                    if len(tail) == self.max_lines:
                        overflow = True
                    tail.append(line)

            if not force and not overflow:
                return

            reopened = False
            if self.stream:
                self.stream.flush()
                self.stream.close()
                self.stream = None

            try:
                tmp_path = self.baseFilename + ".tmp"
                with open(tmp_path, "w", encoding=self.encoding or "utf-8") as outfile:
                    outfile.writelines(tail)
                os.replace(tmp_path, self.baseFilename)
            except PermissionError:
                return
            finally:
                if os.path.exists(self.baseFilename) and not self.delay:
                    self.stream = self._open()
                    reopened = True

            if not reopened and not self.delay:
                self.stream = self._open()
        finally:
            self.release()
