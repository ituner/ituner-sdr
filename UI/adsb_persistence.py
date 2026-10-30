"""RAM-buffered flight logs with periodic, incremental persistence."""
import logging
import time
from logging.handlers import RotatingFileHandler

PERSIST_SECONDS=300


class BufferedFlightHandler(logging.Handler):
    def __init__(self,path,size,backups):
        super().__init__()
        self.destination=RotatingFileHandler(path,maxBytes=size,backupCount=backups,delay=True)
        self.pending=[];self.next_flush=time.monotonic()+PERSIST_SECONDS

    def emit(self,record):
        self.pending.append(record)

    def flush_if_due(self):
        if time.monotonic()>=self.next_flush:self.flush()

    def pending_lines(self,limit=160):
        self.acquire()
        try:return [record.getMessage() for record in self.pending[-limit:]]
        finally:self.release()

    def read_log(self):
        self.acquire()
        try:
            try:
                with open(self.destination.baseFilename,'rb') as stream:data=stream.read()
            except FileNotFoundError:data=b''
            return data+''.join(record.getMessage()+'\n' for record in self.pending).encode()
        finally:self.release()

    def flush(self):
        self.acquire()
        try:
            if not getattr(self,'pending',None):return
            self.destination.setFormatter(self.formatter)
            for record in self.pending:self.destination.handle(record)
            self.destination.flush();self.pending.clear()
            self.next_flush=time.monotonic()+PERSIST_SECONDS
        finally:self.release()

    def close(self):
        self.flush()
        if hasattr(self,'destination'):self.destination.close()
        super().close()
