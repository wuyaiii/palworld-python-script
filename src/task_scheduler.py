#!/usr/bin/env python
# -*- encoding: utf-8 -*-


import codecs
import os
import re
import subprocess
import sys
import threading
import time
import zipfile

import psutil
import urllib.request
import urllib.error

from src import read_conf
from src.utils.log_control import INFO
from rcon.source import Client
from rcon.source.proto import Packet
from rcon.exceptions import WrongPassword


class TaskScheduler:
    def __init__(self):
        self.conf = read_conf.read_config()
        self.appName = 'PalServer-Win64-Test-Cmd.exe'
        self.main_dir = self.conf['main_directory']
        self.palworldsetting_dir = os.path.join(self.main_dir, 'Pal\\Saved\\Config\\WindowsServer')
        self.program_path = os.path.join(self.main_dir, 'PalServer.exe')
        self.palinject_dir = os.path.join(self.main_dir, 'Pal\\Binaries\\Win64')
        self.palinject_path = os.path.join(self.palinject_dir, 'PalServerInject.exe')
        self.appName_path = os.path.join(self.palinject_dir, 'PalServer-Win64-Test-Cmd.exe')
        self.rcon_enabled = self.conf['rcon_enabled']
        self.host = self.conf['rcon_host']
        self.port = self.conf['rcon_port']
        self.passwd = self.conf['rcon_password']
        self.rcon_command = self.conf['rcon_command']
        self.restart_interval = self.conf['restart_interval']
        self.shutdown_notice = self.conf['shutdown_notices']
        self.shutdown_notice_cn = self.conf['shutdown_notices_cn']
        self.memory_monitor_enabled = self.conf['memory_monitor_enabled']
        self.polling_interval_seconds = self.conf['polling_interval_seconds']
        self.memory_usage_threshold = self.conf['memory_usage_threshold']
        self.daemon_time = self.conf['daemon_time']
        self.announcement_enabled = self.conf['announcement_enabled']
        self.announcement_time = self.conf['announcement_time']
        self.announcement_messages = self.conf['announcement_messages']
        self.arguments = self.conf.get('arguments', '').split()
        self.palinject_enabled = self.conf['palinject_enabled']
        self.use_multicore_options= self.conf['use_multicore_options']
        self.is_first_run = True
        self.is_restarting = False
        self.current_announcement_index = 0
        self.script_dir = os.path.dirname(sys.argv[0])
        self.zip_file_path = os.path.join(self.script_dir, "UE4SS-PalServerInject.zip")
        self.files_to_override = ["pal-plugin-loader.dll", "PalServerInject.exe", "UE4SS.dll", "palinject_version.txt"]

    # 修改rcon源代码，忽略SessionTimeout异常
    def patched_run(self, command: str, *args: str, encoding: str = "utf-8") -> str:
        """Patched run method that ignores SessionTimeout exceptions."""
        request = Packet.make_command(command, *args, encoding=encoding)
        response = self.communicate(request)

        return response.payload.decode(encoding)

    # Apply the monkey patch
    Client.run = patched_run

    def send_rcon_command(self, command):
        try:
            with Client(
                host=self.host,
                port=self.port,
                passwd=self.passwd,
                timeout=1) as client:
                response = client.run(command)
            return True, response

        except TimeoutError:
            return False, "连接超时，请检查服务端"
        except ConnectionResetError:
            return False, "远程主机强迫关闭了一个现有的连接，请重连RCON"
        except:
            return False, "未知错误"

    def check_rcon(self):
        while True:
            try:
                with Client(
                        host=self.host,
                        port=self.port,
                        passwd=self.passwd,
                        timeout=1):
                    INFO.logger.info("[ RCON ] RCON连接正常")
                    print("\r[ RCON ] RCON连接正常\n", end='', flush=True)
                    time.sleep(1)
                    return True

            except TimeoutError:
                INFO.logger.error("[ RCON ] 正在检测RCON连接，请不要关闭......")
                print("[ RCON ] 正在检测RCON连接，请不要关闭......")
                if self.is_first_run:
                    time.sleep(1)
                else:
                    return False
            except WrongPassword:
                INFO.logger.error("[ RCON ] RCON密码错误，请检查相关设置")
                print("[ RCON ] RCON密码错误，请检查相关设置")
                time.sleep(2)
                self.close_process()
                sys.exit(0)

    # 读取PalWorldSettings.ini中的ServerName
    def read_server_name(self):
        settings_file_path = os.path.join(self.palworldsetting_dir, 'PalWorldSettings.ini')
        server_name = "PalServer"  # 默认标题
        try:
            with open(settings_file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if 'ServerName=' in line:
                        # 使用正则表达式匹配 ServerName 后的内容，直到遇到双引号为止
                        match = re.search(r'ServerName="([^"]*)"', line)
                        if match:
                            server_name = match.group(1)  # 提取 ServerName
                        break
        except FileNotFoundError:
            INFO.logger.error(f"[ 配置读取 ] 找不到文件 {settings_file_path}")
            print(f"[ 配置读取 ] 找不到文件 {settings_file_path}")
        except Exception as e:
            INFO.logger.error(f"[ 配置读取 ] 读取 ServerName 出错: {e}")
            print(f"[ 配置读取 ] 读取 ServerName 出错: {e}")
        return server_name

    # 进程检查并判断路径
    def is_palserver_running(self):
        INFO.logger.info("[ 配置读取 ] 当前配置文件指定路径为" + self.appName_path)
        matching_processes = []
        for proc in psutil.process_iter(['name', 'exe']):
            try:
                if self.appName.lower() in proc.info['name'].lower():
                    proc_path = proc.info['exe'] if proc.info['exe'] else ''
                    INFO.logger.info(f"检查到{proc.info['name']}进程 - 当前路径为：{proc_path}")
                    matching_processes.append(proc_path)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        for path in matching_processes:
            if os.path.normpath(self.appName_path) == os.path.normpath(path):
                return True
        return False

    # 关闭路径匹配成功的进程
    def close_process(self):
        for proc in psutil.process_iter(['name', 'exe']):
            try:
                if self.appName.lower() in proc.info['name'].lower():
                    if os.path.normpath(self.appName_path) == os.path.normpath(proc.info['exe']):
                        proc.kill()
                        print(f"[ 进程关闭 ] 已关闭位于{proc.info['exe']} 的 {self.appName}")
                        return
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

    # 解压文件
    def unzip_files(self):
        try:
            with zipfile.ZipFile(self.zip_file_path, 'r') as zip_ref:
                for member in zip_ref.namelist():
                    target_path = os.path.join(self.palinject_dir, member)
                    # 如果文件在 files_to_override 列表中，则直接覆盖
                    if any(member.endswith(pf) for pf in self.files_to_override):
                        zip_ref.extract(member, self.palinject_dir)
                    else:
                        if not os.path.exists(target_path):
                            zip_ref.extract(member, self.palinject_dir)
            time.sleep(5)
            settings_file_path = os.path.join(self.palinject_dir, "UE4SS-settings.ini")
            self.modify_ue4ss_settings(settings_file_path)
            INFO.logger.info("[ 解压更新 ] 解压操作完成")
            print("[ 解压更新 ] 解压操作完成")
        except Exception as e:
            INFO.logger.error(f"[ 解压更新 ] 解压操作失败: {str(e)}")
            print(f"[ 解压更新 ] 解压操作失败: {str(e)}")

    # 简化解压逻辑
    def check_and_extract(self):
        palinject_version_file_path = os.path.join(self.palinject_dir, "palinject_version.txt")
        # 获取版本号,暂定默认跟随PALWORLD官方更新版本号
        with zipfile.ZipFile(self.zip_file_path, 'r') as zip_ref:
            with zip_ref.open("palinject_version.txt") as f:
                zip_palplugin_version = f.readline().decode('utf-8').strip()
        # 检查palinject_version.txt版本号
        if os.path.isfile(palinject_version_file_path):
            with open(palinject_version_file_path, 'r', encoding='utf-8') as f:
                installed_palplugin_version = f.readline().strip()
            if installed_palplugin_version >= zip_palplugin_version :
                print(f"[ 启动检测 ] 当前插件版本{installed_palplugin_version}，无需解压")
                return
        print(f"[ 启动检测 ] 当前插件版本{zip_palplugin_version}，\n准备进行解压")
        self.unzip_files()

    # 修改 UE4SS-settings 防止有人默认不是dx11
    # 解压文件覆盖虽然一劳永逸 但是会影响已存在的配置
    def modify_ue4ss_settings(self, settings_file_path):
        lines = []
        section_found = False
        key_found = False

        with codecs.open(settings_file_path, 'r', encoding='utf-8-sig') as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            if '[Debug]' in line:
                section_found = True
            elif section_found and 'GraphicsAPI' in line:
                lines[i] = 'GraphicsAPI = dx11\n'
                key_found = True
                break

        if section_found and key_found:
            with codecs.open(settings_file_path, 'w', encoding='utf-8-sig') as f:
                f.writelines(lines)

            INFO.logger.info("[ 配置更新 ] GraphicsAPI 设置为 dx11")
            print("[ 配置更新 ] GraphicsAPI 设置为 dx11")
        else:
            INFO.logger.error("[ 配置错误 ] 无法找到 Debug 或 GraphicsAPI ")
            print("[ 配置错误 ] 无法找到 Debug 或 GraphicsAPI ")

    # 定时公告
    def send_notice(self):
        if not self.announcement_enabled:
            return
        if not self.announcement_time >= 30:
            print("[ 定时公告 ] 时间尽量大于30秒，请重新设置！")
            return

        # 初始化request_URL
        request_URL = None

        # 获取公告内容
        current_announcement = self.announcement_messages[self.current_announcement_index]

        if self.palinject_enabled:
            if current_announcement:
                base = "http://127.0.0.1:53000/rcon?text="
                command = f"broadcast {current_announcement}"
                messageText = urllib.parse.quote(command)
                request_URL = base + messageText

            # 发送HTTP请求
            try:
                if request_URL:
                    resp = urllib.request.urlopen(request_URL)
                    if resp.status == 200:
                        INFO.logger.info('[ 定时公告 ] {0}'.format(resp.read().decode('utf-8')))
                    else:
                        INFO.logger.error('[ 请求错误 ] HTTP状态码: {0}'.format(resp.status))
                        print('\r[ 请求错误 ] HTTP状态码:', resp.status)
            except urllib.error.URLError as e:
                INFO.logger.error('[ 请求错误 ] {0}'.format(e))
                print('\r[ 请求错误 ]', e)
        else:
            return

        # 更新当前要发送的公告索引
        self.current_announcement_index = (self.current_announcement_index + 1) % len(self.announcement_messages)

        # 创建定时器，延时发送下一条公告
        timer = threading.Timer(self.announcement_time, self.send_notice)
        timer.start()

    # 启动服务端
    def start_program(self):
        server_name = self.read_server_name()
        safe_server_name = server_name.replace('|', '^|').replace(':', '^:')
        INFO.logger.info(safe_server_name)
        os.system(f'title {safe_server_name}')  # 设置标题
        INFO.logger.info("[ 启动任务 ] 正在启动程序......")
        print("[ 启动任务 ] 正在启动程序......")

        if self.palinject_enabled:
            program_args = [self.palinject_path]
        else:
            program_args = [self.program_path]

        if self.arguments:
            INFO.logger.info("[ 启动任务 ] 已配置额外参数")
            print("[ 启动任务 ] 已配置额外参数")
            program_args.extend(self.arguments)
        if self.use_multicore_options:
            INFO.logger.info("[ 启动任务 ] 已开启多核选项")
            print("[ 启动任务 ] 已开启多核选项")
            program_args.extend(["-useperfthreads", "-NoAsyncLoadingThread", "-UseMultithreadForDS"])
        INFO.logger.info(f"[ 启动任务 ] 启动参数：{program_args}")

        try:
            program_args_str = ' '.join(map(str, program_args))
            cmd = f'cmd.exe /c & start "{server_name}" {program_args_str}'
            INFO.logger.info(cmd)
            subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE, shell=True)

        except FileNotFoundError:
            INFO.logger.error(f"[ 启动任务 ] 启动失败，请检查config.ini中main_directory路径配置")
            print(f"\r[ 启动任务 ] 启动失败，请检查config.ini中main_directory路径配置")
            time.sleep(3)
            exit(1)

        # 尝试连接
        if not self.palinject_enabled:
            if self.rcon_enabled:
                if self.is_first_run:  # 只有在首次运行时才检查RCON连接
                    INFO.logger.info("[ RCON ] 已开启RCON功能")
                    print("[ RCON ] 已开启RCON功能")
                    INFO.logger.info("[ RCON ] 正在检查RCON连接，请等待最多60秒......")
                    print("[ RCON ] 正在检查RCON连接，请等待最多60秒......")

                    start_time = time.time()
                    while time.time() - start_time < 60:
                        if self.check_rcon():
                            break
                        time.sleep(1)

                    else:
                        INFO.logger.error("[ RCON ] 无法在60秒内建立RCON连接")
                        print("[ RCON ] 无法在60秒内建立RCON连接")
                        sys.exit(0)

                    self.is_first_run = False

            else:
                INFO.logger.info("[ RCON ] 未开启RCON功能")
                print("[ RCON ] 未开启RCON功能")


    # 轮询任务(固定延迟执行)
    def polling_task(self):
        while True:
            # 经测试等于1分钟时原版RCON会出现timeout
            if self.restart_interval < 60:
                INFO.logger.error("[ 轮询任务 ] 服务器重启时间 restart_interval 必须大于1分钟，请重新设置！")
                print("[ 轮询任务 ] 服务器重启时间 restart_interval 必须大于1分钟，请重新设置！")
                time.sleep(2)
                sys.exit(0)

            # 启动程序前检查, 如果存在服务端则不再进行启动操作,改为每次循环结尾关闭进程
            is_running = self.is_palserver_running()
            INFO.logger.info(f"[ 轮询任务 ] 当前 PalServer 进程运行状态：{is_running}")
            if not is_running and (not self.is_restarting):
                INFO.logger.info("[ 前置检查 ] 未检测到 PalServer 服务，正在启动......")
                print("[ 前置检查 ] 未检测到 PalServer 服务，正在启动......")
                self.start_program()

            INFO.logger.info(f'[ 轮询任务 ] 服务器将进入重启倒计时，设置时长为 {self.conf["restart_interval"]} 秒......')
            print(f'\r[ 轮询任务 ] 服务器将进入重启倒计时，设置时长为 {self.conf["restart_interval"]} 秒......')

            # 服务器持续运行时间(重启间隔)
            for i in range(int(self.restart_interval), 0, -1):
                print("\r\033[K", end='')  # 清除当前行
                print(f'\r[ 轮询任务 ] 服务器将在 {i} 秒后重启......', end='')
                time.sleep(1)
                # 检查内存使用情况
                if self.memory_monitor_enabled:
                    if self.polling_interval_seconds > 5:
                        mem_info = psutil.virtual_memory()
                        mem_usage = mem_info.percent  # 获取内存使用百分比

                        # 内存超限关服消息提醒
                        if mem_usage > self.memory_usage_threshold:
                            self.is_restarting = True  # 开始重启
                            max_notice_time = max(map(int, self.shutdown_notice.keys()))  # 获取最大关服通知时间
                            INFO.logger.error(f"[ 内存监控 ] 内存使用超过{self.memory_usage_threshold}%，正在重启程序......")
                            print(f"\r[ 内存监控 ] 内存使用超过{self.memory_usage_threshold}%，正在重启程序......")
                            time.sleep(1)
                            # 倒计时关闭服务端
                            for j in range(max_notice_time, 0, -1):
                                time.sleep(1)
                                self.send_shutdown_notice(j)
                            # 关服之前执行一次SAVE
                            if self.rcon_enabled:
                                success, response = self.send_rcon_command("Save")
                                if success:
                                    INFO.logger.info('[ RCON ] 存档已保存 {0}'.format(response))
                                    print('\r[ RCON ] 存档已保存', response)
                                    time.sleep(3)
                                else:
                                    INFO.logger.error('[ RCON ] 存档保存失败: {0}'.format(response))
                            self.close_process()
                            self.is_first_run = True
                            time.sleep(5)
                            self.start_program()
                            self.is_restarting = False  # 重启完成

                    else:
                        INFO.logger.error("[ 内存监控 ] 轮询间隔 polling_interval_seconds 必须大于等于5秒，请重新设置！")
                        print("[ 内存监控 ] 轮询间隔 polling_interval_seconds 必须大于5秒，请重新设置！")
                        time.sleep(2)
                        sys.exit(0)

                # 还剩 x 秒的时候发送rcon关服消息提醒
                self.send_shutdown_notice(i)

            # 关服之前执行一次SAVE
            if self.rcon_enabled:
                success, response = self.send_rcon_command("Save")
                if success:
                    INFO.logger.info('[ RCON ] 存档已保存 {0}'.format(response))
                    print('\r[ RCON ] 存档已保存', response)
                    time.sleep(3)


            # 关闭服务端
            INFO.logger.info("[ 轮询任务 ] 正在关闭配置文件指定运行的 PalServer 服务......")
            print("\r\033[K", end='')
            # 清空屏幕信息
            os.system('cls' if os.name == 'nt' else 'clear')
            print("[ 轮询任务 ] 正在关闭配置文件指定运行的 PalServer 服务......")
            self.close_process()

            # 重启程序
            self.start_program()


    def start_daemon(self):
        # 守护进程
        while True:
            try:
                # tasklist检测列表会因为进程名过长截断尾部
                is_running = self.is_palserver_running()
                INFO.logger.info(f"[ 守护进程 ] 当前 PalServer 进程运行状态：{is_running}")

                if not is_running and (not self.is_restarting):
                    INFO.logger.info("[ 守护进程 ] 监控到 PalServer 已停止，正在重新启动......")
                    print("\r\033[K", end='')
                    print('[ 守护进程 ] 监控到 PalServer 已停止，正在重新启动......')

                    # 启动程序
                    self.start_program()

                # 倒计时
                for i in range(int(self.daemon_time), 0, -1):
                    time.sleep(1)

            # 只有异常退出才会触发，手动关闭进程不会触发
            except Exception as e:
                INFO.logger.error(f"[ 守护进程 ] 程序异常终止，错误信息：{e}\n正在尝试重启程序......")
                print("\r\033[K", end='')
                print(f"[ 守护进程 ] 程序异常终止，错误信息：{e}\n正在尝试重启程序......")
                continue

    def send_shutdown_notice(self, countdown):
        """Send a shutdown notice through RCON."""


        countdown_str = str(countdown)
        if self.palinject_enabled:
            if countdown_str in self.shutdown_notice_cn:
                message = self.shutdown_notice_cn[countdown_str]
                # api似乎只支持broadcast,避免改动config.ini
                command = f"broadcast {message}"
                base = "http://127.0.0.1:53000/rcon?text="
                messageText = urllib.parse.quote(command)
                request_URL = base + messageText

                # 发送HTTP请求
                try:
                    resp = urllib.request.urlopen(request_URL)
                    if resp.status == 200:
                        INFO.logger.info('[ 重启通知 ] {0}'.format(resp.read().decode('utf-8')))
                    else:
                        INFO.logger.error('[ 请求错误 ] HTTP状态码: {0}'.format(resp.status))
                except urllib.error.URLError as e:
                    INFO.logger.error('[ 请求错误 ] {0}'.format(e))
        else:
            if self.rcon_enabled and self.rcon_command and countdown_str in self.shutdown_notice:
                message = self.shutdown_notice[countdown_str]
                success, response = self.send_rcon_command(f"{self.rcon_command} {message}")
                if success:
                    INFO.logger.info('[ 指令发送 ] {0}'.format(response))
                    print('\r[ 指令发送 ]', response)
                else:
                    INFO.logger.error('[ 指令发送 ] 失败: {0}'.format(response))


