import hashlib
import json
import sys

# import bencodepy - available if you need it!
# import requests - available if you need it!

# Examples:
#
# - decode_bencode(b"5:hello") -> b"hello"
# - decode_bencode(b"10:hello12345") -> b"hello12345"
def decode_bencode(bencoded_value):
    value, _ = _decode_bencode(bencoded_value, 0)
    return value


def _decode_bencode(data, index):
    if chr(data[index]).isdigit():
        # string: <length>:<bytes>
        colon_index = data.find(b":", index)
        if colon_index == -1:
            raise ValueError("Invalid encoded value")
        length = int(data[index:colon_index])
        start = colon_index + 1
        end = start + length
        return data[start:end], end
    elif data[index:index+1] == b"i":
        # integer: i<number>e
        end_index = data.find(b"e", index)
        if end_index == -1:
            raise ValueError("Invalid encoded value")
        return int(data[index+1:end_index]), end_index + 1
    elif data[index:index+1] == b"l":
        # list: l<bencoded_elements>e
        index += 1
        result = []
        while data[index:index+1] != b"e":
            value, index = _decode_bencode(data, index)
            result.append(value)
        return result, index + 1
    elif data[index:index+1] == b"d":
        # dictionary: d<key1><value1>...<keyN><valueN>e
        index += 1
        result = {}
        while data[index:index+1] != b"e":
            key, index = _decode_bencode(data, index)
            if not isinstance(key, bytes):
                raise ValueError("Dictionary keys must be strings")
            value, index = _decode_bencode(data, index)
            result[key] = value
        return result, index + 1
    else:
        raise NotImplementedError("Only strings, integers, lists, and dictionaries are supported at the moment")


def bencode(value):
    if isinstance(value, bytes):
        return str(len(value)).encode() + b":" + value
    elif isinstance(value, int):
        return b"i" + str(value).encode() + b"e"
    elif isinstance(value, list):
        return b"l" + b"".join(bencode(item) for item in value) + b"e"
    elif isinstance(value, dict):
        result = b"d"
        for key, val in value.items():
            result += bencode(key) + bencode(val)
        return result + b"e"
    else:
        raise TypeError(f"Type not serializable: {type(value)}")


def main():
    command = sys.argv[1]

    # You can use print statements as follows for debugging, they'll be visible when running tests.
    print("Logs from your program will appear here!", file=sys.stderr)

    if command == "decode":
        bencoded_value = sys.argv[2].encode()

        # json.dumps() can't handle bytes, but bencoded "strings" need to be
        # bytestrings since they might contain non utf-8 characters.
        #
        # Let's convert them to strings for printing to the console.
        # This is recursive so dict keys (which json.dumps won't pass to
        # `default`) and nested structures are handled too.
        def bytes_to_str(data):
            if isinstance(data, bytes):
                return data.decode()
            if isinstance(data, dict):
                return {bytes_to_str(k): bytes_to_str(v) for k, v in data.items()}
            if isinstance(data, list):
                return [bytes_to_str(item) for item in data]
            if isinstance(data, (int, float, bool)) or data is None:
                return data

            raise TypeError(f"Type not serializable: {type(data)}")

        print(json.dumps(bytes_to_str(decode_bencode(bencoded_value))))
    elif command == "info":
        with open(sys.argv[2], "rb") as f:
            torrent_data = f.read()

        decoded = decode_bencode(torrent_data)
        print(f"Tracker URL: {decoded[b'announce'].decode()}")
        print(f"Length: {decoded[b'info'][b'length']}")
        info_hash = hashlib.sha1(bencode(decoded[b'info'])).hexdigest()
        print(f"Info Hash: {info_hash}")
        print(f"Piece Length: {decoded[b'info'][b'piece length']}")
        print("Piece Hashes:")
        pieces = decoded[b'info'][b'pieces']
        for i in range(0, len(pieces), 20):
            print(pieces[i:i+20].hex())
    else:
        raise NotImplementedError(f"Unknown command {command}")


if __name__ == "__main__":
    main()
