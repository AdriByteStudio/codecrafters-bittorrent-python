import hashlib
import json
import os
import socket
import sys
from urllib.parse import quote_from_bytes

import requests

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


def recv_exact(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("Connection closed")
        data += chunk
    return data


def recv_message(sock):
    length = int.from_bytes(recv_exact(sock, 4), "big")
    if length == 0:
        return None  # keep-alive
    payload = recv_exact(sock, length)
    return payload[0], payload[1:]


def download_piece_from_peer(host, port, info_hash, piece_index, piece_length):
    BLOCK_SIZE = 16 * 1024

    handshake = (
        b"\x13"  # length of protocol string (19)
        + b"BitTorrent protocol"
        + b"\x00" * 8  # reserved bytes
        + info_hash
        + os.urandom(20)  # peer id
    )

    with socket.create_connection((host, port), timeout=10) as sock:
        sock.sendall(handshake)
        recv_exact(sock, 68)  # handshake response

        # Wait for bitfield message (id 5), ignore payload
        while True:
            msg = recv_message(sock)
            if msg is None:
                continue
            msg_id, _ = msg
            if msg_id == 5:
                break

        # Send interested message (id 2)
        sock.sendall(b"\x00\x00\x00\x01\x02")

        # Wait for unchoke message (id 1)
        while True:
            msg = recv_message(sock)
            if msg is None:
                continue
            msg_id, _ = msg
            if msg_id == 1:
                break

        # Send request messages (id 6) for all blocks (pipelined)
        num_blocks = (piece_length + BLOCK_SIZE - 1) // BLOCK_SIZE
        for block_index in range(num_blocks):
            begin = block_index * BLOCK_SIZE
            block_len = min(BLOCK_SIZE, piece_length - begin)
            request = (
                b"\x00\x00\x00\x0d"  # message length = 13
                + b"\x06"  # request id
                + piece_index.to_bytes(4, "big")
                + begin.to_bytes(4, "big")
                + block_len.to_bytes(4, "big")
            )
            sock.sendall(request)

        # Read piece messages (id 7) until all blocks received
        blocks = {}
        while len(blocks) < num_blocks:
            msg = recv_message(sock)
            if msg is None:
                continue
            msg_id, payload = msg
            if msg_id == 7:
                begin = int.from_bytes(payload[4:8], "big")
                blocks[begin] = payload[8:]

    return b"".join(blocks[begin] for begin in sorted(blocks))


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
    elif command == "peers":
        with open(sys.argv[2], "rb") as f:
            torrent_data = f.read()

        decoded = decode_bencode(torrent_data)
        tracker_url = decoded[b'announce'].decode()
        info_hash = hashlib.sha1(bencode(decoded[b'info'])).digest()
        length = decoded[b'info'][b'length']

        url = (
            f"{tracker_url}?info_hash={quote_from_bytes(info_hash, safe='')}"
            f"&peer_id={quote_from_bytes(os.urandom(20), safe='')}"
            f"&port=6881&uploaded=0&downloaded=0&left={length}&compact=1"
        )
        response = requests.get(url)
        response.raise_for_status()

        tracker_response = decode_bencode(response.content)
        peers = tracker_response[b'peers']
        for i in range(0, len(peers), 6):
            ip = ".".join(str(b) for b in peers[i:i+4])
            port = int.from_bytes(peers[i+4:i+6], "big")
            print(f"{ip}:{port}")
    elif command == "handshake":
        with open(sys.argv[2], "rb") as f:
            torrent_data = f.read()

        decoded = decode_bencode(torrent_data)
        info_hash = hashlib.sha1(bencode(decoded[b'info'])).digest()

        host, port = sys.argv[3].rsplit(":", 1)
        port = int(port)

        handshake = (
            b"\x13"  # length of protocol string (19)
            + b"BitTorrent protocol"
            + b"\x00" * 8  # reserved bytes
            + info_hash
            + os.urandom(20)  # peer id
        )

        with socket.create_connection((host, port), timeout=10) as sock:
            sock.sendall(handshake)
            response = b""
            while len(response) < 68:
                chunk = sock.recv(68 - len(response))
                if not chunk:
                    break
                response += chunk

        received_peer_id = response[48:68]
        print(f"Peer ID: {received_peer_id.hex()}")
    elif command == "download_piece":
        output_path = sys.argv[3]
        torrent_file = sys.argv[4]
        piece_index = int(sys.argv[5])

        with open(torrent_file, "rb") as f:
            torrent_data = f.read()

        decoded = decode_bencode(torrent_data)
        info = decoded[b'info']
        info_hash = hashlib.sha1(bencode(info)).digest()
        tracker_url = decoded[b'announce'].decode()
        length = info[b'length']
        piece_length = info[b'piece length']
        pieces = info[b'pieces']

        # Get peers from the tracker
        url = (
            f"{tracker_url}?info_hash={quote_from_bytes(info_hash, safe='')}"
            f"&peer_id={quote_from_bytes(os.urandom(20), safe='')}"
            f"&port=6881&uploaded=0&downloaded=0&left={length}&compact=1"
        )
        response = requests.get(url)
        response.raise_for_status()
        tracker_response = decode_bencode(response.content)
        peers = tracker_response[b'peers']

        # This piece's length (the last piece may be shorter)
        num_pieces = len(pieces) // 20
        if piece_index == num_pieces - 1:
            this_piece_length = length - piece_index * piece_length
        else:
            this_piece_length = piece_length

        # Try each peer until one succeeds
        piece_data = None
        for i in range(0, len(peers), 6):
            host = ".".join(str(b) for b in peers[i:i+4])
            port = int.from_bytes(peers[i+4:i+6], "big")
            try:
                piece_data = download_piece_from_peer(
                    host, port, info_hash, piece_index, this_piece_length
                )
                break
            except Exception:
                continue

        if piece_data is None:
            raise RuntimeError("Failed to download piece from all peers")

        # Verify the piece hash
        expected_hash = pieces[piece_index*20:(piece_index+1)*20]
        if hashlib.sha1(piece_data).digest() != expected_hash:
            raise ValueError("Piece hash mismatch")

        with open(output_path, "wb") as f:
            f.write(piece_data)

        print(f"Piece {piece_index} downloaded to {output_path}")
    elif command == "download":
        output_path = sys.argv[3]
        torrent_file = sys.argv[4]

        with open(torrent_file, "rb") as f:
            torrent_data = f.read()

        decoded = decode_bencode(torrent_data)
        info = decoded[b'info']
        info_hash = hashlib.sha1(bencode(info)).digest()
        tracker_url = decoded[b'announce'].decode()
        length = info[b'length']
        piece_length = info[b'piece length']
        pieces = info[b'pieces']

        # Get peers from the tracker
        url = (
            f"{tracker_url}?info_hash={quote_from_bytes(info_hash, safe='')}"
            f"&peer_id={quote_from_bytes(os.urandom(20), safe='')}"
            f"&port=6881&uploaded=0&downloaded=0&left={length}&compact=1"
        )
        response = requests.get(url)
        response.raise_for_status()
        tracker_response = decode_bencode(response.content)
        peers = tracker_response[b'peers']

        peer_list = []
        for i in range(0, len(peers), 6):
            host = ".".join(str(b) for b in peers[i:i+4])
            port = int.from_bytes(peers[i+4:i+6], "big")
            peer_list.append((host, port))

        num_pieces = len(pieces) // 20

        file_data = b""
        for piece_index in range(num_pieces):
            if piece_index == num_pieces - 1:
                this_piece_length = length - piece_index * piece_length
            else:
                this_piece_length = piece_length

            # Try each peer until one succeeds
            piece_data = None
            for host, port in peer_list:
                try:
                    piece_data = download_piece_from_peer(
                        host, port, info_hash, piece_index, this_piece_length
                    )
                    break
                except Exception:
                    continue

            if piece_data is None:
                raise RuntimeError(f"Failed to download piece {piece_index}")

            # Verify the piece hash
            expected_hash = pieces[piece_index*20:(piece_index+1)*20]
            if hashlib.sha1(piece_data).digest() != expected_hash:
                raise ValueError(f"Piece {piece_index} hash mismatch")

            file_data += piece_data

        with open(output_path, "wb") as f:
            f.write(file_data)

        print(f"Downloaded {torrent_file} to {output_path}")
    else:
        raise NotImplementedError(f"Unknown command {command}")


if __name__ == "__main__":
    main()
