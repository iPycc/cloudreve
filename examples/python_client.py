"""
Cloudreve Python 客户端示例
================================
本示例涵盖 Cloudreve 后端的以下功能：

1. 用户认证（登录、刷新令牌、登出）
2. 存储策略管理（列出、查看、创建、更新、删除）
3. 存储策略 CORS 配置（适用于 S3、OSS、COS、KS3、OBS）
4. OneDrive OAuth 管理（获取授权链接、查看凭据状态）
5. 文件上传（创建上传会话、分片上传、本地文件上传）
6. 文件下载（获取下载/预览链接、下载文件内容）
7. 文件操作（列出文件、获取文件信息）

支持的存储后端：
  - local   : 本机存储
  - remote  : 从机（分布式）存储
  - s3      : Amazon S3 及兼容协议（MinIO 等）
  - oss     : 阿里云 OSS
  - cos     : 腾讯云 COS
  - obs     : 华为云 OBS
  - ks3     : 金山云 KS3
  - qiniu   : 七牛云 Kodo
  - upyun   : 又拍云
  - onedrive: Microsoft OneDrive / SharePoint

依赖：
    pip install requests

使用方法：
    python python_client.py
"""

import math
import os
import time

import requests

# ─────────────────────────────────────────────
# 基础配置
# ─────────────────────────────────────────────
BASE_URL = "http://localhost:5212"  # Cloudreve 服务地址（生产环境请使用 https://）
API_PREFIX = "/api/v4"
ADMIN_EMAIL = "admin@cloudreve.org"  # 管理员邮箱
ADMIN_PASSWORD = "admin_password"   # 管理员密码

# ─────────────────────────────────────────────
# Cloudreve API 客户端
# ─────────────────────────────────────────────

