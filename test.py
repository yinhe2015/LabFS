from 主程序 import 文件系统

索引路径 = '/Volumes/RAMDisk/index.json'
设备路径 = '/dev/disk4s1'

with 文件系统(索引路径, 设备路径) as fs:
    fs.创建文件('test.txt')
    fs.写入文件('test.txt', 'hello world')