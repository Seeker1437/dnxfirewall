from typing import Union

def iptoi(ipa: str) -> int: ...
def itoip(ipa: int) -> str: ...
def calc_checksum(data: Union[bytes, bytearray, memoryview], pack: bool) -> Union[bytes, int]: ...