class CloudreveClient:
    """Cloudreve HTTP API 封装客户端。"""

    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self._access_token: str = ""
        self._refresh_token: str = ""

    # ── 内部工具 ──────────────────────────────

    def _url(self, path: str) -> str:
        return f"{self.base_url}{API_PREFIX}{path}"

    def _auth_header(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token}"}

    def _check(self, resp: requests.Response) -> dict:
        """检查 HTTP 响应，非 2xx 或 code != 0 时抛出异常。"""
        resp.raise_for_status()
        data = resp.json()
        if data.get("code", 0) != 0:
            raise RuntimeError(
                f"API 错误 code={data['code']}: {data.get('msg', '')} {data.get('error', '')}"
            )
        return data

    # ─────────────────────────────────────────
    # 1. 用户认证
    # ─────────────────────────────────────────

    def login(self, email: str, password: str) -> dict:
        """
        用户登录，获取 access_token / refresh_token。

        POST /api/v4/session/token
        请求体: { "email": "...", "password": "..." }
        响应体: { "code": 0, "data": { "token": { "access_token": "...", "refresh_token": "..." }, ... } }
        """
        payload = {"email": email, "password": password}
        resp = self.session.post(self._url("/session/token"), json=payload)
        result = self._check(resp)
        token_data = result["data"]["token"]
        self._access_token = token_data["access_token"]
        self._refresh_token = token_data["refresh_token"]
        self.session.headers.update(self._auth_header())
        print(f"[认证] 登录成功，access_token 前缀: {self._access_token[:20]}...")
        return result["data"]

    def refresh_token(self) -> dict:
        """
        使用 refresh_token 刷新 access_token。

        POST /api/v4/session/token/refresh
        请求体: { "refresh_token": "..." }
        响应体: { "code": 0, "data": { "access_token": "...", "refresh_token": "..." } }
        """
        payload = {"refresh_token": self._refresh_token}
        resp = self.session.post(self._url("/session/token/refresh"), json=payload)
        result = self._check(resp)
        token_data = result["data"]
        self._access_token = token_data["access_token"]
        self._refresh_token = token_data["refresh_token"]
        self.session.headers.update(self._auth_header())
        print(f"[认证] 令牌刷新成功")
        return token_data

    def logout(self) -> None:
        """
        登出，吊销当前 refresh_token。

        DELETE /api/v4/session/token
        请求体: { "refresh_token": "..." }
        """
        payload = {"refresh_token": self._refresh_token}
        resp = self.session.delete(self._url("/session/token"), json=payload)
        self._check(resp)
        self._access_token = ""
        self._refresh_token = ""
        self.session.headers.pop("Authorization", None)
        print("[认证] 已登出")

    # ─────────────────────────────────────────
    # 2. 存储策略管理（Admin）
    # ─────────────────────────────────────────

    def list_storage_policies(
        self,
        page: int = 1,
        page_size: int = 20,
        order_by: str = "updated_at",
        order_direction: str = "DESC",
        policy_type: str = "",
    ) -> dict:
        """
        列出所有存储策略（分页）。

        POST /api/v4/admin/policy
        请求体:
        {
            "page": 1,
            "page_size": 20,
            "order_by": "updated_at",
            "order_direction": "DESC",
            "conditions": { "policy_type": "s3" }   // 可选过滤
        }
        响应: { "code": 0, "data": { "pagination": {...}, "policies": [...] } }
        """
        payload = {
            "page": page,
            "page_size": page_size,
            "order_by": order_by,
            "order_direction": order_direction,
            "conditions": {},
        }
        if policy_type:
            payload["conditions"]["policy_type"] = policy_type

        resp = self.session.post(self._url("/admin/policy"), json=payload)
        result = self._check(resp)
        policies = result["data"]["policies"]
        total = result["data"]["pagination"]["total"]
        print(f"[存储策略] 共 {total} 条，本页返回 {len(policies)} 条")
        return result["data"]

    def get_storage_policy(self, policy_id: int, count_entity: bool = False) -> dict:
        """
        获取单个存储策略详情。

        GET /api/v4/admin/policy/:id?countEntity=1
        响应: { "code": 0, "data": { "id": 1, "name": "...", "type": "s3", "settings": {...}, ... } }

        count_entity=True 时额外返回 entities_count / entities_size。
        """
        params = {}
        if count_entity:
            params["countEntity"] = "1"
        resp = self.session.get(self._url(f"/admin/policy/{policy_id}"), params=params)
        result = self._check(resp)
        policy = result["data"]
        print(f"[存储策略] 策略 {policy_id}: name={policy['name']}, type={policy['type']}")
        if count_entity:
            print(
                f"  - 文件数: {policy.get('entities_count', 0)}, "
                f"占用空间: {policy.get('entities_size', 0)} 字节"
            )
        return policy

    def create_storage_policy(self, policy: dict) -> dict:
        """
        创建新的存储策略。

        PUT /api/v4/admin/policy
        请求体: { "policy": { "name": "...", "type": "s3", "settings": {...}, ... } }
        响应: 创建后的策略详情

        policy 字段说明：
          name           (str)   策略名称
          type           (str)   存储类型，可选值见文件顶部
          server         (str)   存储节点地址（本机存储留空）
          bucket_name    (str)   存储桶/容器名称
          is_private     (bool)  是否私有读
          access_key     (str)   访问密钥 ID
          secret_key     (str)   访问密钥 Secret
          max_size       (int)   单文件最大字节数，0 表示不限制
          dir_name_rule  (str)   目录命名规则，支持 {uid} {path} {date} 等变量
          file_name_rule (str)   文件命名规则，支持 {originName} {timestamp} 等变量
          settings       (dict)  高级配置（见下方各存储类型说明）
        """
        payload = {"policy": policy}
        resp = self.session.put(self._url("/admin/policy"), json=payload)
        result = self._check(resp)
        created = result["data"]
        print(f"[存储策略] 策略创建成功，ID={created['id']}, name={created['name']}")
        return created

    def update_storage_policy(self, policy_id: int, policy: dict) -> dict:
        """
        更新已有存储策略。

        PUT /api/v4/admin/policy/:id
        请求体: { "policy": { ... } }
        响应: 更新后的策略详情
        """
        payload = {"policy": policy}
        resp = self.session.put(self._url(f"/admin/policy/{policy_id}"), json=payload)
        result = self._check(resp)
        updated = result["data"]
        print(f"[存储策略] 策略 {policy_id} 更新成功")
        return updated

    def delete_storage_policy(self, policy_id: int) -> None:
        """
        删除存储策略。

        DELETE /api/v4/admin/policy/:id

        限制：
          - 不能删除 ID=1 的默认策略
          - 不能删除被用户组引用的策略
          - 不能删除存在文件的策略
        """
        resp = self.session.delete(self._url(f"/admin/policy/{policy_id}"))
        self._check(resp)
        print(f"[存储策略] 策略 {policy_id} 已删除")

    # ─────────────────────────────────────────
    # 3. CORS 配置（适用于云存储桶）
    # ─────────────────────────────────────────

    def create_cors_config(self, policy: dict) -> None:
        """
        自动在云存储桶上创建 CORS 规则，使浏览器可直传文件。

        POST /api/v4/admin/policy/cors
        请求体: { "policy": { "id": 2, "type": "s3", ... } }

        支持的存储类型: s3, oss, cos, ks3, obs
        """
        payload = {"policy": policy}
        resp = self.session.post(self._url("/admin/policy/cors"), json=payload)
        self._check(resp)
        print(f"[CORS] 策略 {policy.get('id')} 的 CORS 规则已创建")

    # ─────────────────────────────────────────
    # 4. OneDrive OAuth 管理
    # ─────────────────────────────────────────

    def get_onedrive_oauth_url(self, policy_id: int, app_id: str, secret: str) -> str:
        """
        获取 OneDrive OAuth2 授权跳转地址。

        POST /api/v4/admin/policy/oauth/signin
        请求体: { "id": 3, "app_id": "...", "secret": "..." }
        响应: { "code": 0, "data": "https://login.microsoftonline.com/..." }
        """
        payload = {"id": policy_id, "app_id": app_id, "secret": secret}
        resp = self.session.post(self._url("/admin/policy/oauth/signin"), json=payload)
        result = self._check(resp)
        url = result["data"]
        print(f"[OneDrive OAuth] 授权链接: {url}")
        return url

    def get_onedrive_oauth_redirect_url(self) -> str:
        """
        获取 OneDrive OAuth 回调地址（需要在 Azure 应用中注册）。

        GET /api/v4/admin/policy/oauth/redirect
        """
        resp = self.session.get(self._url("/admin/policy/oauth/redirect"))
        result = self._check(resp)
        url = result["data"]
        print(f"[OneDrive OAuth] 回调地址: {url}")
        return url

    def get_onedrive_credential_status(self, policy_id: int) -> dict:
        """
        检查 OneDrive 凭据（Token）是否有效。

        GET /api/v4/admin/policy/oauth/status/:id
        响应: { "code": 0, "data": { "valid": true, "last_refresh_time": "..." } }
        """
        resp = self.session.get(self._url(f"/admin/policy/oauth/status/{policy_id}"))
        result = self._check(resp)
        status = result["data"]
        print(
            f"[OneDrive OAuth] 策略 {policy_id} 凭据状态: "
            f"valid={status['valid']}, last_refresh_time={status.get('last_refresh_time')}"
        )
        return status

    def finish_onedrive_oauth(self, code: str, state: str) -> None:
        """
        完成 OneDrive OAuth 回调，使用授权码换取并保存 Token。

        POST /api/v4/admin/policy/oauth/callback
        请求体: { "code": "M.R3_BAY.xxx", "state": "3" }
        （state 为策略 ID 的字符串形式）
        """
        payload = {"code": code, "state": state}
        resp = self.session.post(self._url("/admin/policy/oauth/callback"), json=payload)
        self._check(resp)
        print(f"[OneDrive OAuth] OAuth 完成，策略 {state} 凭据已保存")

    # ─────────────────────────────────────────
    # 5. 文件上传
    # ─────────────────────────────────────────

    def create_upload_session(
        self,
        uri: str,
        size: int,
        last_modified: int = 0,
        mime_type: str = "application/octet-stream",
        policy_id: str = "",
        metadata: dict = None,
        entity_type: str = "",
    ) -> dict:
        """
        创建文件上传会话。

        PUT /api/v4/file/upload
        请求体:
        {
            "uri": "/My Files/example.txt",
            "size": 1048576,
            "last_modified": 1704067200000,
            "mime_type": "text/plain",
            "policy_id": "MQ==",          // 可选，留空则使用用户默认策略
            "metadata": {},               // 可选自定义元数据（最多 256 个键）
            "entity_type": ""             // 可选: "" | "live_photo" | "version"
        }
        响应:
        {
            "session_id": "abc123",
            "chunk_size": 26214400,      // 每片大小（字节）
            "expires": 1704153600,
            "upload_urls": [...],         // 云存储直传 URL（非本机存储时有效）
            "storage_policy": { ... }
        }
        """
        payload = {
            "uri": uri,
            "size": size,
            "last_modified": last_modified or int(time.time() * 1000),
            "mime_type": mime_type,
            "policy_id": policy_id,
            "metadata": metadata or {},
            "entity_type": entity_type,
        }
        resp = self.session.put(self._url("/file/upload"), json=payload)
        result = self._check(resp)
        session = result["data"]
        print(
            f"[上传] 会话已创建: session_id={session['session_id']}, "
            f"chunk_size={session['chunk_size']} 字节"
        )
        return session

    def upload_chunk(self, session_id: str, index: int, data: bytes) -> None:
        """
        上传文件分片。

        POST /api/v4/file/upload/:sessionId/:index
        Content-Type: application/octet-stream
        请求体: 原始二进制数据

        :param session_id: 由 create_upload_session 返回的会话 ID
        :param index:      分片索引（从 0 开始）
        :param data:       本片二进制内容
        """
        url = self._url(f"/file/upload/{session_id}/{index}")
        headers = {
            "Content-Type": "application/octet-stream",
            "Authorization": f"Bearer {self._access_token}",
        }
        resp = requests.post(url, data=data, headers=headers)
        resp.raise_for_status()
        body = resp.json()
        if body.get("code", 0) != 0:
            raise RuntimeError(
                f"分片 {index} 上传失败: code={body['code']} {body.get('msg', '')}"
            )
        print(f"[上传] 分片 {index} 上传成功")

    def upload_file(self, local_path: str, remote_uri: str, policy_id: str = "") -> None:
        """
        上传本地文件到 Cloudreve（自动分片）。

        完整流程:
          1. create_upload_session  → 获取 session_id / chunk_size
          2. 按 chunk_size 切割文件，逐片调用 upload_chunk
          3. 若上传中断可调用 delete_upload_session 清理会话

        :param local_path:  本地文件路径
        :param remote_uri:  目标路径，例如 "/My Files/photo.jpg"
        :param policy_id:   存储策略哈希 ID（可选）
        """
        file_size = os.path.getsize(local_path)
        mime_type = _guess_mime(local_path)
        last_modified = int(os.path.getmtime(local_path) * 1000)

        session = self.create_upload_session(
            uri=remote_uri,
            size=file_size,
            last_modified=last_modified,
            mime_type=mime_type,
            policy_id=policy_id,
        )
        session_id = session["session_id"]
        # chunk_size=0 means the server wants a single-part upload; treat it as the full file size.
        # Also guard against file_size=0 (empty file) to avoid ZeroDivisionError.
        chunk_size = session["chunk_size"] or file_size or 1  # fallback to 1 for empty files

        try:
            with open(local_path, "rb") as f:
                total_chunks = max(1, math.ceil(file_size / chunk_size))
                for idx in range(total_chunks):
                    chunk_data = f.read(chunk_size)
                    if not chunk_data:
                        break
                    self.upload_chunk(session_id, idx, chunk_data)
            print(f"[上传] 文件 '{local_path}' 上传完成 → '{remote_uri}'")
        except Exception as exc:
            print(f"[上传] 上传失败，正在清理会话: {exc}")
            self.delete_upload_session([session_id])
            raise

    def delete_upload_session(self, session_ids: list) -> None:
        """
        删除（取消）上传会话，释放服务端资源。

        DELETE /api/v4/file/upload
        请求体: { "session_ids": ["id1", "id2"] }
        """
        payload = {"session_ids": session_ids}
        resp = self.session.delete(self._url("/file/upload"), json=payload)
        self._check(resp)
        print(f"[上传] 会话已清理: {session_ids}")

    # ─────────────────────────────────────────
    # 6. 文件下载 / 预览链接
    # ─────────────────────────────────────────

    def get_file_url(
        self,
        uris: list,
        download: bool = False,
        redirect: bool = False,
    ) -> dict:
        """
        获取文件的下载或预览链接。

        POST /api/v4/file/url
        请求体:
        {
            "uris": ["/My Files/photo.jpg"],
            "download": false,    // true = 强制下载，false = 预览
            "redirect": false     // true = 直接 302 跳转（仅单个 URI 有效）
        }
        响应:
        {
            "code": 0,
            "data": {
                "urls": [{ "url": "https://...", "expires": "2024-..." }],
                "expires": "2024-01-02T00:00:00Z"
            }
        }
        """
        payload = {"uris": uris, "download": download, "redirect": redirect}
        resp = self.session.post(self._url("/file/url"), json=payload)
        result = self._check(resp)
        data = result["data"]
        for item in data.get("urls", []):
            action = "下载" if download else "预览"
            print(f"[{action}链接] {item.get('url', '(无 URL)')}")
        return data

    def download_file(self, uri: str, save_path: str) -> None:
        """
        下载文件并保存到本地。

        步骤:
          1. 调用 get_file_url 获取带签名的临时下载链接
          2. 直接 GET 该链接，流式写入本地文件
        """
        url_data = self.get_file_url([uri], download=True)
        urls = url_data.get("urls", [])
        if not urls:
            raise RuntimeError("未获取到下载链接")

        download_url = urls[0]["url"]
        print(f"[下载] 开始下载: {download_url}")
        with requests.get(download_url, stream=True) as r:
            r.raise_for_status()
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)
        print(f"[下载] 文件已保存到: {save_path}")

    # ─────────────────────────────────────────
    # 7. 文件操作
    # ─────────────────────────────────────────

    def list_files(self, uri: str = "/") -> dict:
        """
        列出指定目录下的文件和子目录。

        GET /api/v4/file?uri=<encoded_uri>
        响应: { "code": 0, "data": { "objects": [...], "pagination": {...} } }
        """
        resp = self.session.get(self._url("/file"), params={"uri": uri})
        result = self._check(resp)
        objects = result["data"].get("objects", [])
        print(f"[文件列表] '{uri}' 下共 {len(objects)} 个对象")
        for obj in objects[:10]:  # 最多打印前 10 条
            print(f"  - {obj.get('name')} ({obj.get('type')})")
        return result["data"]

    def get_file_info(self, uri: str) -> dict:
        """
        获取文件元数据信息。

        GET /api/v4/file/info?sources=<uri>
        响应: { "code": 0, "data": { ... } }
        """
        resp = self.session.get(self._url("/file/info"), params={"sources": uri})
        result = self._check(resp)
        info = result["data"]
        print(f"[文件信息] {uri}: {info}")
        return info


