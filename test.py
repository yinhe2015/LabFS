from 主程序 import 文件系统
import os

索引路径 = '/Volumes/RAMDisk/index.json'
设备路径 = '/dev/disk4s1'

fpath = '/Users/yhm/Downloads/1EB GDDR9 9090 Ti Super.png'

with 文件系统(索引路径, 设备路径) as fs:
    fs.创建文件(os.path.basename(fpath))
    with open(fpath, 'rb') as f:
        fs.文件_写入(os.path.basename(fpath), 0, f.read())

    print(fs.列出文件())