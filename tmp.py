from 打开分区 import 打开分区

if __name__ == "__main__":
    dev = "/dev/disk4s1"

    with 打开分区(dev, enable_cache=False) as f:
        f.seek(0)
        buf = f.read(64)
        print(buf.hex())
        f.seek(100)
        f.write(b"test123")
        f.flush()