# ─────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────

def _guess_mime(filename: str) -> str:
    """根据文件扩展名猜测 MIME 类型。"""
    import mimetypes
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


# ─────────────────────────────────────────────
# 各存储类型配置示例
# ─────────────────────────────────────────────

# 命名规则变量说明：
#   {uid}        - 用户 ID
#   {path}       - 文件所在路径（不含文件名）
#   {originName} - 原始文件名（含扩展名）
#   {timestamp}  - 当前 Unix 时间戳
#   {date}       - 当前日期 YYYY-MM-DD
#   {year}       - 年，{month} - 月，{day} - 日

POLICY_EXAMPLES = {
    # ── 本机存储 ──────────────────────────────
    "local": {
        "name": "本机存储",
        "type": "local",
        "is_private": True,
        "max_size": 0,                          # 0 = 不限制
        "dir_name_rule": "uploads/{uid}/{path}",
        "file_name_rule": "{originName}",
        "settings": {
            "pre_allocate": False,              # 是否预分配磁盘空间
        },
    },

    # ── 从机（分布式）存储 ─────────────────────
    "remote": {
        "name": "从机存储",
        "type": "remote",
        "server": "https://slave.example.com",  # 从机节点地址
        "is_private": True,
        "max_size": 5368709120,                 # 5 GB
        "dir_name_rule": "uploads/{uid}/{path}",
        "file_name_rule": "{originName}",
        "settings": {
            "chunk_size": 26214400,             # 25 MB 分片
            "tps_limit": 0.0,                   # 0 = 不限制 API 速率
            "tps_limit_burst": 0,
        },
    },

    # ── Amazon S3 / 兼容协议（MinIO 等）────────
    "s3": {
        "name": "S3 存储",
        "type": "s3",
        "server": "s3.amazonaws.com",           # S3 端点，MinIO 填写内网地址
        "bucket_name": "my-cloudreve-bucket",
        "is_private": True,
        "access_key": "AKIAIOSFODNN7EXAMPLE",
        "secret_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "max_size": 0,
        "dir_name_rule": "{uid}/{path}",
        "file_name_rule": "{originName}",
        "settings": {
            "region": "us-east-1",
            "chunk_size": 26214400,             # 25 MB（S3 最小 5 MB，最大 5 GB）
            "s3_path_style": False,             # True = 路径风格（适用于 MinIO）
            "server_side_endpoint": "",         # 服务端内网端点（可选）
            "tps_limit": 0.0,
            "tps_limit_burst": 0,
            "relay": False,                     # True = 通过服务器中转上传
            "s3_delete_batch_size": 1000,       # 批量删除每批数量
            "stream_saver": False,              # 浏览器流式下载
            "thumb_exts": ["jpg", "jpeg", "png", "gif", "webp"],
            "thumb_support_all_exts": False,
            "media_meta_exts": ["mp3", "mp4", "flac"],
        },
    },

    # ── 阿里云 OSS ───────────────────────────
    "oss": {
        "name": "阿里云 OSS",
        "type": "oss",
        "server": "oss-cn-hangzhou.aliyuncs.com",
        "bucket_name": "my-bucket",
        "is_private": True,
        "access_key": "LTAI5tXXXXXXXXXXXXXXXXXX",
        "secret_key": "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
        "max_size": 0,
        "dir_name_rule": "{uid}/{path}",
        "file_name_rule": "{originName}",
        "settings": {
            "region": "oss-cn-hangzhou",
            "chunk_size": 26214400,
            "server_side_endpoint": "oss-cn-hangzhou-internal.aliyuncs.com",
            "use_cname": False,                 # 使用自定义 CNAME 域名
            "cdn_domain": "",                   # CDN 加速域名（可选）
            "tps_limit": 0.0,
            "relay": False,
            "thumb_exts": ["jpg", "jpeg", "png"],
            "media_meta_exts": ["mp4", "mp3"],
        },
    },

    # ── 腾讯云 COS ───────────────────────────
    "cos": {
        "name": "腾讯云 COS",
        "type": "cos",
        "server": "cos.ap-guangzhou.myqcloud.com",
        "bucket_name": "my-bucket-1234567890",  # 需包含 AppID 后缀
        "is_private": True,
        "access_key": "<Your_SecretId>",
        "secret_key": "<Your_SecretKey>",
        "max_size": 0,
        "dir_name_rule": "{uid}/{path}",
        "file_name_rule": "{originName}",
        "settings": {
            "region": "ap-guangzhou",
            "chunk_size": 26214400,
            "server_side_endpoint": "cos.ap-guangzhou.myqcloud.com",
            "cdn_domain": "",
            "tps_limit": 0.0,
            "relay": False,
            "thumb_exts": ["jpg", "png"],
            "media_meta_exts": ["mp4"],
        },
    },

    # ── 华为云 OBS ───────────────────────────
    "obs": {
        "name": "华为云 OBS",
        "type": "obs",
        "server": "obs.cn-north-4.myhuaweicloud.com",
        "bucket_name": "my-obs-bucket",
        "is_private": True,
        "access_key": "XXXXXXXXXXXXXXXXXXXXXXXXXX",
        "secret_key": "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
        "max_size": 0,
        "dir_name_rule": "{uid}/{path}",
        "file_name_rule": "{originName}",
        "settings": {
            "region": "cn-north-4",
            "chunk_size": 26214400,
            "server_side_endpoint": "obs.cn-north-4.myhuaweicloud.com",
            "tps_limit": 0.0,
            "relay": False,
        },
    },

    # ── 金山云 KS3 ───────────────────────────
    "ks3": {
        "name": "金山云 KS3",
        "type": "ks3",
        "server": "ks3-cn-beijing.ksyuncs.com",
        "bucket_name": "my-ks3-bucket",
        "is_private": True,
        "access_key": "XXXXXXXXXXXXXXXXXXXXXXXX",
        "secret_key": "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
        "max_size": 0,
        "dir_name_rule": "{uid}/{path}",
        "file_name_rule": "{originName}",
        "settings": {
            "region": "BEIJING",
            "chunk_size": 26214400,
            "tps_limit": 0.0,
            "relay": False,
        },
    },

    # ── 七牛云 Kodo ──────────────────────────
    "qiniu": {
        "name": "七牛云 Kodo",
        "type": "qiniu",
        "server": "up.qiniup.com",              # 上传域名（按 Zone 选择）
        "bucket_name": "my-qiniu-bucket",
        "is_private": True,
        "access_key": "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
        "secret_key": "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
        "max_size": 0,
        "dir_name_rule": "{uid}/{path}",
        "file_name_rule": "{originName}",
        "settings": {
            "region": "z0",                     # z0=华东 z1=华北 z2=华南 na0=北美
            "chunk_size": 26214400,
            "cdn_domain": "https://cdn.example.com",
            "tps_limit": 0.0,
            "relay": False,
            "thumb_exts": ["jpg", "png"],
            "media_meta_exts": ["mp4", "mp3"],
        },
    },

    # ── 又拍云 ───────────────────────────────
    "upyun": {
        "name": "又拍云",
        "type": "upyun",
        "server": "https://v0.api.upyun.com",
        "bucket_name": "my-upyun-bucket",       # 服务名（空间名）
        "is_private": False,
        "access_key": "upyun_operator_name",    # 操作员名称
        "secret_key": "upyun_operator_password",
        "max_size": 0,
        "dir_name_rule": "{uid}/{path}",
        "file_name_rule": "{originName}",
        "settings": {
            "token": "",                        # 防盗链 Token（可选）
            "cdn_domain": "https://cdn.example.com",
            "tps_limit": 0.0,
            "relay": False,
            "thumb_exts": ["jpg", "png"],
        },
    },

    # ── Microsoft OneDrive / SharePoint ──────
    "onedrive": {
        "name": "OneDrive 存储",
        "type": "onedrive",
        "bucket_name": "YOUR_AZURE_APP_CLIENT_ID",
        "is_private": True,
        "secret_key": "YOUR_AZURE_APP_CLIENT_SECRET",
        "max_size": 0,
        "dir_name_rule": "{uid}/{path}",
        "file_name_rule": "{originName}",
        "settings": {
            "od_driver": "",                    # SharePoint Drive 路径，留空则使用个人 OneDrive
                                                # 例: "sites/<site-id>/drive"
            "od_redirect": "",                  # OAuth 回调地址（创建策略后由系统自动填充）
            "chunk_size": 52428800,             # 50 MB（OneDrive 推荐）
            "tps_limit": 0.0,
            "relay": False,
            "thumb_exts": ["jpg", "png"],
            "media_meta_exts": ["mp4"],
        },
    },
}


