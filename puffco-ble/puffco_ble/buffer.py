"""Node.js-compatible byte buffer helpers for Lorax framing."""


class Buffer:
    def __init__(self, init_value: int | bytes | bytearray):
        if isinstance(init_value, int):
            self.data = bytearray(init_value)
            self.size = init_value
        else:
            self.data = bytearray(init_value)
            self.size = len(self.data)
        self.encoding = "utf-8"

    def readUInt8(self, pos: int) -> int:
        return self.readUIntLE(pos, 1)

    def readUInt16LE(self, pos: int) -> int:
        return self.readUIntLE(pos, 2)

    def readUIntLE(self, pos: int, byte_len: int = 1) -> int:
        return int.from_bytes(self.data[pos : pos + byte_len], byteorder="little")

    def writeUInt8(self, int_value: int, pos: int) -> int:
        return self.writeUIntLE(int_value, pos, 1)

    def writeUInt16LE(self, int_value: int, pos: int) -> int:
        return self.writeUIntLE(int_value, pos, 2)

    def writeUIntLE(self, int_value: int, pos: int, byte_len: int) -> int:
        if int_value is None:
            int_value = 0
        self.data[pos : pos + byte_len] = int_value.to_bytes(byte_len, "little")
        return pos + byte_len
