"""Official SDKs with explicit credentials and provider-owned HTTPS origins only.

All provider exceptions are translated before leaving this boundary. Neither raw
exceptions nor request URLs (which may contain signatures) may reach audit logs.
"""

import hashlib
import re
from datetime import timedelta
from urllib.parse import quote

import httpx

from app.core.errors import AppError


def provider_status(exc):
    for _ in range(5):
        if hasattr(exc, "get_status_code"):
            return str(exc.get_status_code())
        if getattr(exc, "status_code", None):
            return str(exc.status_code)
        if not hasattr(exc, "unwrap"):
            break
        exc = exc.unwrap()
    return None


def normalize_prefix(prefix: str | None) -> str:
    """Return a safe relative prefix; an empty value means bucket root."""
    value = (prefix or "").strip().strip("/")
    if not value:
        return ""
    if not re.fullmatch(r"[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*", value):
        raise AppError(
            422,
            "STORAGE_PREFIX_INVALID",
            "路径前缀可留空（表示桶根目录），或仅使用字母、数字、横线、下划线和目录分隔符",
        )
    return value


def validate_identity(provider, region, bucket, prefix):
    if provider not in {"cos", "oss"} or not re.fullmatch(r"[a-z][a-z0-9-]{2,39}", region):
        raise AppError(422, "STORAGE_IDENTITY_INVALID", "请使用云厂商地域标识")
    pattern = (
        r"[a-z0-9][a-z0-9-]{1,62}-[0-9]{5,20}"
        if provider == "cos"
        else r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]"
    )
    if not re.fullmatch(pattern, bucket):
        raise AppError(422, "STORAGE_IDENTITY_INVALID", "存储桶名称无效；COS 名称须包含 APPID")
    normalize_prefix(prefix)


