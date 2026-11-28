import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from aiobotocore.client import AioBaseClient
from aiobotocore.config import AioConfig
from aiobotocore.session import get_session

from hoshi.core.config import Settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def open_s3_client(settings: Settings) -> AsyncIterator[AioBaseClient]:
    """创建并管理异步 S3 客户端的生命周期上下文管理器"""

    # 提取认证信息并格式化连接参数
    access_key, secret_key = settings.s3_credentials()
    endpoint_url = str(settings.s3_endpoint_url).rstrip("/")
    region_name = settings.s3_region.strip()
    bucket = settings.s3_bucket.strip()

    # 配置 S3v4 签名与路径风格寻址
    client_config = AioConfig(signature_version="s3v4", s3={"addressing_style": "path"})

    # 初始化异步会话并创建客户端上下文
    session = get_session()
    async with session.create_client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region_name,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=client_config,
    ) as client:
        try:
            logger.info(
                "S3 客户端已装配, endpoint=%s, region_name=%s, bucket=%s, addressing_style=path",
                endpoint_url,
                region_name,
                bucket,
            )
            yield client
        finally:
            # 确保退出上下文时记录连接关闭日志
            logger.info("S3 客户端已关闭, endpoint=%s, bucket=%s", endpoint_url, bucket)
