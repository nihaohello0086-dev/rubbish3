# app/utils/logger.py
import logging
import sys
from pathlib import Path
from typing import Optional, Any, Dict
import json
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """JSON格式化器，便于日志分析"""

    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
        }

        # 使用 getattr 避免类型检查警告
        extra_data = getattr(record, "extra_data", None)
        if extra_data is not None:
            log_obj["data"] = extra_data

        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj, ensure_ascii=False)


def setup_logger(
    name: str = "grading_system", log_level: str = "INFO", log_dir: str = "logs"
) -> logging.Logger:
    """
    设置应用日志器

    Args:
        name: 日志器名称
        log_level: 日志级别
        log_dir: 日志文件目录
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper()))

    # 避免重复添加处理器
    if logger.handlers:
        return logger

    # 创建日志目录
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)

    # 控制台处理器 - 人类可读格式
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - [%(module)s:%(funcName)s:%(lineno)d] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_format)

    # 文件处理器 - JSON格式，便于分析
    file_handler = logging.FileHandler(
        log_path / f"app_{datetime.now().strftime('%Y%m%d')}.log", encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JSONFormatter())

    # 错误文件处理器 - 只记录错误
    error_handler = logging.FileHandler(
        log_path / f"errors_{datetime.now().strftime('%Y%m%d')}.log", encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(JSONFormatter())

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.addHandler(error_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    获取子模块的日志器

    Args:
        name: 模块名称

    Returns:
        配置好的日志器
    """
    return logging.getLogger(f"grading_system.{name}")


# 创建默认日志器
logger = setup_logger()

# 导出常用的日志函数，方便其他模块使用
debug = logger.debug
info = logger.info
warning = logger.warning
error = logger.error
critical = logger.critical
