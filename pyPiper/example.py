import os

from pyPiper import Node, Pipeline
from tqdm import tqdm

import time
import random

class Generate(Node):
    def setup(self, size, reverse=False):
        self.size = size
        self.reverse = reverse
        self.pos = 0
        self.stateless = False

    def run(self, data):
        if self.pos < self.size:
            if self.reverse:
                res = self.size - self.pos - 1
            else:
                res = self.pos
            self.pos += 1

            self.emit(res)
        else:
            self.close()

class EvenOddGenerate(Node):
    def setup(self, size, reverse=False):
        self.size = size
        self.reverse = reverse
        self.pos = 0
        self.stateless = False

    def run(self, data):
        if self.pos < self.size:
            if self.reverse:
                res = self.size - self.pos - 1
            else:
                res = self.pos
            self.pos += 2

            self.emit([res, res+1])
        else:
            self.close()

class Square(Node):
    def run(self, data):
        self.emit(data**2)

class Double(Node):
    def run(self, data):
        self.emit(data*2)

class Sleep(Node):
    def run(self, data):
        time.sleep(random.randint(1,4))
        self.emit(data)

class Half(Node):
    def run(self, data):
        self.emit(data/2.0)

class Printer(Node):
    def setup(self):
        self.stateless = False
        self.batch_size = Node.BATCH_SIZE_ALL

    def run(self, data):

        print(data)


class TqdmUpdate(tqdm):
    def update(self, done, total_size=None):
        if total_size is not None:
            self.total = total_size
        self.n = done
        super().refresh()

if __name__ == '__main__':
    gen = Generate("gen", size=10000)
    double = Double("double")
    square = Square("square")
    printer1 = Printer("printer1", batch_size=1)
    printer2 = Printer("printer2", batch_size=1)
    sleeper = Sleep("sleep")
    sleeper1 = Sleep("sleep1")

    # p = Pipeline(gen | [sleeper, sleeper1], quiet=False, n_threads=50)
    # p.run()

    # p = Pipeline(gen | double | printer, n_threads=1)
    # p.run()

    # with TqdmUpdate(desc="Progress") as pbar:
    pbar=None
    p = Pipeline(gen | [double, square], n_threads=4, update_callback=pbar, quiet=False)
    p.run()
