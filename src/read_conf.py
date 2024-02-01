#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import codecs
import configparser
import json
import os


def read_config():
    # 读取配置文件
    config = configparser.ConfigParser()
    config_path = os.path.join(os.path.dirname(__file__), 'config.ini')
    with codecs.open(config_path, 'r', encoding='utf-8-sig') as f:
        config.read_file(f)
    main_directory = config.get('Settings', 'main_directory')
    backup_dir = config.get('Settings', 'backup_dir')
    arguments = config.get('Settings', 'arguments')
    use_multicore_options = config.getboolean('Settings', 'use_multicore_options')
    backup_interval_hours = config.getint('Settings', 'backup_interval_hours')
    backup_interval_minutes = config.getint('Settings', 'backup_interval_minutes')
    restart_interval_hours = config.getint('Settings', 'restart_interval_hours')
    restart_interval_minutes = config.getint('Settings', 'restart_interval_minutes')
    daemon_enabled = config.getboolean('Settings', 'daemon_enabled')
    daemon_time = config.get('Settings', 'daemon_time')
    memory_monitor_enabled = config.getboolean('Memory', 'memory_monitor_enabled')
    polling_interval_seconds = config.getint('Memory', 'polling_interval_seconds')
    memory_usage_threshold = config.getint('Memory', 'memory_usage_threshold')
    shutdown_notices = dict(item.split(':') for item in config.get('RCON', 'shutdown_notices').split(';'))
    rcon_enabled = config.getboolean('RCON', 'rcon_enabled')
    rcon_host = config.get('RCON', 'HOST')
    rcon_port = config.getint('RCON', 'PORT')
    rcon_password = config.get('RCON', 'AdminPassword')
    rcon_command = config.get('RCON', 'COMMAND')

    # 将小时和分钟转换为秒
    restart_interval = (restart_interval_hours * 60 + restart_interval_minutes) * 60
    backup_interval = (backup_interval_hours * 60 + backup_interval_minutes) * 60

    return {
        'main_directory': main_directory,
        'backup_dir': backup_dir,
        'arguments': arguments,
        'use_multicore_options': use_multicore_options,
        'rcon_enabled': rcon_enabled,
        'rcon_host': rcon_host,
        'rcon_port': rcon_port,
        'rcon_password': rcon_password,
        'rcon_command': rcon_command,
        'backup_interval': backup_interval,
        'restart_interval': restart_interval,
        'shutdown_notices': shutdown_notices,
        'daemon_enabled': daemon_enabled,
        'daemon_time': daemon_time,
        'memory_monitor_enabled': memory_monitor_enabled,
        'polling_interval_seconds': polling_interval_seconds,
        'memory_usage_threshold': memory_usage_threshold,
    }


if __name__ == '__main__':
    config = read_config()
    # 打印config中所有配置
    print(json.dumps(config, indent=4))
