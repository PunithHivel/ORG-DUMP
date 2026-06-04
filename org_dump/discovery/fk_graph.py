from collections import deque
from dataclasses import dataclass
from org_dump.discovery.schema_inspector import ForeignKey


@dataclass
class JoinStep:
    from_table: str
    from_col: str
    to_table: str
    to_col: str


class FKGraph:
    def __init__(self, foreign_keys: list[ForeignKey]):
        # forward[table] = [(from_col, to_table, to_col), ...]
        self.forward: dict[str, list[tuple[str, str, str]]] = {}
        # reverse[table] = [(from_table, from_col, to_col), ...]
        self.reverse: dict[str, list[tuple[str, str, str]]] = {}

        for fk in foreign_keys:
            self.forward.setdefault(fk.from_table, []).append(
                (fk.from_col, fk.to_table, fk.to_col)
            )
            self.reverse.setdefault(fk.to_table, []).append(
                (fk.from_table, fk.from_col, fk.to_col)
            )

    def find_shortest_path(self, start: str, targets: set[str]) -> list[JoinStep] | None:
        """BFS from start following forward FK edges to any table in targets.
        Returns the list of JoinSteps representing the path, or None if unreachable."""
        if start in targets:
            return []

        # BFS: queue holds (current_table, path_so_far)
        queue: deque[tuple[str, list[JoinStep]]] = deque()
        queue.append((start, []))
        visited = {start}

        while queue:
            current, path = queue.popleft()
            for from_col, to_table, to_col in self.forward.get(current, []):
                if to_table in visited:
                    continue
                visited.add(to_table)
                new_path = path + [JoinStep(
                    from_table=current,
                    from_col=from_col,
                    to_table=to_table,
                    to_col=to_col,
                )]
                if to_table in targets:
                    return new_path
                queue.append((to_table, new_path))

        return None

    def all_paths_to_targets(self, start: str, targets: set[str]) -> list[list[JoinStep]]:
        """Returns all distinct shortest-length paths from start to any target."""
        if start in targets:
            return [[]]

        found: list[list[JoinStep]] = []
        min_len = None
        queue: deque[tuple[str, list[JoinStep]]] = deque()
        queue.append((start, []))
        visited: dict[str, int] = {start: 0}

        while queue:
            current, path = queue.popleft()
            if min_len is not None and len(path) >= min_len:
                continue
            for from_col, to_table, to_col in self.forward.get(current, []):
                new_len = len(path) + 1
                if to_table in visited and visited[to_table] < new_len:
                    continue
                visited[to_table] = new_len
                new_path = path + [JoinStep(
                    from_table=current,
                    from_col=from_col,
                    to_table=to_table,
                    to_col=to_col,
                )]
                if to_table in targets:
                    min_len = new_len
                    found.append(new_path)
                else:
                    queue.append((to_table, new_path))

        return found

    def topological_sort(self, tables: list[str]) -> list[str]:
        """Kahn's algorithm. Tables not in the graph are appended last."""
        table_set = set(tables)
        in_degree: dict[str, int] = {t: 0 for t in tables}

        for table in tables:
            for _, to_table, _ in self.forward.get(table, []):
                if to_table in table_set:
                    in_degree[to_table] = in_degree.get(to_table, 0) + 1

        queue = deque(t for t in tables if in_degree[t] == 0)
        result = []
        while queue:
            node = queue.popleft()
            result.append(node)
            for _, to_table, _ in self.forward.get(node, []):
                if to_table in table_set:
                    in_degree[to_table] -= 1
                    if in_degree[to_table] == 0:
                        queue.append(to_table)

        # any remaining tables (cycles) appended at end
        remaining = [t for t in tables if t not in set(result)]
        result.extend(remaining)
        return result
