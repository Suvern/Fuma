"""Credential-free parser entrypoint. Never extracts or executes package contents."""

import hashlib
import json
import plistlib
import re
import resource
import stat
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

VERSION = "fuma-parser-1"


def parse(path, platform):
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 20000:
            raise ValueError("压缩包条目过多")
        names, total = set(), 0
        for entry in entries:
            name = entry.filename
            total += entry.file_size
            if (
                name in names
                or "\\" in name
                or PurePosixPath(name).is_absolute()
                or ".." in PurePosixPath(name).parts
                or stat.S_ISLNK(entry.external_attr >> 16)
            ):
                raise ValueError("压缩包包含重复、越界或符号链接条目")
            names.add(name)
            if (
                total > 8 * 1024**3
                or entry.file_size > 2 * 1024**3
                or entry.file_size > max(entry.compress_size, 1) * 500
            ):
                raise ValueError("压缩包超过解压资源限制")
        if platform == "ios":
            candidates = [
                e for e in entries if re.fullmatch(r"Payload/[^/]+\.app/Info\.plist", e.filename)
            ]
            if len(candidates) != 1 or candidates[0].file_size > 1024**2:
                raise ValueError("IPA 必须包含唯一的主应用 Info.plist，且不超过 1 MiB")
            info = plistlib.loads(archive.read(candidates[0]))
            result = dict(
                package_identifier=info.get("CFBundleIdentifier"),
                version_name=info.get("CFBundleShortVersionString"),
                build_number=info.get("CFBundleVersion"),
                min_os=info.get("MinimumOSVersion"),
                architectures=[],
                signer_fingerprints=[],
                signature_status="未验证 Apple 安装资格；下载文件不代表可直接安装",
            )
        elif platform == "android":
            if "AndroidManifest.xml" not in names:
                raise ValueError("APK 缺少 AndroidManifest.xml")
            # Android SDK tools are installed only in the offline parser container.
            summary = command(["aapt", "dump", "badging", str(path)])
            package = re.search(
                r"^package: name='([^']+)' versionCode='([^']+)' versionName='([^']*)'",
                summary,
                re.M,
            )
            if not package:
                raise ValueError("无法读取 APK 包标识与版本")
            signed = command(["apksigner", "verify", "--print-certs", str(path)])
            certificates = re.findall(r"certificate SHA-256 digest: ([a-fA-F0-9]{64})", signed)
            if not certificates:
                raise ValueError("APK 签名校验未获得证书摘要")
            minimum = re.search(r"^sdkVersion:'([^']+)'", summary, re.M)
            architectures = sorted(
                {
                    e.filename.split("/")[1]
                    for e in entries
                    if re.fullmatch(r"lib/[^/]+/[^/]+\.so", e.filename)
                }
            )
            result = dict(
                package_identifier=package[1],
                version_name=package[3],
                build_number=package[2],
                min_os=minimum[1] if minimum else None,
                architectures=architectures,
                signer_fingerprints=certificates,
                signature_status="APK 签名验证通过",
            )
        else:
            raise ValueError("不支持的平台")
        for field in ("package_identifier", "version_name", "build_number"):
            if (
                not isinstance(result[field], str)
                or not result[field]
                or len(result[field]) > (255 if field == "package_identifier" else 100)
            ):
                raise ValueError("安装包标识或版本元数据不完整")
        if result["min_os"] is not None and (
            not isinstance(result["min_os"], str) or len(result["min_os"]) > 100
        ):
            raise ValueError("系统版本格式不合法")
        return {**result, "parser_version": VERSION}


def command(args):
    # Resource limits cap native tool output as well as parser output.
    import tempfile

    with tempfile.TemporaryFile() as output:
        completed = subprocess.run(
            args,
            stdout=output,
            stderr=subprocess.DEVNULL,
            timeout=40,
            env={
                "PATH": "/usr/bin:/bin",
                "JAVA_TOOL_OPTIONS": (
                    "-Xmx256m -Xss256k -XX:ActiveProcessorCount=1 "
                    "-XX:ParallelGCThreads=1 -XX:ConcGCThreads=1 -XX:CICompilerCount=2 "
                    "-XX:CompressedClassSpaceSize=64m -XX:ReservedCodeCacheSize=64m"
                ),
            },
            check=False,
        )
        if completed.returncode:
            raise ValueError("Android 元数据读取或签名验证失败")
        output.seek(0)
        value = output.read(1024**2 + 1)
        if len(value) > 1024**2:
            raise ValueError("解析器输出超过限制")
        return value.decode("utf-8", errors="strict")


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024**2, 2 * 1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    try:
        path = Path(sys.argv[1])
        platform = sys.argv[2]
        result = {"ok": True, "metadata": parse(path, platform), "sha256": hash_file(path)}
    except Exception as error:
        message = str(error) if isinstance(error, ValueError) else "安装包解析失败或解析工具不可用"
        result = {"ok": False, "error_message": message[:300]}
    sys.stdout.write(json.dumps(result, ensure_ascii=False))


def hash_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


if __name__ == "__main__":
    main()
