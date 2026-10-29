"""Offline Java/Android APK builder. No Gradle, downloads, server access, or device installation.

First inspect the frozen web input with --inspect-web; then pass --expected-web-sha.
Signing uses existing private files selected by ASTERIA_CHAT_SIGNING_DIR; no key is created.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid
import zipfile

APP = Path(__file__).resolve().parent
ROOT = APP.parents[1]
VERSION = "1.7.0"
VERSION_CODE = 50
VERSION_SCHEMA = 2
# Exact permissions for authenticated chat, reply monitoring and explicitly
# enabled phone perception. Any additional permission fails the build.
EXPECTED_PERMISSIONS = [
    "uses-permission: name='android.permission.INTERNET'",
    "uses-permission: name='android.permission.POST_NOTIFICATIONS'",
    "uses-permission: name='android.permission.FOREGROUND_SERVICE'",
    "uses-permission: name='android.permission.FOREGROUND_SERVICE_DATA_SYNC'",
    "uses-permission: name='android.permission.ACCESS_NETWORK_STATE'",
    "uses-permission: name='android.permission.PACKAGE_USAGE_STATS'",
    "uses-permission: name='android.permission.FOREGROUND_SERVICE_SPECIAL_USE'",
]
DEFAULT_SERVER = ""
DEFAULT_CERT_SHA256 = ""
ALLOWED_WEB_EXTENSIONS = {".html", ".css", ".js", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".woff2"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(directory: Path, *, web: bool = False) -> dict[str, str]:
    if not directory.is_dir():
        raise RuntimeError(f"Missing source directory: {directory}")
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("Source symlinks are not accepted")
        if not path.is_file():
            continue
        relative = path.relative_to(directory).as_posix()
        if any(part.startswith(".") for part in Path(relative).parts):
            raise RuntimeError("Hidden source files must not enter the APK")
        if web and path.suffix.lower() not in ALLOWED_WEB_EXTENSIONS:
            raise RuntimeError(f"Unreviewed web asset type: {relative}")
        if path.stat().st_size > 8 * 1024 * 1024:
            raise RuntimeError(f"Oversized source: {relative}")
        result[relative] = sha(path)
    if not result or (web and "index.html" not in result):
        raise RuntimeError("Empty input or missing web index.html")
    return result


def aggregate(files: dict[str, str]) -> str:
    payload = json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(payload).hexdigest()


def run(argv: list[str | Path], *, cwd: Path, timeout: int = 90) -> str:
    command = [str(value) for value in argv]
    completed = subprocess.run(command, cwd=cwd, check=False, capture_output=True, timeout=timeout,
                               encoding="utf-8", errors="replace")
    output = completed.stdout + completed.stderr
    if completed.returncode:
        # No password values occur in argv or normal tool output; password inputs use private files.
        raise RuntimeError(f"{Path(command[0]).name} failed ({completed.returncode}):\n{output[-8000:]}")
    return output.strip()


def existing_signing() -> tuple[Path, Path]:
    """Locate existing signing files without reading or creating private data."""
    configured = os.environ.get("ASTERIA_CHAT_SIGNING_DIR", "").strip()
    if not configured:
        raise RuntimeError("Set ASTERIA_CHAT_SIGNING_DIR to the existing signing directory; no key will be generated")
    directory = Path(configured).expanduser()
    if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
        raise RuntimeError("ASTERIA_CHAT_SIGNING_DIR must be an existing absolute directory, not a symlink")
    key = Path(os.environ.get("ASTERIA_CHAT_KEYSTORE", str(directory / "asteria-chat.p12")))
    password = Path(os.environ.get("ASTERIA_CHAT_STOREPASS_FILE", str(directory / "storepass.private.txt")))
    for path in (key, password):
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError("Existing user-owned signing files are required; no key/password is created or copied")
    return key, password


def freeze_file(source: Path, destination: Path, digest: str, *, resume: bool) -> bool:
    """Retain an already restored, exact input; never silently replace drift."""
    if resume and destination.exists():
        if destination.is_symlink() or not destination.is_file() or sha(destination) != digest:
            raise RuntimeError("Existing frozen input differs from the selected source")
        return True
    shutil.copyfile(source, destination)
    if sha(destination) != digest:
        raise RuntimeError("Source changed while freezing build inputs")
    return False


def normalize_zip(source: Path, destination: Path, dex: Path) -> None:
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(destination, "x") as target:
        names = original.namelist()
        if len(names) != len(set(names)) or any(name.startswith("/") or ".." in Path(name).parts for name in names):
            raise RuntimeError("Unsafe resource archive")
        if "resources.arsc" not in names:
            raise RuntimeError("Missing Android resources table")
        for name in sorted(names):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED if name == "resources.arsc" else zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            target.writestr(info, original.read(name))
        for path in sorted(dex.glob("classes*.dex")):
            info = zipfile.ZipInfo(path.name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            target.writestr(info, path.read_bytes())


def verify_resource_layout(apk: Path) -> dict[str, int | bool]:
    with zipfile.ZipFile(apk) as archive:
        table = archive.getinfo("resources.arsc")
        if table.compress_type != zipfile.ZIP_STORED:
            raise RuntimeError("Target 30+ cannot install a compressed resources.arsc")
        with apk.open("rb") as stream:
            stream.seek(table.header_offset)
            header = stream.read(30)
        if len(header) != 30 or header[:4] != b"PK\x03\x04":
            raise RuntimeError("Invalid resources table local header")
        name_bytes, extra_bytes = struct.unpack_from("<HH", header, 26)
        data_offset = table.header_offset + 30 + name_bytes + extra_bytes
        if data_offset % 4:
            raise RuntimeError("Target 30+ requires a 4-byte-aligned resources.arsc data offset")
        return {"stored": True, "data_offset": data_offset, "data_offset_mod4": data_offset % 4,
                "uncompressed_bytes": table.file_size}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, default=Path(os.environ.get("ANDROID_HOME", str(Path.home() / ("AppData/Local/Android/Sdk" if os.name == "nt" else "Android/Sdk")))))
    parser.add_argument("--jdk", type=Path,
                        default=Path(os.environ.get("JAVA_HOME", ".")))
    parser.add_argument("--expected-web-sha")
    parser.add_argument("--server", default=DEFAULT_SERVER, help="Optional HTTPS API prefix; blank asks on first login")
    parser.add_argument("--key-alias", default=os.environ.get("ASTERIA_CHAT_KEY_ALIAS", "asteria-chat"))
    parser.add_argument("--inspect-web", action="store_true")
    parser.add_argument("--run-id", default=uuid.uuid4().hex)
    parser.add_argument("--resume-inputs", action="store_true",
                        help="Resume only an incomplete, verified pre-compilation input directory")
    parser.add_argument("--certificate-sha256", default=DEFAULT_CERT_SHA256,
                        help="Exact default-origin leaf DER SHA256; empty disables private-certificate fallback")
    args = parser.parse_args()
    web_files = snapshot(APP / "web", web=True)
    web_sha = aggregate(web_files)
    if args.inspect_web:
        print(json.dumps({"web_sha256": web_sha, "files": web_files}, ensure_ascii=False, indent=2))
        return 0
    if args.expected_web_sha != web_sha:
        raise RuntimeError("Web snapshot does not match the explicitly reviewed SHA; inspect/freeze it first")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", args.run_id):
        raise RuntimeError("Invalid run id")
    from urllib.parse import urlsplit
    server = args.server.strip().rstrip("/")
    if server:
        parsed = urlsplit(server)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise RuntimeError("Compiled default server must be an HTTPS API prefix without credentials")
    brand = json.loads((APP / "brand.json").read_text(encoding="utf8"))
    app_name = brand["name"]
    if not isinstance(app_name, str) or not 1 <= len(app_name) <= 60 or any(ord(c) < 32 for c in app_name):
        raise RuntimeError("Invalid app name")
    pin = args.certificate_sha256.lower()
    if pin and not re.fullmatch(r"[0-9a-f]{64}", pin):
        raise RuntimeError("Certificate pin must be exactly one DER SHA256")
    if pin and not server:
        raise RuntimeError("A leaf certificate pin requires an explicit compiled HTTPS default server")
    key, password = existing_signing()
    records = ROOT / ".runtime" / "asteria_chat_build" / args.run_id
    if args.resume_inputs:
        if records.is_symlink() or not records.is_dir() or any(records.iterdir()):
            raise RuntimeError("Resume requires the original incomplete build record directory")
    else:
        records.mkdir(parents=True, exist_ok=False)
    # The installed Windows aapt2 cannot open the existing non-ASCII project path.
    # Freeze exact bytes into an isolated ASCII temp directory; never rename the project.
    work = Path(tempfile.gettempdir()) / "AsteriaChatBuild" / args.run_id
    try:
        str(work).encode("ascii")
    except UnicodeEncodeError as error:
        raise RuntimeError("Windows native build tools need an ASCII TEMP directory") from error
    if args.resume_inputs:
        if (work.is_symlink() or not work.is_dir()
                or {item.name for item in work.iterdir()} != {"android", "assets"}
                or (work / "android").is_symlink() or (work / "assets").is_symlink()
                or not (work / "assets/app.js").is_file()):
            raise RuntimeError("Resume requires restored original inputs before native compilation")
    else:
        work.mkdir(parents=True, exist_ok=False)
    retained_inputs = []
    android = APP / "android"
    source = snapshot(android / "src")
    resources = snapshot(android / "res")
    manifest_sha = sha(android / "AndroidManifest.xml")
    build_script_sha = sha(Path(__file__))
    frozen_android = work / "android"
    for area, files in (("src", source), ("res", resources)):
        for relative, digest in files.items():
            destination = frozen_android / area / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if freeze_file(android / area / relative, destination, digest, resume=args.resume_inputs):
                retained_inputs.append("android/" + area + "/" + relative)
    if freeze_file(android / "AndroidManifest.xml", frozen_android / "AndroidManifest.xml", manifest_sha, resume=args.resume_inputs):
        retained_inputs.append("android/AndroidManifest.xml")
    if snapshot(frozen_android / "src") != source or snapshot(frozen_android / "res") != resources:
        raise RuntimeError("Frozen native inputs differ from the selected source")
    assets = work / "assets"
    assets.mkdir(exist_ok=args.resume_inputs)
    for relative, digest in web_files.items():
        destination = assets / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if freeze_file(APP / "web" / relative, destination, digest, resume=args.resume_inputs):
            retained_inputs.append("assets/" + relative)
    if ({p.relative_to(assets).as_posix() for p in assets.rglob("*") if p.is_file()} != set(web_files)
            or snapshot(assets, web=True) != web_files):
        raise RuntimeError("Frozen assets do not match the complete selected web input")
    if snapshot(APP / "web", web=True) != web_files:
        raise RuntimeError("Web input changed while freezing assets")
    executable = lambda path: path.with_name(path.name + ".exe") if os.name == "nt" else path
    java = executable(args.jdk / "bin/java")
    javac = executable(args.jdk / "bin/javac")
    tools = args.sdk / "build-tools/35.0.0"
    platform = args.sdk / "platforms/android-35/android.jar"
    for tool in (java, javac, executable(tools / "aapt2"), executable(tools / "zipalign"), tools / "lib/d8.jar",
                 tools / "lib/apksigner.jar", platform):
        if not tool.is_file():
            raise RuntimeError(f"Missing offline build tool: {tool}")
    generated = work / "generated"
    classes = work / "classes"
    dex = work / "dex"
    for directory in (generated, classes, dex):
        directory.mkdir()
    config = generated / "com/asteria/chat/BuildConfig.java"
    config.parent.mkdir(parents=True)
    config.write_text("package com.asteria.chat;\npublic final class BuildConfig {\n"
                      f'public static final String VERSION_NAME="{VERSION}";\n'
                      f'public static final String DEFAULT_SERVER={json.dumps(server)};\n'
                      f'public static final String APP_NAME={json.dumps(app_name)};\n'
                      f'public static final String DEFAULT_CERT_SHA256="{pin}";\n'
                      "private BuildConfig() {}\n}\n", encoding="utf-8")
    versions = {"java": run([java, "-version"], cwd=work),
                "aapt2": run([executable(tools / "aapt2"), "version"], cwd=work),
                "d8": run([java, "-cp", tools / "lib/d8.jar", "com.android.tools.r8.D8", "--version"], cwd=work),
                "apksigner": run([java, "-jar", tools / "lib/apksigner.jar", "version"], cwd=work)}
    if not re.search(r'\bversion\s+"17(?:\.|"|[-+])', versions["java"]):
        raise RuntimeError("Offline build requires JDK 17")
    compiled = work / "compiled-res.zip"
    run([executable(tools / "aapt2"), "compile", "--dir", frozen_android / "res", "-o", compiled], cwd=work)
    resource_apk = work / "resources.apk"
    run([executable(tools / "aapt2"), "link", "--auto-add-overlay", "-I", platform, "--manifest", frozen_android / "AndroidManifest.xml",
         "-R", compiled, "-A", assets, "--java", generated, "--min-sdk-version", "26",
         "--target-sdk-version", "35", "--version-code", str(VERSION_CODE), "--version-name", VERSION,
         "-o", resource_apk], cwd=work)
    java_sources = sorted((frozen_android / "src").rglob("*.java")) + sorted(generated.rglob("*.java"))
    run([javac, "-encoding", "UTF-8", "-g:none", "--release", "8",
         "-classpath", platform, "-d", classes, *java_sources], cwd=work)
    run([java, "-Xmx512m", "-cp", tools / "lib/d8.jar", "com.android.tools.r8.D8",
         "--lib", platform, "--min-api", "26", "--output", dex, *sorted(classes.rglob("*.class"))], cwd=work)
    unsigned = work / "unsigned.apk"
    normalize_zip(resource_apk, unsigned, dex)
    aligned = work / "aligned.apk"
    run([executable(tools / "zipalign"), "-p", "4", unsigned, aligned], cwd=work)
    signed = work / f"asteria-chat-{VERSION}.apk"
    run([java, "-jar", tools / "lib/apksigner.jar", "sign", "--ks", key,
         "--ks-key-alias", args.key_alias, "--ks-pass", f"file:{password}",
         "--out", signed, aligned], cwd=work)
    signature = run([java, "-jar", tools / "lib/apksigner.jar", "verify", "--verbose", "--print-certs", signed], cwd=work)
    alignment = run([executable(tools / "zipalign"), "-c", "-v", "4", signed], cwd=work)
    resource_layout = verify_resource_layout(signed)
    badging = run([executable(tools / "aapt2"), "dump", "badging", signed], cwd=work)
    if "package: name='com.asteria.chat'" not in badging or "minSdkVersion:'26'" not in badging \
            or "targetSdkVersion:'35'" not in badging \
            or f"versionCode='{VERSION_CODE}' versionName='{VERSION}'" not in badging:
        raise RuntimeError("APK package or platform contract mismatch")
    permissions = [line for line in badging.splitlines() if line.startswith("uses-permission:")]
    if permissions != EXPECTED_PERMISSIONS:
        raise RuntimeError("Unexpected APK permissions: %r" % (permissions,))
    if not (work / "dex/classes.dex").is_file():
        raise RuntimeError("APK contains no application dex")
    with zipfile.ZipFile(signed) as archive:
        for relative, digest in web_files.items():
            if hashlib.sha256(archive.read("assets/" + relative)).hexdigest() != digest:
                raise RuntimeError("APK asset does not match the frozen web source")
        if any(".p12" in name or "storepass" in name or "private" in name.lower() for name in archive.namelist()):
            raise RuntimeError("Private material entered the APK")
    if source != snapshot(android / "src") or resources != snapshot(android / "res") \
            or manifest_sha != sha(android / "AndroidManifest.xml") or web_files != snapshot(APP / "web", web=True) \
            or build_script_sha != sha(Path(__file__)):
        raise RuntimeError("Build inputs changed during compilation")
    package = ROOT / "packages" / signed.name
    package.parent.mkdir(exist_ok=True)
    digest = sha(signed)
    if package.exists():
        if sha(package) != digest:
            raise RuntimeError("A different package already uses this version; preserve it and select a new version")
    else:
        with package.open("xb") as output:
            output.write(signed.read_bytes())
    receipt = {"schema": "asteria_chat_offline_build_v1", "run_id": args.run_id, "version": VERSION,
               "version_code": VERSION_CODE,
               "package": "com.asteria.chat", "apk": str(package.relative_to(ROOT)).replace("\\", "/"),
               "apk_sha256": digest, "apk_bytes": package.stat().st_size,
               "web_sha256": web_sha, "web_files": web_files,
               "android_sources": source, "android_resources": resources, "manifest_sha256": manifest_sha,
               "build_script_sha256": build_script_sha, "default_server": server,
               "default_leaf_certificate_sha256": pin, "pin_scope": "exact compiled default server only; system trust otherwise",
               "min_sdk": 26, "target_sdk": 35, "permissions": [value.split("'")[1] for value in EXPECTED_PERMISSIONS],
               "tools": versions, "signature_verification": signature,
               "native_work_directory": str(work),
               "windows_path_boundary": "verified frozen input bytes in isolated ASCII TEMP; original project is unchanged",
               "alignment_verified": True, "alignment_tool_output": alignment,
               "resources_arsc": resource_layout,
               "source_and_assets_verified": True, "offline_build": True,
               "resumed_verified_inputs": args.resume_inputs, "retained_frozen_inputs": retained_inputs,
               "adb_installation_attempted": False, "real_device_acceptance": False,
               "production_modified": False, "signing_key_in_package": False,
               "signing_key_boundary": "existing operator-owned key selected by ASTERIA_CHAT_SIGNING_DIR; no key/password generation; private values omitted"}
    receipt_path = records / "build.safe.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    public_receipt = package.with_suffix(".build.safe.json")
    if public_receipt.exists():
        public_receipt = package.with_name(f"asteria-chat-{VERSION}.{args.run_id}.build.safe.json")
    with public_receipt.open("x", encoding="utf-8") as handle:
        json.dump(receipt, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"apk": str(package), "sha256": digest, "bytes": package.stat().st_size,
                      "receipt": str(public_receipt), "web_sha256": web_sha,
                      "signature_verified": True, "real_device_acceptance": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.TimeoutExpired, OSError) as failure:
        print(f"Build stopped: {failure}", file=sys.stderr)
        raise SystemExit(1)
