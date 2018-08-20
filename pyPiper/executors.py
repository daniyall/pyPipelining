from collections import deque
from abc import ABC, abstractmethod
from functools import reduce

from multiprocessing import Pool, Manager, Queue
from multiprocessing.pool import ApplyResult
from queue import Empty

def _filter_data_stream(node, next_node, parcels):
    to_push = []

    for parcel in parcels:
        data = parcel.data

        if next_node.in_streams == "*":
            to_push.append(data)
        else:
            if not isinstance(data, (list, tuple)):
                data = [data]

            if node.out_streams == "*":
                if len(data) != len(next_node.in_streams):
                    raise Exception(
                        "Node %s emits %i items, but next node (%s) expects %i" % (node, len(data), node, node.in_streams))
                to_push = data
            else:
                for k in next_node.in_streams:
                    to_push.append(data[node.out_streams.index(k)])

    if len(to_push) == 1:
        to_push = to_push[0]

    return to_push


class BaseExecutor(ABC):
    def __init__(self, graph, quiet=False, update_callback=None):
        self.graph = graph
        self.quiet = quiet
        self.update_callback = update_callback
        self.use_callback = False

    def print_buffer(self, buffer):
        if not self.quiet and buffer:
            for parcel in buffer:
                print(parcel.data)

    @staticmethod
    def get_key(node, successor):
        return "%s%s" % (node, successor)

    @abstractmethod
    def _run_root(self):
        pass

    @abstractmethod
    def _step(self):
        pass

    def is_finished(self):
        return self.graph.is_all_closed()

    def run(self):
        if self.update_callback is not None and self.graph._root.size is not None:
            self.use_callback = True
            self.total_size = self.graph._root.size

        while not self.is_finished():
            self._run_root()
            self._step()


class Executor(BaseExecutor):
    def __init__(self, graph, quiet=False, update_callback=None):
        super().__init__(graph, quiet, update_callback)

        self.queues = {}
        for node in graph._node_list:
            for successor in graph._graph[node]:
                self.queues[self.get_key(node, successor)] = deque()

    def send(self, node, successor, data):
        self.queues[self.get_key(node, successor)].append(data)

    def get_data_to_push(self, node, successor):
        queue = self.queues[self.get_key(node, successor)]

        if node._state != node.STATE_CLOSED:
            size = successor.batch_size
        else:
            size = len(queue)

        if len(queue) >= size:
            return [queue.popleft() for x in range(size)]

        return None

    def _run_root(self):
        root = self.graph._root

        root.state_transition()

        root._run(None)
        if self.use_callback:
            self.update_callback(1, self.total_size)


        for parcel in root._output_buffer:
            for successor in self.graph._graph[root]:
                self.send(root, successor, parcel)
        if len(self.graph._graph[root]) == 0:
            self.print_buffer(root._output_buffer)
        root._output_buffer.clear()


    def _step(self):
        for node in self.graph:
            node.state_transition()
            successors = self.graph._graph[node]

            for successor in successors:
                data = self.get_data_to_push(node, successor)

                if data:
                    data = _filter_data_stream(node, successor, data)
                    successor._run(data)

                for d in successor._output_buffer:
                    super_successors = self.graph._graph[successor]
                    for ss in super_successors:
                        self.send(successor, ss, d)

                    if len(super_successors) == 0:
                        self.print_buffer(successor._output_buffer)
                    successor._output_buffer.clear()


                if node._state != node.STATE_RUNNING:
                    successor.close()


class ParallelExecutor(BaseExecutor):
    def __init__(self, graph, n_threads, quiet=False, update_callback=None):
        super().__init__(graph, quiet, update_callback)

        self.n_threads = n_threads
        self.pool = Pool(processes=n_threads)

        root = self.graph._root
        self.queues = []
        self.executors = []

        self.results = [None for i in range(n_threads)]

        for i in range(n_threads):
            self.queues.append({})
            self.executors.append(Executor(graph, quiet))

            for successor in self.graph._graph[root]:
                self.queues[i][self.get_key(root, successor)] = deque()

    def _run_root(self):
        root = self.graph._root

        if root._state == root.STATE_RUNNING:
            for i in range(self.n_threads):
                root._run(None)
                if self.use_callback:
                    self.update_callback(1, self.total_size)
        else:
            root.state_transition()

        thread = 0
        for parcel in root._output_buffer:
            for successor in self.graph._graph[root]:
                self.queues[thread][self.get_key(root, successor)].append(parcel)
            thread += 1

        if len(self.graph._graph[root]) == 0:
            self.print_buffer(root._output_buffer)
        root._output_buffer.clear()

    def is_finished(self):
        return reduce(lambda x,y: x and y, [x.is_finished() for x in self.executors])

    def _step(self):
        for i in range(self.n_threads):
            if isinstance(self.results[i], ApplyResult):
                if self.results[i].ready():
                    self.executors[i].graph = self.results[i].get()
                else:
                    continue

            # print([(i, node, node._state) for node in self.executors[i].graph._node_list])

            root = self.executors[i].graph._root
            self.executors[i].graph._root._state = self.graph._root._state

            queues = self.queues[i]
            args = []
            for q_key in queues:
                q = queues[q_key]
                for successor in self.graph._graph[root]:
                    if len(q) > 0:
                        parcel = q.popleft()
                        args.append((root, successor, parcel))

            r = self.pool.apply_async(_single_step, (self.executors[i], args), error_callback=error_func)
            self.results[i] = r

    def run(self):
        super().run()
        self.pool.close()
        self.pool.join()

def _single_step(executor, args):
    for root, successor, parcel in args:
        executor.send(root, successor, parcel)

    executor._step()

    return executor.graph

def error_func(value):
    print(type(value), value)
    raise value