# ─────────────────────────────────────────────
# 主演示流程
# ─────────────────────────────────────────────

def demo_authentication(client: CloudreveClient) -> None:
    """演示登录与令牌刷新。"""
    print("\n" + "=" * 60)
    print("1. 用户认证")
    print("=" * 60)
    client.login(ADMIN_EMAIL, ADMIN_PASSWORD)
    # 刷新令牌（可选，access_token 过期时使用）
    # client.refresh_token()


def demo_list_and_get_policies(client: CloudreveClient) -> None:
    """演示列出并查看存储策略。"""
    print("\n" + "=" * 60)
    print("2. 列出存储策略")
    print("=" * 60)
    data = client.list_storage_policies(page=1, page_size=10)
    policies = data.get("policies") or []

    if policies:
        first_id = policies[0]["id"]
        print(f"\n查看第一条策略（ID={first_id}）详情：")
        client.get_storage_policy(first_id, count_entity=True)

    # 按类型过滤（只列出 S3 策略）
    print("\n只列出 S3 策略：")
    client.list_storage_policies(policy_type="s3")


def demo_create_update_delete_policy(client: CloudreveClient) -> None:
    """演示创建、更新、删除存储策略。"""
    print("\n" + "=" * 60)
    print("3. 创建 / 更新 / 删除存储策略")
    print("=" * 60)

    # 创建 S3 策略
    s3_policy = POLICY_EXAMPLES["s3"].copy()
    s3_policy["name"] = "示例 S3 策略（测试）"
    created = client.create_storage_policy(s3_policy)
    new_id = created["id"]

    # 更新：修改策略名称
    update_payload = {"name": "示例 S3 策略（已更新）"}
    client.update_storage_policy(new_id, update_payload)

    # 删除刚创建的策略（仅演示，若存在文件则会失败）
    client.delete_storage_policy(new_id)


