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
    else:
        raise NotImplementedError("Only strings, integers, and lists are supported at the moment")


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
        def bytes_to_str(data):
            if isinstance(data, bytes):
                return data.decode()

            raise TypeError(f"Type not serializable: {type(data)}")

        print(json.dumps(decode_bencode(bencoded_value), default=bytes_to_str))
    else:
        raise NotImplementedError(f"Unknown command {command}")


if __name__ == "__main__":
    main()