def main():
    Task = TaskScheduler()
    if Task.conf['palinject_enabled']:
        INFO.logger.info("[ 启动检测 ] 检测已开启注入模式")
        print("[ 启动检测 ] 检测已开启注入模式")
        Task.check_and_extract()

    polling_thread = threading.Thread(target=Task.polling_task)
    INFO.logger.info("[ 轮询任务 ] 已启动，每隔{0}秒重启 PalServer 进程......".format(Task.conf['restart_interval']))
    print("[ 轮询任务 ] 已启动，每隔{0}秒重启 PalServer 进程......".format(Task.conf['restart_interval']))
    polling_thread.start()
    time.sleep(1)

    # [ 轮询任务 ] 必须在最初启动 防止[ 轮询任务 ] kill掉[ 守护进程 ] 刚启动的服务端
    if Task.conf['daemon_enabled']:
        print("\r\033[K", end='')
        INFO.logger.info("[ 守护进程 ] 守护进程已开启，延迟5秒启动避免双端开启，每隔{0}秒检查一次......".format(
            Task.conf['daemon_time']))
        print("[ 守护进程 ] 守护进程已开启，延迟5秒启动避免双端开启，每隔{0}秒检查一次......".format(
            Task.conf['daemon_time']))
        time.sleep(5)  # 延迟5秒避免双开服务端
        daemon_thread = threading.Thread(target=Task.start_daemon)
        daemon_thread.start()

    if Task.conf['memory_monitor_enabled']:
        INFO.logger.info("[ 内存监控 ] 已开启内存监控，每{0}秒检查一次，将在内存使用超过{1}%时重启程序".format(
            Task.conf['polling_interval_seconds'], Task.conf['memory_usage_threshold']))
        print("[ 内存监控 ] 已开启内存监控，每{0}秒检查一次，将在内存使用超过{1}%时重启程序".format(
            Task.conf['polling_interval_seconds'], Task.conf['memory_usage_threshold']))

    if Task.conf['palinject_enabled']:
        if Task.conf['announcement_enabled']:
            INFO.logger.info("[ 定时公告 ] 已启动，每隔{0}秒发送公告信息......".format(Task.conf['announcement_time']))
            print("[ 定时公告 ] 已启动，每隔{0}秒发送公告信息......".format(Task.conf['announcement_time']))
            time.sleep(30)
            Task.send_notice()  # 公告
        else:
            INFO.logger.info("[ 定时公告 ] 未启动，announcement_enabled开关为False")
            print("[ 定时公告 ] 未启动，announcement_enabled开关为False")
    else:
        INFO.logger.info("[ 定时公告 ] 未启动，palinject_enabled开关为False")
        print("[ 定时公告 ] 未启动，palinject_enabled开关为False")

    polling_thread.join()
    if Task.conf['daemon_enabled']:
        daemon_thread.join()


if __name__ == '__main__':
    main()