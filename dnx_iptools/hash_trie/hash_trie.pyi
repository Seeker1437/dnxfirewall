
class HashTrie_Range:
    def py_search(self, host: tuple[int, int]) -> int: ...
    def generate_structure(self, py_trie: list, py_trie_len: int) -> None: ...

class HashTrie_Value:
    def py_search(self, trie_key: int) -> int: ...
    def generate_structure(self, py_trie: list, py_trie_len: int) -> None: ...