def demo_cors_config(client: CloudreveClient) -> None:
    """演示为云存储桶配置 CORS。"""
    print("\n" + "=" * 60)
    print("4. CORS 配置")
    print("=" * 60)
    # 假设已有 ID=2 的 S3 策略，为其创建 CORS 规则
    cors_policy = {
        "id": 2,
        "type": "s3",
        "server": "s3.amazonaws.com",
        "bucket_name": "my-bucket",
        "access_key": "AKIAIOSFODNN7EXAMPLE",
        "secret_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "settings": {"region": "us-east-1"},
    }
    client.create_cors_config(cors_policy)


def demo_onedrive_oauth(client: CloudreveClient) -> None:
    """演示 OneDrive OAuth 管理（仅打印步骤，不实际跳转）。"""
    print("\n" + "=" * 60)
    print("5. OneDrive OAuth 管理")
    print("=" * 60)
    # 步骤 1：获取回调地址（注册到 Azure 应用）
    redirect_url = client.get_onedrive_oauth_redirect_url()
    print(f"  → 请将此地址添加到 Azure 应用的 Redirect URIs: {redirect_url}")

    # 步骤 2：假设策略 ID=3 已创建（OneDrive 类型）
    # auth_url = client.get_onedrive_oauth_url(
    #     policy_id=3,
    #     app_id="YOUR_CLIENT_ID",
    #     secret="YOUR_CLIENT_SECRET",
    # )
    # print(f"  → 在浏览器中打开此地址完成授权: {auth_url}")

    # 步骤 3：用户授权后，使用回调中的 code 和 state 完成 OAuth
    # client.finish_onedrive_oauth(code="M.R3_BAY.xxx", state="3")

    # 查看凭据状态
    # client.get_onedrive_credential_status(policy_id=3)