class Adapter:
    def __init__(self, location, credentials):
        validate_identity(location.provider, location.region, location.bucket, location.prefix)
        self.location = location
        if location.provider == "cos":
            from qcloud_cos import CosConfig, CosS3Client

            self.client = CosS3Client(
                CosConfig(
                    Region=location.region,
                    SecretId=credentials["access_key_id"],
                    SecretKey=credentials["access_key_secret"],
                    Scheme="https",
                    Timeout=30,
                ),
                retry=1,
            )
            self.origin = f"https://{location.bucket}.cos.{location.region}.myqcloud.com"
        else:
            import alibabacloud_oss_v2 as oss

            self.oss = oss
            self.client = oss.Client(
                oss.Config(
                    region=location.region,
                    endpoint=f"https://oss-{location.region}.aliyuncs.com",
                    credentials_provider=oss.credentials.StaticCredentialsProvider(
                        credentials["access_key_id"], credentials["access_key_secret"]
                    ),
                    connect_timeout=5,
                    readwrite_timeout=30,
                    retry_max_attempts=2,
                    enabled_redirect=False,
                    disable_ssl=False,
                )
            )
            self.origin = f"https://{location.bucket}.oss-{location.region}.aliyuncs.com"

    def key(self, key):
        prefix = normalize_prefix(self.location.prefix)
        parts = key.split("/")
        within_prefix = key.startswith(prefix + "/") if prefix else True
        if (
            not within_prefix
            or not key
            or key.startswith("/")
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise AppError(422, "STORAGE_KEY_INVALID", "对象不在本系统专用路径内")
        return key

    def url(self, key):
        return self.origin + "/" + quote(self.key(key), safe="/")

    def call(self, method, **kwargs):
        try:
            return getattr(self.client, method)(**kwargs)
        except Exception as exc:
            status = provider_status(exc)
            code = "STORAGE_AUTH_ERROR" if str(status) in {"401", "403"} else "STORAGE_UNAVAILABLE"
            raise AppError(503, code, "对象存储请求失败，请检查权限、地域、网络及凭据") from None

    def check_bucket(self):
        """Versioned public objects cannot be reclaimed by an unversioned delete."""
        if self.location.provider == "cos":
            result = self.call("get_bucket_versioning", Bucket=self.location.bucket)
            status = result.get("Status")
        else:
            result = self.call(
                "get_bucket_versioning",
                request=self.oss.GetBucketVersioningRequest(bucket=self.location.bucket),
            )
            status = result.version_status
        if self.location.read_mode == "public" and status in {"Enabled", "Suspended"}:
            raise AppError(
                409,
                "STORAGE_POLICY_UNSAFE",
                "公开副本桶不能启用或曾启用版本控制；请使用独立未启用版本控制的桶",
            )

    def put(self, key, path, sha256, *, public=False):
        key = self.key(key)
        acl = "public-read" if public else "private"
        if self.location.provider == "cos":
            return self.call(
                "upload_file",
                Bucket=self.location.bucket,
                Key=key,
                LocalFilePath=str(path),
                PartSize=16,
                MAXThread=2,
                EnableMD5=True,
                ACL=acl,
                Metadata={"x-cos-meta-sha256": sha256},
                CacheControl="no-store",
                ContentType="application/octet-stream",
                ContentDisposition="attachment",
            )
        return self._oss_upload(key, path, sha256, acl)

    def _oss_upload(self, key, path, sha256, acl):
        try:
            return self.oss.Uploader(self.client).upload_file(
                self.oss.PutObjectRequest(
                    bucket=self.location.bucket,
                    key=key,
                    acl=acl,
                    metadata={"sha256": sha256},
                    cache_control="no-store",
                    content_disposition="attachment",
                    content_type="application/octet-stream",
                ),
                str(path),
                part_size=16 * 1024**2,
                parallel_num=2,
                leave_parts_on_error=False,
            )
        except Exception:
            raise AppError(
                503, "STORAGE_UPLOAD_FAILED", "云存储上传失败，可重试；尚未入库或发布"
            ) from None

    def head(self, key):
        key = self.key(key)
        if self.location.provider == "cos":
            value = self.call("head_object", Bucket=self.location.bucket, Key=key)
            return int(value["Content-Length"]), value.get("x-cos-meta-sha256")
        value = self.call(
            "head_object", request=self.oss.HeadObjectRequest(bucket=self.location.bucket, key=key)
        )
        return value.content_length, (value.metadata or {}).get("sha256")

    def list_objects(self, prefix, *, limit=50, cursor=None):
        """List objects below a validated application prefix.

        Listing is intentionally kept behind the adapter so provider response
        shapes and continuation tokens never reach the API layer.
        """
        prefix = prefix.strip("/")
        location_prefix = normalize_prefix(self.location.prefix)
        within_prefix = prefix.startswith(location_prefix + "/") if location_prefix else True
        if prefix and not within_prefix:
            raise AppError(422, "STORAGE_KEY_INVALID", "对象不在本系统专用路径内")
        if not 1 <= limit <= 100:
            raise AppError(422, "STORAGE_LIST_LIMIT_INVALID", "对象列表大小无效")
        if self.location.provider == "cos":
            arguments = {
                "Bucket": self.location.bucket,
                "Prefix": prefix + "/" if prefix else "",
                "MaxKeys": limit,
            }
            if cursor:
                arguments["Marker"] = cursor
            result = self.call("list_objects", **arguments)
            contents = result.get("Contents", []) or []
            items = [
                {
                    "key": item.get("Key"),
                    "size": int(item.get("Size", 0)),
                    "sha256": item.get("x-cos-meta-sha256"),
                }
                for item in contents
                if item.get("Key")
            ]
            return {
                "items": items,
                "next_cursor": result.get("NextMarker") if result.get("IsTruncated") else None,
            }
        request = self.oss.ListObjectsV2Request(
            bucket=self.location.bucket,
            prefix=prefix + "/" if prefix else "",
            max_keys=limit,
            continuation_token=cursor,
        )
        result = self.call("list_objects_v2", request=request)
        contents = result.contents or []
        return {
            "items": [
                {"key": item.key, "size": int(item.size or 0), "sha256": None}
                for item in contents
                if item.key
            ],
            "next_cursor": result.next_continuation_token if result.is_truncated else None,
        }

    def presign(self, key, seconds=300, file_name="download.bin"):
        key = self.key(key)
        disposition = "attachment; filename*=UTF-8''" + quote(file_name, safe="")
        if self.location.provider == "cos":
            return self.call(
                "get_presigned_download_url",
                Bucket=self.location.bucket,
                Key=key,
                Expired=seconds,
                Params={"response-content-disposition": disposition},
            )
        return self.call(
            "presign",
            request=self.oss.GetObjectRequest(
                bucket=self.location.bucket, key=key, response_content_disposition=disposition
            ),
            expires=timedelta(seconds=seconds),
        ).url

    def download(self, key, path, *, expected_size=None, max_size=None):
        """Stream a verified provider object to a local temporary path."""
        key = self.key(key)
        digest, count = hashlib.sha256(), 0
        try:
            with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
                with client.stream("GET", self.presign(key, seconds=600)) as response:
                    response.raise_for_status()
                    with open(path, "wb") as target:
                        for chunk in response.iter_bytes(1024**2):
                            count += len(chunk)
                            if expected_size is not None and count > expected_size:
                                raise ValueError("object is larger than declared")
                            if max_size is not None and count > max_size:
                                raise ValueError("object is larger than allowed")
                            digest.update(chunk)
                            target.write(chunk)
        except Exception:
            raise AppError(503, "STORAGE_DOWNLOAD_FAILED", "云端对象下载失败，请稍后重试") from None
        if expected_size is not None and count != expected_size:
            raise AppError(409, "STORAGE_CONTENT_MISMATCH", "对象大小与构建事件不一致")
        return count, digest.hexdigest()

    def anonymous_status(self, key):
        try:
            with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
                with client.stream(
                    "GET",
                    self.url(key),
                    headers={"Range": "bytes=0-0", "Cache-Control": "no-cache"},
                ) as response:
                    return response.status_code
        except Exception:
            raise AppError(
                503, "STORAGE_PROBE_UNAVAILABLE", "无法确认对象匿名访问权限，已阻止继续分发"
            ) from None

    def verify(self, key, size, sha256, *, public=False, full=False):
        actual_size, actual_sha256 = self.head(key)
        if actual_size != size or (actual_sha256 and actual_sha256 != sha256):
            raise AppError(409, "STORAGE_CONTENT_MISMATCH", "云端大小或摘要不一致")
        status = self.anonymous_status(key)
        if (public and status not in {200, 206}) or (not public and status != 403):
            raise AppError(
                409, "STORAGE_POLICY_UNSAFE", "匿名读取结果不符合所选模式，已阻止继续分发"
            )
        if full:
            digest, count = hashlib.sha256(), 0
            try:
                with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
                    with client.stream("GET", self.presign(key)) as response:
                        response.raise_for_status()
                        for chunk in response.iter_bytes(1024**2):
                            count += len(chunk)
                            if count > size:
                                raise ValueError
                            digest.update(chunk)
                if count != size or digest.hexdigest() != sha256:
                    raise ValueError
            except Exception:
                raise AppError(
                    503, "STORAGE_READBACK_FAILED", "云端回读校验失败，文件尚未就绪"
                ) from None

    def delete(self, key):
        key = self.key(key)
        # Recheck at reclaim time: the bucket policy may have changed since upload.
        if self.location.read_mode == "public":
            self.check_bucket()
        if self.location.provider == "cos":
            self.call("delete_object", Bucket=self.location.bucket, Key=key)
        else:
            self.call(
                "delete_object",
                request=self.oss.DeleteObjectRequest(bucket=self.location.bucket, key=key),
            )
        # Anonymous denial alone would also match a still-existing private object.
        try:
            if self.location.provider == "cos":
                self.client.head_object(Bucket=self.location.bucket, Key=key)
            else:
                self.client.head_object(
                    self.oss.HeadObjectRequest(bucket=self.location.bucket, key=key)
                )
        except Exception as exc:
            status = provider_status(exc)
            if str(status) == "404" and self.anonymous_status(key) in {403, 404}:
                return
        raise AppError(
            503, "STORAGE_DELETE_UNCONFIRMED", "删除或访问收回尚未确认；请重试并检查云权限"
        )