def demo_upload(client: CloudreveClient) -> None:
    """演示文件上传（使用临时测试文件）。"""
    print("\n" + "=" * 60)
    print("6. 文件上传")
    print("=" * 60)

    # 创建一个临时测试文件（跨平台）
    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="cloudreve_test_")
    os.close(tmp_fd)
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write("Hello, Cloudreve! 这是一个测试文件。\n" * 100)

    remote_uri = "/示例上传/test_upload.txt"
    client.upload_file(local_path=tmp_path, remote_uri=remote_uri)

    # 清理临时文件
    os.remove(tmp_path)


def demo_download(client: CloudreveClient) -> None:
    """演示获取文件下载/预览链接。"""
    print("\n" + "=" * 60)
    print("7. 文件下载 / 预览")
    print("=" * 60)
    uri = "/示例上传/test_upload.txt"

    # 获取预览链接
    client.get_file_url([uri], download=False)

    # 获取下载链接
    url_data = client.get_file_url([uri], download=True)
    print(f"  下载链接有效期至: {url_data.get('expires')}")

    # 如需实际下载，取消下方注释：
    # client.download_file(uri, save_path="/tmp/downloaded_test.txt")


def demo_file_operations(client: CloudreveClient) -> None:
    """演示列出文件、查看文件信息。"""
    print("\n" + "=" * 60)
    print("8. 文件操作")
    print("=" * 60)
    client.list_files("/")
    # client.get_file_info("/示例上传/test_upload.txt")


def show_policy_config_examples() -> None:
    """打印各存储类型的配置示例（供参考）。"""
    import json
    print("\n" + "=" * 60)
    print("各存储类型配置示例（参考）")
    print("=" * 60)
    for policy_type, cfg in POLICY_EXAMPLES.items():
        print(f"\n[{policy_type}]")
        print(json.dumps(cfg, ensure_ascii=False, indent=2))


# ─────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # 打印所有存储类型配置示例
    show_policy_config_examples()

    # 初始化客户端
    client = CloudreveClient(BASE_URL)

    # 如需连接真实 Cloudreve 实例，取消以下演示代码的注释并填写正确凭据
    #
    # demo_authentication(client)
    # demo_list_and_get_policies(client)
    # demo_create_update_delete_policy(client)
    # demo_cors_config(client)
    # demo_onedrive_oauth(client)
    # demo_upload(client)
    # demo_download(client)
    # demo_file_operations(client)
    # client.logout()

    print("\n示例代码演示完毕。")
    print("请修改 BASE_URL / ADMIN_EMAIL / ADMIN_PASSWORD 后取消相应注释以连接真实实例。")
